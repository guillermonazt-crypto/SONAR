"""Clasificación de transceptores SFP (verde/amarillo/rojo).

Las lecturas DOM las guarda el worker en Puerto.optica. Manda el umbral que
publica el propio switch para ese módulo (entSensorThresholdTable); si no lo
publica se usa UmbralOptico como respaldo.
"""
import math
from datetime import datetime, timedelta

from .health import LEVEL_RANK, _worst

# Línea base de RX: promedio móvil exponencial con constante de 7 días. Una
# caída brusca queda visible unos días; un cambio permanente se vuelve la nueva
# base en lugar de alertar para siempre.
BASELINE_WINDOW = timedelta(days=7)
NO_SIGNAL_DBM = -40.0
# Predicción: regresión lineal de RX (una muestra por hora, últimos 7 días) y
# días hasta PREDICTION_TARGET_DBM, donde el enlace deja de ser confiable.
PREDICTION_TARGET_DBM = -24.0
SAMPLE_EVERY = timedelta(hours=1)
PREDICTION_WINDOW = timedelta(days=7)
SAMPLE_RETENTION = timedelta(days=14)
MIN_SAMPLES = 6
MIN_SPAN = timedelta(hours=12)
# Pendientes más suaves (dB/día) se consideran ruido de la lectura, no degradación.
MIN_SLOPE_DB_DAY = -0.05
ETA_CRITICAL_DAYS = 3
ETA_WARNING_DAYS = 7


def _reason(reasons, level, text):
    reasons.append(dict(level=level, text=text))
    return level


def effective_limits(reading, limits):
    """Umbrales que aplican a esta óptica.

    {rx|tx|temp|voltaje|bias: {baja_alarma, baja_aviso, alta_aviso, alta_alarma, origen}}:
    cada valor que el switch publica sustituye al global; origen='switch' si hay alguno.
    Voltaje y bias sólo tienen los umbrales del módulo (no hay respaldo global).
    """
    own = reading.get('umbrales') or {}
    fallback = dict(
        rx=dict(baja_aviso=limits.rx_atencion, baja_alarma=limits.rx_riesgo, alta_aviso=limits.rx_saturacion),
        tx=dict(baja_aviso=limits.tx_minimo),
        temp=dict(alta_aviso=limits.temp_atencion, alta_alarma=limits.temp_riesgo),
        voltaje={}, bias={},
    )
    result = {}
    for name, defaults in fallback.items():
        published = {key: value for key, value in (own.get(name) or {}).items() if value is not None}
        # La temperatura baja de un SFP no es un riesgo real: sólo cuenta la alta.
        if name == 'temp':
            published = {key: value for key, value in published.items() if key.startswith('alta')}
        result[name] = dict(defaults, **published, origen='switch' if published else 'global' if defaults else None)
    return result


def _check(value, entry, label, unit, digits, reasons, high_level='warning'):
    """Nivel de una métrica contra sus umbrales efectivos."""
    if value is None:
        return 'ok'
    origin = 'umbral del módulo' if entry.get('origen') == 'switch' else 'umbral global'
    shown = f'{value:.{digits}f}'
    for key, level, op, cmp in (('baja_alarma', 'critical', '≤', lambda v, t: v <= t),
                                ('alta_alarma', 'critical', '≥', lambda v, t: v >= t),
                                ('baja_aviso', 'warning', '≤', lambda v, t: v <= t),
                                ('alta_aviso', high_level, '≥', lambda v, t: v >= t)):
        limit = entry.get(key)
        if limit is not None and cmp(value, limit):
            return _reason(reasons, level, f'{label} {shown} {unit} ({op} {limit:g}, {origin})')
    return 'ok'


def assess_optic(reading, limits):
    """Devuelve (nivel, motivos, niveles por métrica) para una lectura DOM.

    reading: {rx_dbm, tx_dbm, temperatura, estado, sin_senal, admin, oper, umbrales, rx_base_dbm}.
    Un puerto deshabilitado o sin enlace no genera alertas: su láser o el del
    otro extremo están apagados a propósito o el puerto no está en uso.
    """
    reasons = []
    per_metric = dict(rx='ok', tx='ok', temp='ok', voltaje='ok', bias='ok')
    if reading.get('admin') == 'down':
        _reason(reasons, 'ok', 'Puerto deshabilitado (shutdown): no se evalúa la óptica')
        return 'ok', reasons, per_metric
    limits_now = effective_limits(reading, limits)
    rx, tx, temp = reading.get('rx_dbm'), reading.get('tx_dbm'), reading.get('temperatura')
    no_signal = reading.get('sin_senal') or (rx is not None and rx <= NO_SIGNAL_DBM)
    level = 'ok'
    if no_signal:
        if reading.get('oper') == 'up':
            per_metric['rx'] = _reason(reasons, 'warning', 'RX sin señal (-40 dBm) con el enlace arriba: revisar lectura DOM')
        else:
            _reason(reasons, 'ok', 'Sin luz en RX: enlace caído o sin fibra conectada')
        level = _worst(level, per_metric['rx'])
    else:
        per_metric['rx'] = _check(rx, limits_now['rx'], 'RX', 'dBm', 1, reasons)
        level = _worst(level, per_metric['rx'])
        base = reading.get('rx_base_dbm')
        if rx is not None and base is not None and base - rx >= limits.caida_rx:
            per_metric['rx'] = _worst(per_metric['rx'], 'warning')
            level = _worst(level, _reason(
                reasons, 'warning', f'RX cayó {base - rx:.1f} dB frente a su línea base de 7 días ({base:.1f} dBm)'))
    per_metric['tx'] = _check(tx, limits_now['tx'], 'TX', 'dBm', 1, reasons)
    per_metric['temp'] = _check(temp, limits_now['temp'], 'Temperatura', '°C', 0, reasons)
    per_metric['voltaje'] = _check(reading.get('voltaje_v'), limits_now['voltaje'], 'Voltaje', 'V', 2, reasons)
    per_metric['bias'] = _check(reading.get('bias_ma'), limits_now['bias'], 'Bias', 'mA', 1, reasons)
    for metric in ('tx', 'temp', 'voltaje', 'bias'):
        level = _worst(level, per_metric[metric])
    if reading.get('estado') == 'alerta':
        level = _worst(level, _reason(reasons, 'warning', 'El equipo reporta el sensor fuera de servicio'))
    prediction = reading.get('prediccion')
    trend = prediction_reason(prediction) if not no_signal else None
    if trend:
        per_metric['rx'] = _worst(per_metric['rx'], prediction['nivel'])
        level = _worst(level, _reason(reasons, prediction['nivel'], trend))
    return level, reasons, per_metric


def update_baseline(previous, current, now):
    """Línea base de RX (dBm) para guardar con la lectura nueva.

    Sólo aprende de lecturas con luz y el puerto habilitado; el primer valor
    visto es la base inicial, así un despliegue nuevo no genera alertas.
    """
    previous = previous or {}
    base = previous.get('rx_base_dbm')
    rx = usable_rx(current)
    if rx is None:
        return base
    if base is None:
        return rx
    try:
        elapsed = now - datetime.fromisoformat(previous['time'])
    except (KeyError, TypeError, ValueError):
        return base
    weight = 1 - math.exp(-max(0.0, elapsed / BASELINE_WINDOW))
    return round(base + (rx - base) * weight, 3)


def sort_key(item):
    return (-LEVEL_RANK[item['nivel']], item['switch']['nombre'] if item.get('switch') else item['device'], item['interfaz'])


def usable_rx(reading):
    """RX de una lectura con luz y el puerto habilitado; None si no sirve para tendencias."""
    rx = reading.get('rx_dbm')
    if rx is None or reading.get('sin_senal') or reading.get('admin') == 'down' or rx <= NO_SIGNAL_DBM:
        return None
    return rx


def predict_rx(samples, now, target=PREDICTION_TARGET_DBM):
    """Pendiente de RX (dB/día) por mínimos cuadrados y días estimados hasta `target`.

    samples: [(datetime, rx_dbm)]. Devuelve None si no hay historial suficiente, o
    {pendiente_db_dia, rx_estimado_dbm, eta_dias, nivel, muestras, desde}. eta_dias
    es None si RX no va a la baja; 0 si la recta ya cruzó el umbral.
    """
    samples = sorted(samples)
    if len(samples) < MIN_SAMPLES or samples[-1][0] - samples[0][0] < MIN_SPAN:
        return None
    origin = samples[0][0]
    xs = [(at - origin).total_seconds() / 86400 for at, _rx in samples]
    ys = [rx for _at, rx in samples]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    if not spread:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / spread
    estimate = mean_y + slope * ((now - origin).total_seconds() / 86400 - mean_x)
    eta = None
    if estimate <= target:
        eta = 0.0
    elif slope <= MIN_SLOPE_DB_DAY:
        eta = round((target - estimate) / slope, 1)
    level = 'ok'
    if eta is not None:
        level = 'critical' if eta < ETA_CRITICAL_DAYS else 'warning' if eta < ETA_WARNING_DAYS else 'ok'
    return dict(pendiente_db_dia=round(slope, 3), rx_estimado_dbm=round(estimate, 2), eta_dias=eta, nivel=level,
                muestras=len(samples), desde=origin.isoformat(), objetivo_dbm=target)


def prediction_reason(prediction):
    """Texto del motivo cuando la predicción está en atención o riesgo; None si no aplica."""
    if not prediction or prediction.get('nivel', 'ok') == 'ok':
        return None
    target, eta = prediction['objetivo_dbm'], prediction['eta_dias']
    if eta == 0:
        return f'RX estimado {prediction["rx_estimado_dbm"]:.1f} dBm: ya en {target:g} dBm o menos según su tendencia'
    return (f'RX baja {abs(prediction["pendiente_db_dia"]):.2f} dB/día: llegará a {target:g} dBm en ~{eta:g} días '
            '(revisar conectores o fibra)')

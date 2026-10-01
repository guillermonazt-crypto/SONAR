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


def _reason(reasons, level, text):
    reasons.append(dict(level=level, text=text))
    return level


def effective_limits(reading, limits):
    """Umbrales que aplican a esta óptica.

    {rx|tx|temp: {baja_alarma, baja_aviso, alta_aviso, alta_alarma, origen}}: cada
    valor que el switch publica sustituye al global; origen='switch' si hay alguno.
    """
    own = reading.get('umbrales') or {}
    fallback = dict(
        rx=dict(baja_aviso=limits.rx_atencion, baja_alarma=limits.rx_riesgo, alta_aviso=limits.rx_saturacion),
        tx=dict(baja_aviso=limits.tx_minimo),
        temp=dict(alta_aviso=limits.temp_atencion, alta_alarma=limits.temp_riesgo),
    )
    result = {}
    for name, defaults in fallback.items():
        published = {key: value for key, value in (own.get(name) or {}).items() if value is not None}
        # La temperatura baja de un SFP no es un riesgo real: sólo cuenta la alta.
        if name == 'temp':
            published = {key: value for key, value in published.items() if key.startswith('alta')}
        result[name] = dict(defaults, **published, origen='switch' if published else 'global')
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
    per_metric = dict(rx='ok', tx='ok', temp='ok')
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
    level = _worst(_worst(level, per_metric['tx']), per_metric['temp'])
    if reading.get('estado') == 'alerta':
        level = _worst(level, _reason(reasons, 'warning', 'El equipo reporta el sensor fuera de servicio'))
    return level, reasons, per_metric


def update_baseline(previous, current, now):
    """Línea base de RX (dBm) para guardar con la lectura nueva.

    Sólo aprende de lecturas con luz y el puerto habilitado; el primer valor
    visto es la base inicial, así un despliegue nuevo no genera alertas.
    """
    previous = previous or {}
    base = previous.get('rx_base_dbm')
    rx = current.get('rx_dbm')
    if rx is None or current.get('sin_senal') or current.get('admin') == 'down' or rx <= NO_SIGNAL_DBM:
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

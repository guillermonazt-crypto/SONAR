"""Clasificación de transceptores SFP (verde/amarillo/rojo) con UmbralOptico.

Las lecturas vienen de InfluxDB (measurement "optica", escrito por el worker).
"""
from .health import LEVEL_RANK, _worst


def _reason(reasons, level, text):
    reasons.append(dict(level=level, text=text))
    return level


def assess_optic(reading, limits):
    """Devuelve (nivel, motivos) para una lectura {rx_dbm, tx_dbm, temperatura, rx_max_24h, estado}."""
    reasons = []
    level = 'ok'
    rx, tx, temp = reading.get('rx_dbm'), reading.get('tx_dbm'), reading.get('temperatura')
    if rx is not None:
        if rx <= limits.rx_riesgo:
            level = _worst(level, _reason(reasons, 'critical', f'RX {rx:.1f} dBm (≤ {limits.rx_riesgo:g})'))
        elif rx <= limits.rx_atencion:
            level = _worst(level, _reason(reasons, 'warning', f'RX {rx:.1f} dBm (≤ {limits.rx_atencion:g})'))
        elif rx >= limits.rx_saturacion:
            level = _worst(level, _reason(reasons, 'warning', f'RX {rx:.1f} dBm: receptor saturado'))
        peak = reading.get('rx_max_24h')
        if peak is not None and peak - rx >= limits.caida_rx:
            level = _worst(level, _reason(reasons, 'warning', f'RX cayó {peak - rx:.1f} dB en 24 h'))
    if tx is not None and tx <= limits.tx_minimo:
        level = _worst(level, _reason(reasons, 'warning', f'TX {tx:.1f} dBm (≤ {limits.tx_minimo:g}): láser débil'))
    if temp is not None:
        if temp >= limits.temp_riesgo:
            level = _worst(level, _reason(reasons, 'critical', f'Temperatura {temp:.0f} °C (≥ {limits.temp_riesgo:g})'))
        elif temp >= limits.temp_atencion:
            level = _worst(level, _reason(reasons, 'warning', f'Temperatura {temp:.0f} °C (≥ {limits.temp_atencion:g})'))
    if reading.get('estado') == 'alerta':
        level = _worst(level, _reason(reasons, 'warning', 'El equipo reporta el sensor fuera de rango'))
    return level, reasons


def sort_key(item):
    return (-LEVEL_RANK[item['nivel']], item['switch']['nombre'] if item.get('switch') else item['device'], item['interfaz'])

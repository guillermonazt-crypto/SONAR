"""Detalle de cada óptica para la vista y el reporte: tendencia, pérdida del enlace y errores.

Complementa la última lectura DOM (Puerto.optica) con el historial horario de
MuestraOptica (sparkline, variación 24 h / 7 d), la potencia que transmite el
otro extremo cuando su vecino CDP/LLDP también publica DOM, y los contadores de
error del puerto: una fibra degradada suele subir los CRC.
"""
import re
from datetime import timedelta

from switches.models import MuestraOptica, Puerto, Switch
from switches.optics import PREDICTION_TARGET_DBM, PREDICTION_WINDOW, usable_rx

ERROR_FIELDS = ('errores_crc', 'errores_entrada', 'errores_salida', 'errores_nuevos', 'ultimo_error')
DELTA_WINDOWS = (('delta_rx_24h', timedelta(hours=24)), ('delta_rx_7d', timedelta(days=7)))
# Una muestra cuenta como "hace 24 h" si está a menos de esta distancia del momento buscado.
DELTA_TOLERANCE = timedelta(hours=3)


def port_key(name):
    """Clave para comparar nombres CDP/LLDP: 'Gi1/0/25' y 'GigabitEthernet1/0/25' -> 'gi1/0/25'."""
    match = re.match(r'\s*([A-Za-z]+)[\s-]*([\d/.:]+)\s*$', name or '')
    return f'{match.group(1)[:2].lower()}{match.group(2)}' if match else (name or '').strip().lower()


def trends(port_ids, now):
    """{puerto_id: {serie: [{time, rx_dbm, tx_dbm}], delta_rx_24h, delta_rx_7d}} de los últimos 7 días."""
    series = {}
    since = now - PREDICTION_WINDOW - DELTA_TOLERANCE
    for pk, at, rx, tx in (MuestraOptica.objects.filter(puerto_id__in=port_ids, momento__gte=since)
                           .order_by('momento').values_list('puerto_id', 'momento', 'rx_dbm', 'tx_dbm')):
        series.setdefault(pk, []).append((at, rx, tx))
    result = {}
    for pk, points in series.items():
        item = dict(serie=[dict(time=at.isoformat(), rx_dbm=rx, tx_dbm=tx) for at, rx, tx in points])
        latest_at, latest_rx, _tx = points[-1]
        for key, window in DELTA_WINDOWS:
            target = latest_at - window
            # La muestra más cercana al momento buscado, si hay una razonablemente cerca.
            at, rx, _tx = min(points, key=lambda point: abs(point[0] - target))
            item[key] = round(latest_rx - rx, 2) if abs(at - target) <= DELTA_TOLERANCE else None
        result[pk] = item
    return result


def remote_tx(ports):
    """{puerto_id: (switch remoto, puerto remoto, TX dBm)} cuando el vecino también publica DOM."""
    wanted = [port for port in ports if port.vecino_puerto and (port.vecino_ip or port.vecino_nombre)]
    if not wanted:
        return {}
    switches, by_pk = {}, {}
    for switch in Switch.objects.filter(activo=True).only('pk', 'nombre', 'hostname'):
        switches[switch.hostname] = switches[switch.nombre.lower()] = by_pk[switch.pk] = switch
    remote = {}
    for port in wanted:
        short = (port.vecino_nombre or '').split('.')[0].split('(')[0].strip().lower()
        switch = switches.get(port.vecino_ip or '') or switches.get(short)
        if switch is not None and switch.pk != port.switch_id:
            remote.setdefault(switch.pk, []).append(port)
    result = {}
    for other in Puerto.objects.filter(switch_id__in=remote, optica__isnull=False).only('switch_id', 'nombre', 'optica'):
        for port in remote[other.switch_id]:
            if port_key(other.nombre) == port_key(port.vecino_puerto):
                result[port.pk] = (by_pk[other.switch_id].nombre, other.nombre, (other.optica or {}).get('tx_dbm'))
    return result


def extras(port, reading, trend, remote):
    """Campos extra de una óptica: margen, pérdida del enlace, tendencia, errores y módulo."""
    rx = usable_rx(reading)
    trend = trend or {}
    remote_switch, remote_port, remote_power = remote or (None, None, None)
    loss = round(remote_power - rx, 2) if rx is not None and remote_power is not None else None
    return dict(
        margen_rx_db=round(rx - PREDICTION_TARGET_DBM, 2) if rx is not None else None,
        objetivo_dbm=PREDICTION_TARGET_DBM,
        perdida_enlace_db=loss,
        remoto=dict(switch=remote_switch, puerto=remote_port, tx_dbm=remote_power) if remote else None,
        serie=trend.get('serie', []),
        delta_rx_24h=trend.get('delta_rx_24h'),
        delta_rx_7d=trend.get('delta_rx_7d'),
        modulo=reading.get('modulo'),
        errores={field: (value.isoformat() if hasattr(value, 'isoformat') else value)
                 for field in ERROR_FIELDS for value in [getattr(port, field)]},
    )

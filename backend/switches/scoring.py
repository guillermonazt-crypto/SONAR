"""Severidad ponderada por plantel (semáforo del mapa del NOC).

En lugar del peor estado de un solo equipo, cada plantel suma el peso de sus
problemas abiertos, así un plantel con muchos detalles menores se distingue de
uno con una falla grave:

    puerto con errores, inestable o PoE en falla   0.5 por puerto
    equipo lento (latencia/pérdida, CPU o memoria)  1.0 por equipo
    equipo caído (sin SNMP ni ping)                 3.0 por equipo
    condición crítica (hardware, óptica, CPU…)      5.0 por equipo

Verde < 5, amarillo de 5 a 15 y rojo > 15.

Con Zabbix configurado, sus problemas activos (no suprimidos) del switch también
cuentan, sin duplicar lo que SONAR ya detectó en el mismo equipo: severidad
Desastre suma como crítico, Alta como caído y Advertencia/Media como lento.
"""

WEIGHTS = dict(puerto=0.5, lento=1.0, caido=3.0, critico=5.0)
WARNING_SCORE = 5
CRITICAL_SCORE = 15
DOWN_TYPES = ('snmp', 'lectura')
SLOW_TYPES = ('latencia', 'cpu', 'memoria')
PORT_KEYS = ('con_errores', 'inestables', 'poe_falla')
# Severidades de Zabbix: 2 Advertencia, 3 Media, 4 Alta, 5 Desastre.
ZABBIX_SLOW, ZABBIX_DOWN, ZABBIX_CRITICAL = 2, 4, 5


def device_events(device):
    """{puerto, lento, caido, critico}: cuántas veces cuenta cada peso para un switch evaluado."""
    reasons = device.get('motivos') or []
    critical = [r for r in reasons if r.get('level') == 'critical']
    down = any(r.get('tipo') in DOWN_TYPES for r in critical)
    # Sin SNMP pero con ping: el equipo está encendido y lento de responder, no caído.
    alive_without_snmp = any(r.get('level') == 'warning' and r.get('tipo') == 'snmp' for r in reasons)
    slow = alive_without_snmp or any(r.get('level') == 'warning' and r.get('tipo') in SLOW_TYPES for r in reasons)
    ports = device.get('puertos') or {}
    severe = any(r.get('tipo') not in DOWN_TYPES for r in critical)
    zabbix = (device.get('zabbix') or {}).get('severidad') or 0
    if zabbix >= ZABBIX_CRITICAL:
        severe = True
    elif zabbix >= ZABBIX_DOWN and not severe:
        down = True
    elif zabbix >= ZABBIX_SLOW and not (severe or down):
        slow = True
    return dict(puerto=sum(ports.get(key) or 0 for key in PORT_KEYS),
                lento=int(slow and not down),
                caido=int(down),
                critico=int(severe))


def score(events):
    return round(sum(WEIGHTS[kind] * count for kind, count in events.items()), 1)


def level(points):
    """Nivel del semáforo para un puntaje: ok < 5 ≤ warning ≤ 15 < critical."""
    if points > CRITICAL_SCORE:
        return 'critical'
    if points >= WARNING_SCORE:
        return 'warning'
    return 'ok'


def site_score(devices):
    """{puntaje, estado, desglose} de los switches activos de un plantel ('none' si no hay)."""
    breakdown = dict.fromkeys(WEIGHTS, 0)
    active = [device for device in devices if device.get('activo', True)]
    for device in active:
        for kind, count in device_events(device).items():
            breakdown[kind] += count
    points = score(breakdown)
    return dict(puntaje=points, estado=level(points) if active else 'none', desglose=breakdown)

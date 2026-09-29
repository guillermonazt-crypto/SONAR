"""Reportes exportables (tabla en pantalla o CSV).

Cada reporte devuelve {titulo, descripcion, columnas: [(clave, título)], filas: [dict]}.
"""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from switches.health import FLAP_CHANGES, assess, port_stats, thresholds_by_role
from switches.models import Alerta, EventoPuerto, Puerto, Switch

UNREACHABLE = 'No responde a SNMP'


def _days(params, default):
    try:
        return max(1, min(int(params.get('dias', default)), 365))
    except (TypeError, ValueError):
        return default


def _port_row(port, **extra):
    return dict(switch=port.switch.nombre, switch_id=port.switch_id, plantel=port.switch.plantel.nombre,
                puerto=port.nombre, puerto_id=port.pk, descripcion=port.descripcion or '', **extra)


def inventario(params, now):
    switches = list(Switch.objects.select_related('plantel__division'))
    stats = port_stats([s.pk for s in switches], now)
    thresholds = thresholds_by_role()
    rows = []
    for s in switches:
        level, _reasons = assess(s, stats[s.pk], thresholds[s.rol], now)
        rows.append(dict(switch=s.nombre, switch_id=s.pk, ip=s.hostname, rol=s.get_rol_display(),
                         plantel=s.plantel.nombre, division=s.plantel.division.nombre, modelo=s.modelo or '',
                         firmware=s.firmware or '', activo='Sí' if s.activo else 'No', estado=level,
                         uptime_dias=round(s.uptime_segundos / 86400, 1) if s.uptime_segundos is not None else None,
                         puertos=stats[s.pk]['total'], activos=stats[s.pk]['up']))
    return dict(titulo='Inventario de switches', descripcion='Equipos, ubicación, versión y estado actual.',
                columnas=[('switch', 'Switch'), ('ip', 'IP'), ('rol', 'Rol'), ('plantel', 'Plantel'),
                          ('division', 'División'), ('modelo', 'Modelo'), ('firmware', 'Firmware'),
                          ('activo', 'Activo'), ('estado', 'Estado'), ('uptime_dias', 'Uptime (días)'),
                          ('puertos', 'Puertos'), ('activos', 'Puertos activos')], filas=rows)


def disponibilidad(params, now):
    days = _days(params, 30)
    since = now - timedelta(days=days)
    total = days * 24 * 60
    outages = Alerta.objects.filter(Q(fin__isnull=True) | Q(fin__gt=since), inicio__lt=now)
    down = {}
    for alert in outages:
        if not any(reason.get('text') == UNREACHABLE for reason in alert.motivos):
            continue
        start, end = max(alert.inicio, since), min(alert.fin or now, now)
        down[alert.switch_id] = down.get(alert.switch_id, 0) + max(0, (end - start).total_seconds() / 60)
    rows = []
    for s in Switch.objects.select_related('plantel').filter(activo=True):
        minutes = round(down.get(s.pk, 0))
        rows.append(dict(switch=s.nombre, switch_id=s.pk, plantel=s.plantel.nombre, minutos_caido=minutes,
                         disponibilidad=round(100 - minutes * 100 / total, 3)))
    rows.sort(key=lambda row: (row['disponibilidad'], row['switch']))
    return dict(titulo=f'Disponibilidad · últimos {days} días',
                descripcion='Tiempo sin respuesta SNMP según el centro de alertas (se cuenta desde que existe el registro).',
                columnas=[('switch', 'Switch'), ('plantel', 'Plantel'), ('minutos_caido', 'Minutos sin respuesta'),
                          ('disponibilidad', 'Disponibilidad %')], filas=rows)


def puertos_errores(params, now):
    days = _days(params, 7)
    ports = (Puerto.objects.select_related('switch__plantel')
             .filter(es_fisico=True, ultimo_error__gte=now - timedelta(days=days)).order_by('-ultimo_error'))
    rows = [_port_row(p, entrada=p.errores_entrada, salida=p.errores_salida, crc=p.errores_crc,
                      nuevos=p.errores_nuevos, ultimo_error=p.ultimo_error.isoformat()) for p in ports]
    return dict(titulo=f'Puertos con errores · últimos {days} días', descripcion='Errores nuevos detectados por el worker.',
                columnas=[('switch', 'Switch'), ('puerto', 'Puerto'), ('descripcion', 'Descripción'),
                          ('entrada', 'Errores entrada'), ('salida', 'Errores salida'), ('crc', 'CRC'),
                          ('nuevos', 'Nuevos último ciclo'), ('ultimo_error', 'Último error')], filas=rows)


def puertos_sin_uso(params, now):
    days = _days(params, 30)
    limit = now - timedelta(days=days)
    ports = (Puerto.objects.select_related('switch__plantel')
             .filter(es_fisico=True, es_trunk=False, switch__activo=True).exclude(estado_operativo='up')
             .filter(Q(ultimo_activo__lt=limit) | Q(ultimo_activo__isnull=True)).order_by('switch__nombre', 'indice'))
    rows = [_port_row(p, vlan=p.vlan, sin_enlace_desde=p.ultimo_activo.isoformat() if p.ultimo_activo else 'Sin registro',
                      dias=(now - p.ultimo_activo).days if p.ultimo_activo else None) for p in ports]
    return dict(titulo=f'Puertos sin uso · más de {days} días',
                descripcion='Puertos de acceso sin enlace; candidatos a reasignar antes de comprar switches. '
                            '"Sin registro": no se ha visto activo desde que SONAR lo mide.',
                columnas=[('switch', 'Switch'), ('plantel', 'Plantel'), ('puerto', 'Puerto'), ('descripcion', 'Descripción'),
                          ('vlan', 'VLAN'), ('sin_enlace_desde', 'Sin enlace desde'), ('dias', 'Días')], filas=rows)


def puertos_inestables(params, now):
    hours = _days(dict(dias=params.get('horas', 24)), 24)
    counts = (EventoPuerto.objects.filter(momento__gte=now - timedelta(hours=hours))
              .values('puerto').annotate(cambios=Count('id')).filter(cambios__gte=FLAP_CHANGES))
    by_port = {row['puerto']: row['cambios'] for row in counts}
    ports = Puerto.objects.select_related('switch__plantel').filter(pk__in=by_port)
    rows = sorted((_port_row(p, cambios=by_port[p.pk], estado=p.estado_operativo,
                             ultimo_cambio=p.ultimo_cambio.isoformat() if p.ultimo_cambio else None) for p in ports),
                  key=lambda row: -row['cambios'])
    return dict(titulo=f'Puertos inestables · últimas {hours} h',
                descripcion=f'{FLAP_CHANGES} o más cambios up/down: revisar cable, conector o tarjeta de red.',
                columnas=[('switch', 'Switch'), ('puerto', 'Puerto'), ('descripcion', 'Descripción'),
                          ('cambios', 'Cambios'), ('estado', 'Estado'), ('ultimo_cambio', 'Último cambio')], filas=rows)


def puertos_saturados(params, now):
    ports = (Puerto.objects.select_related('switch__plantel').filter(es_fisico=True, uso_pct__gte=70).order_by('-uso_pct'))
    rows = [_port_row(p, velocidad_mbps=p.velocidad_mbps, uso_pct=p.uso_pct, entrada_bps=p.bps_entrada,
                      salida_bps=p.bps_salida, troncal='Sí' if p.es_trunk else 'No') for p in ports]
    return dict(titulo='Puertos con uso alto (≥ 70 %)', descripcion='Uso calculado entre los dos últimos sondeos.',
                columnas=[('switch', 'Switch'), ('puerto', 'Puerto'), ('descripcion', 'Descripción'), ('troncal', 'Troncal'),
                          ('velocidad_mbps', 'Velocidad (Mbps)'), ('uso_pct', 'Uso %'), ('entrada_bps', 'Entrada bps'),
                          ('salida_bps', 'Salida bps')], filas=rows)


def poe(params, now):
    powered = dict(Puerto.objects.filter(poe_estado='deliveringPower').values('switch').annotate(n=Count('id'))
                   .values_list('switch', 'n'))
    rows = []
    for s in Switch.objects.select_related('plantel').exclude(poe_presupuesto_w__isnull=True):
        used = s.poe_consumo_w or 0
        rows.append(dict(switch=s.nombre, switch_id=s.pk, plantel=s.plantel.nombre, presupuesto_w=s.poe_presupuesto_w,
                         consumo_w=used, uso_pct=round(used * 100 / s.poe_presupuesto_w, 1) if s.poe_presupuesto_w else None,
                         puertos_energizados=powered.get(s.pk, 0)))
    rows.sort(key=lambda row: -(row['uso_pct'] or 0))
    return dict(titulo='PoE por switch', descripcion='Presupuesto y consumo de energía por Ethernet (POWER-ETHERNET-MIB).',
                columnas=[('switch', 'Switch'), ('plantel', 'Plantel'), ('presupuesto_w', 'Presupuesto (W)'),
                          ('consumo_w', 'Consumo (W)'), ('uso_pct', 'Uso %'), ('puertos_energizados', 'Puertos energizados')],
                filas=rows)


def hardware(params, now):
    rows = []
    for s in Switch.objects.select_related('plantel').exclude(hardware__isnull=True):
        for item in s.hardware or []:
            rows.append(dict(switch=s.nombre, switch_id=s.pk, plantel=s.plantel.nombre, tipo=item.get('tipo'),
                             componente=item.get('nombre'), estado=item.get('estado'), valor=item.get('valor')))
    rank = {'critical': 0, 'warning': 1, 'ok': 2}
    rows.sort(key=lambda row: (rank.get(row['estado'], 3), row['switch']))
    return dict(titulo='Salud del hardware', descripcion='Temperatura, ventiladores y fuentes (CISCO-ENVMON-MIB).',
                columnas=[('switch', 'Switch'), ('plantel', 'Plantel'), ('tipo', 'Tipo'), ('componente', 'Componente'),
                          ('estado', 'Estado'), ('valor', 'Valor (°C)')], filas=rows)


def topologia(params, now):
    by_name = {}
    for s in Switch.objects.all():
        by_name[s.nombre.lower()] = s
        by_name[s.hostname] = s
    ports = (Puerto.objects.select_related('switch__plantel').exclude(vecino_nombre__isnull=True)
             .exclude(vecino_nombre='').order_by('switch__nombre', 'indice'))
    rows = []
    for p in ports:
        short = p.vecino_nombre.split('.')[0].split('(')[0].strip().lower()
        known = by_name.get(p.vecino_ip or '') or by_name.get(short)
        rows.append(_port_row(p, vecino=p.vecino_nombre, vecino_puerto=p.vecino_puerto or '',
                              plataforma=p.vecino_plataforma or '', vecino_ip=p.vecino_ip or '',
                              vecino_id=known.pk if known else None,
                              en_inventario='Sí' if known else 'No'))
    return dict(titulo='Topología (vecinos CDP)', descripcion='Enlaces descubiertos por CDP entre equipos.',
                columnas=[('switch', 'Switch'), ('puerto', 'Puerto'), ('vecino', 'Vecino'), ('vecino_puerto', 'Puerto del vecino'),
                          ('plataforma', 'Plataforma'), ('vecino_ip', 'IP'), ('en_inventario', 'En inventario')], filas=rows)


def opticas(params, now):
    from .views import build_optics
    data = build_optics()
    rows = [dict(switch=(item['switch'] or {}).get('nombre') or item['device'], puerto=item['interfaz'],
                 rx_dbm=item['rx_dbm'], tx_dbm=item['tx_dbm'], temperatura=item['temperatura'],
                 atenuacion=item['atenuacion'], nivel=item['nivel'],
                 motivos='; '.join(reason['text'] for reason in item['motivos'])) for item in data['transceptores']]
    return dict(titulo='Ópticas SFP', descripcion=data['detalle'] or 'Última lectura DOM de cada transceptor.',
                columnas=[('switch', 'Switch'), ('puerto', 'Interfaz'), ('rx_dbm', 'RX dBm'), ('tx_dbm', 'TX dBm'),
                          ('temperatura', 'Temp °C'), ('atenuacion', 'Atenuación dB'), ('nivel', 'Nivel'),
                          ('motivos', 'Motivos')], filas=rows)


REPORTS = {
    'inventario': inventario,
    'disponibilidad': disponibilidad,
    'puertos-errores': puertos_errores,
    'puertos-sin-uso': puertos_sin_uso,
    'puertos-inestables': puertos_inestables,
    'puertos-saturados': puertos_saturados,
    'poe': poe,
    'hardware': hardware,
    'topologia': topologia,
    'opticas': opticas,
}


def build(kind, params, now=None):
    report = REPORTS[kind](params, now or timezone.now())
    report['columnas'] = [dict(clave=key, titulo=title) for key, title in report['columnas']]
    report['tipo'] = kind
    return report

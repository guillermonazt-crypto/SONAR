"""Reportes exportables (tabla en pantalla o CSV).

Cada reporte devuelve {titulo, descripcion, columnas: [(clave, título)], filas: [dict]}.
"""
from datetime import datetime, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from switches.health import FLAP_CHANGES, POE_FAULT_STATES, assess, port_stats, reason_type, thresholds_by_role
from switches.models import Alerta, EventoPuerto, Puerto, Switch



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
        if not any(reason_type(reason) == 'snmp' for reason in alert.motivos):
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


# Consumo máximo por equipo según la norma (W): 802.3af y 802.3at (PoE+).
POE_CLASSES = (('capacidad_af', 15.4), ('capacidad_at', 30.0))


def poe(params, now):
    """Presupuesto, consumo y cuánto margen queda para conectar más equipos PoE."""
    ports = {}
    for row in (Puerto.objects.filter(es_fisico=True).exclude(poe_estado__isnull=True)
                .values('switch', 'poe_estado', 'estado_operativo')):
        counts = ports.setdefault(row['switch'], dict(poe=0, energizados=0, libres=0, falla=0))
        counts['poe'] += 1
        if row['poe_estado'] == 'deliveringPower':
            counts['energizados'] += 1
        elif row['poe_estado'] in POE_FAULT_STATES:
            counts['falla'] += 1
        elif row['estado_operativo'] != 'up':
            counts['libres'] += 1
    rows = []
    switches = Switch.objects.select_related('plantel').filter(activo=True).filter(
        Q(poe_presupuesto_w__isnull=False) | Q(pk__in=ports))
    for s in switches:
        counts = ports.get(s.pk, dict(poe=0, energizados=0, libres=0, falla=0))
        budget, used = s.poe_presupuesto_w, s.poe_consumo_w or 0
        free_w = round(max(0.0, budget - used), 1) if budget else None
        capacity = {key: int(free_w // watts) if free_w is not None else None for key, watts in POE_CLASSES}
        if not budget:
            ready = 'Sin presupuesto publicado'
        elif counts['falla']:
            ready = 'Revisar puertos en falla'
        elif not capacity['capacidad_af'] or not counts['libres']:
            ready = 'Sin margen' if not capacity['capacidad_af'] else 'Sin puertos PoE libres'
        else:
            ready = 'Listo'
        rows.append(dict(switch=s.nombre, switch_id=s.pk, plantel=s.plantel.nombre, presupuesto_w=budget,
                         consumo_w=s.poe_consumo_w,
                         uso_pct=round(used * 100 / budget, 1) if budget else None, disponible_w=free_w,
                         puertos_poe=counts['poe'], puertos_energizados=counts['energizados'],
                         puertos_libres=counts['libres'], puertos_falla=counts['falla'], **capacity, preparacion=ready))
    rows.sort(key=lambda row: (row['preparacion'] == 'Listo', -(row['uso_pct'] or 0), row['switch']))
    return dict(titulo='PoE por switch',
                descripcion='Presupuesto, consumo y margen para nuevos equipos (POWER-ETHERNET-MIB). Capacidad = cuántos '
                            'equipos más caben con el presupuesto restante: 802.3af hasta 15.4 W, PoE+ (802.3at) hasta 30 W. '
                            'Puertos libres: PoE sin enlace ni falla.',
                columnas=[('switch', 'Switch'), ('plantel', 'Plantel'), ('presupuesto_w', 'Presupuesto (W)'),
                          ('consumo_w', 'Consumo (W)'), ('uso_pct', 'Uso %'), ('disponible_w', 'Disponible (W)'),
                          ('puertos_energizados', 'Energizados'), ('puertos_libres', 'Libres PoE'),
                          ('puertos_falla', 'En falla'), ('capacidad_af', 'Caben 802.3af'), ('capacidad_at', 'Caben PoE+'),
                          ('preparacion', 'Preparación')],
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
                              vecino_tipo=p.vecino_tipo or '', tipo_equipo=p.get_vecino_tipo_display() or '',
                              plataforma=p.vecino_plataforma or '', vecino_ip=p.vecino_ip or '',
                              vecino_id=known.pk if known else None,
                              en_inventario='Sí' if known else 'No'))
    return dict(titulo='Topología (vecinos CDP/LLDP)', descripcion='Enlaces descubiertos por CDP y LLDP entre equipos.',
                columnas=[('switch', 'Switch'), ('puerto', 'Puerto'), ('tipo_equipo', 'Tipo'), ('vecino', 'Vecino'),
                          ('vecino_puerto', 'Puerto del vecino'), ('plataforma', 'Plataforma'), ('vecino_ip', 'IP'),
                          ('en_inventario', 'En inventario')], filas=rows)


def aps_telefonos(params, now):
    """Access points y teléfonos IP conectados, por CDP/LLDP o por la MAC del teléfono (SEPxxxx)."""
    wanted = [kind for kind in ('ap', 'telefono') if params.get('equipo') in (None, '', kind)]
    query = Q(vecino_tipo__in=wanted)
    if 'telefono' in wanted:
        query |= Q(vecino_tipo__isnull=True, mac_telefono__isnull=False) & ~Q(mac_telefono='')
    labels = dict(Puerto.TIPOS_VECINO)
    rows = []
    for p in Puerto.objects.select_related('switch__plantel').filter(query).order_by('switch__nombre', 'indice'):
        kind = p.vecino_tipo or 'telefono'
        rows.append(_port_row(p, vecino_tipo=kind, tipo_equipo=labels[kind], vecino=p.vecino_nombre or p.mac_telefono,
                              plataforma=p.vecino_plataforma or '', vecino_ip=p.vecino_ip or '',
                              vlan=p.voice_vlan if kind == 'telefono' and p.voice_vlan else p.vlan,
                              poe_w=round(p.poe_mw / 1000, 1) if p.poe_mw is not None else None))
    totals = {kind: sum(1 for row in rows if row['vecino_tipo'] == kind) for kind in ('ap', 'telefono')}
    return dict(titulo='Access points y teléfonos IP',
                descripcion=f"{totals['ap']} access points y {totals['telefono']} teléfonos detectados por CDP/LLDP.",
                columnas=[('switch', 'Switch'), ('plantel', 'Plantel'), ('puerto', 'Puerto'), ('tipo_equipo', 'Tipo'),
                          ('vecino', 'Equipo'), ('plataforma', 'Modelo'), ('vecino_ip', 'IP'), ('vlan', 'VLAN'),
                          ('poe_w', 'PoE W')], filas=rows)


def opticas(params, now):
    from .views import build_optics
    data = build_optics()
    rows = [dict(switch=(item['switch'] or {}).get('nombre') or item['device'], puerto=item['interfaz'],
                 rx_dbm=item['rx_dbm'], rx_base_dbm=item.get('rx_base_dbm'), tx_dbm=item['tx_dbm'],
                 temperatura=item['temperatura'], voltaje_v=item.get('voltaje_v'), bias_ma=item.get('bias_ma'),
                 atenuacion=item['atenuacion'], nivel=item['nivel'],
                 motivos='; '.join(reason['text'] for reason in item['motivos'])) for item in data['transceptores']]
    return dict(titulo='Ópticas SFP', descripcion=data['detalle'] or 'Última lectura DOM de cada transceptor.',
                columnas=[('switch', 'Switch'), ('puerto', 'Interfaz'), ('rx_dbm', 'RX dBm'), ('rx_base_dbm', 'RX base 7 d'),
                          ('tx_dbm', 'TX dBm'), ('temperatura', 'Temp °C'), ('voltaje_v', 'Voltaje V'),
                          ('bias_ma', 'Bias mA'), ('atenuacion', 'Atenuación dB'), ('nivel', 'Nivel'),
                          ('motivos', 'Motivos')], filas=rows)


TREND_DAYS = (7, 30)


def _mean(values):
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 1) if values else None


def _peak(values):
    values = [value for value in values if value is not None]
    return round(max(values), 1) if values else None


def _reboots(points):
    """Reinicios en la serie: el uptime baja entre dos ventanas consecutivas."""
    uptimes = [point['uptime'] for point in points if point.get('uptime') is not None]
    return sum(1 for before, after in zip(uptimes, uptimes[1:]) if after < before)


def _risk_minutes(alerts, since, now):
    return round(sum(max(0, (min(a.fin or now, now) - max(a.inicio, since)).total_seconds() / 60) for a in alerts))


def _local_day(iso):
    return timezone.localtime(datetime.fromisoformat(iso)).date().isoformat()


def tendencias(params, now):
    """CPU, memoria, tráfico, reinicios y alertas de los últimos 7 o 30 días.

    Las métricas salen de InfluxDB (bucket de largo plazo si existe). Si InfluxDB
    no responde, el reporte se entrega igual con lo que guarda Django (alertas y
    minutos en riesgo) y lo indica en la descripción.
    """
    days = _days(params, 7)
    days = min(TREND_DAYS, key=lambda option: abs(option - days))
    since = now - timedelta(days=days)
    switches = list(Switch.objects.select_related('plantel').filter(activo=True))
    alerts = {}
    for alert in Alerta.objects.filter(Q(fin__isnull=True) | Q(fin__gt=since), inicio__lt=now):
        alerts.setdefault(alert.switch_id, []).append(alert)
    detail = None
    try:
        from .history import switch_trends
        series, bucket = switch_trends([s.nombre for s in switches], days)
    except Exception as error:
        series, bucket, detail = {}, None, f'InfluxDB no respondió ({error}); sólo se muestran alertas registradas en SONAR.'
    rows = []
    for s in switches:
        points = series.get(s.nombre, [])
        episodes = alerts.get(s.pk, [])
        traffic = [max(p['entrada_bps'] or 0, p['salida_bps'] or 0) if p['entrada_bps'] is not None or p['salida_bps'] is not None
                   else None for p in points]
        rows.append(dict(
            switch=s.nombre, switch_id=s.pk, plantel=s.plantel.nombre,
            cpu_prom=_mean(p['cpu'] for p in points), cpu_max=_peak(p['cpu'] for p in points),
            memoria_prom=_mean(p['memoria'] for p in points), memoria_max=_peak(p['memoria'] for p in points),
            entrada_bps=_mean(p['entrada_bps'] for p in points), salida_bps=_mean(p['salida_bps'] for p in points),
            pico_bps=_peak(traffic), reinicios=_reboots(points) if points else None,
            alertas=sum(1 for a in episodes if a.inicio >= since), minutos_riesgo=_risk_minutes(episodes, since, now)))
    rows.sort(key=lambda row: (-row['minutos_riesgo'], -(row['cpu_max'] or 0), row['switch']))
    # Serie diaria de toda la red: promedio de CPU/memoria, suma del tráfico promedio y alertas nuevas.
    by_day = {}
    for name, points in series.items():
        for point in points:
            day = by_day.setdefault(_local_day(point['time']), dict(cpu=[], memoria=[], entrada={}, salida={}))
            day['cpu'].append(point['cpu'])
            day['memoria'].append(point['memoria'])
            for key, field in (('entrada', 'entrada_bps'), ('salida', 'salida_bps')):
                if point[field] is not None:
                    day[key].setdefault(name, []).append(point[field])
    new_alerts = {}
    for episodes in alerts.values():
        for alert in episodes:
            if alert.inicio >= since:
                key = timezone.localtime(alert.inicio).date().isoformat()
                new_alerts[key] = new_alerts.get(key, 0) + 1
    serie = []
    for offset in range(days, -1, -1):
        key = (timezone.localdate(now) - timedelta(days=offset)).isoformat()
        day = by_day.get(key)
        total = lambda side: round(sum(_mean(v) for v in day[side].values())) if day and day[side] else None
        serie.append(dict(dia=key, cpu=_mean(day['cpu']) if day else None, memoria=_mean(day['memoria']) if day else None,
                          entrada_bps=total('entrada'), salida_bps=total('salida'), alertas=new_alerts.get(key, 0)))
    source = f'InfluxDB ({bucket})' if bucket else 'sin lecturas en InfluxDB'
    return dict(titulo=f'Tendencias · últimos {days} días',
                descripcion=detail or f'Promedios y picos por switch ({source}); alertas y minutos en riesgo del centro de alertas.',
                detalle=detail, serie=serie,
                columnas=[('switch', 'Switch'), ('plantel', 'Plantel'), ('cpu_prom', 'CPU prom. %'), ('cpu_max', 'CPU máx. %'),
                          ('memoria_prom', 'Memoria prom. %'), ('memoria_max', 'Memoria máx. %'),
                          ('entrada_bps', 'Entrada prom. bps'), ('salida_bps', 'Salida prom. bps'), ('pico_bps', 'Pico bps'),
                          ('reinicios', 'Reinicios'), ('alertas', 'Alertas'), ('minutos_riesgo', 'Minutos en riesgo')],
                filas=rows)


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
    'aps-telefonos': aps_telefonos,
    'opticas': opticas,
    'tendencias': tendencias,
}


def build(kind, params, now=None):
    report = REPORTS[kind](params, now or timezone.now())
    report['columnas'] = [dict(clave=key, titulo=title) for key, title in report['columnas']]
    report['tipo'] = kind
    return report

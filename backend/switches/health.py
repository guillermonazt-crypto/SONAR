"""Clasificación de salud por switch (verde/amarillo/rojo).

Única fuente de reglas: la usan el endpoint /api/resumen/ y las alertas del
worker, así el panel y las notificaciones nunca discrepan.
"""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from .models import Switch, UmbralRol

STALE_MINUTES = 5
RECENT_REBOOT_HOURS = 24
RECENT_ERROR_HOURS = 24
# Puerto inestable: FLAP_CHANGES o más cambios up/down en la última hora.
FLAP_WINDOW = timedelta(hours=1)
FLAP_CHANGES = 4
SATURATION_PCT = 90
POE_BUDGET_PCT = 90
POE_FAULT_STATES = ('fault', 'otherFault')
HARDWARE_LABEL = {'temperatura': 'Sensor de temperatura', 'ventilador': 'Ventilador', 'fuente': 'Fuente de poder'}
LEVEL_RANK = {'ok': 0, 'warning': 1, 'critical': 2}
DEFAULTS = dict(cpu_atencion=70, cpu_riesgo=90, memoria_atencion=80, memoria_riesgo=90, puertos_riesgo=3,
                escalar_minutos=30)
# Sin fila en el admin, un core caído se escala antes que un switch de acceso.
ROLE_DEFAULTS = {'core': dict(escalar_minutos=15), 'distribution': dict(escalar_minutos=30),
                 'access': dict(escalar_minutos=60)}
THRESHOLD_FIELDS = tuple(DEFAULTS)


def thresholds_by_role():
    """Umbrales configurados en el admin; los roles sin fila usan DEFAULTS."""
    configured = {row.rol: {field: getattr(row, field) for field in THRESHOLD_FIELDS}
                  for row in UmbralRol.objects.all()}
    return {rol: configured.get(rol, {**DEFAULTS, **ROLE_DEFAULTS.get(rol, {})}) for rol, _label in Switch.ROLES}


def port_stats(switch_ids, now=None):
    """Conteos de puertos físicos por switch, calculados en la base de datos."""
    now = now or timezone.now()
    since = now - timedelta(hours=RECENT_ERROR_HOURS)
    from .models import EventoPuerto, Puerto
    rows = (Puerto.objects.filter(switch_id__in=switch_ids, es_fisico=True)
            .values('switch_id')
            .annotate(total=Count('id'),
                      up=Count('id', filter=Q(estado_operativo='up')),
                      down=Count('id', filter=Q(estado_operativo='down')),
                      con_errores=Count('id', filter=Q(ultimo_error__gte=since)),
                      danados=Count('id', filter=Q(estado='rojo')),
                      troncales=Count('id', filter=Q(es_trunk=True)),
                      voz=Count('id', filter=Q(voice_vlan__gt=0) & ~Q(voice_vlan=4096)),
                      saturados=Count('id', filter=Q(uso_pct__gte=SATURATION_PCT)),
                      poe_falla=Count('id', filter=Q(poe_estado__in=POE_FAULT_STATES))))
    empty = dict(total=0, up=0, down=0, con_errores=0, danados=0, troncales=0, voz=0, saturados=0, inestables=0,
                 poe_falla=0)
    stats = {switch_id: dict(empty, opticas=[]) for switch_id in switch_ids}
    for row in rows:
        stats[row.pop('switch_id')] = dict(row, inestables=0, opticas=[])
    for problem in optic_problems(switch_ids):
        stats[problem.pop('switch_id')]['opticas'].append(problem)
    flapping = (EventoPuerto.objects.filter(puerto__switch_id__in=switch_ids, momento__gte=now - FLAP_WINDOW)
                .values('puerto__switch_id', 'puerto_id').annotate(changes=Count('id'))
                .filter(changes__gte=FLAP_CHANGES))
    for row in flapping:
        stats[row['puerto__switch_id']]['inestables'] += 1
    return stats


def optic_problems(switch_ids):
    """Transceptores fuera de rango: [{switch_id, puerto, nivel, motivos}]."""
    from .models import Puerto, UmbralOptico
    from .optics import assess_optic
    ports = list(Puerto.objects.filter(switch_id__in=switch_ids, optica__isnull=False)
                 .values('switch_id', 'nombre', 'estado_operativo', 'optica'))
    if not ports:
        return []
    limits = UmbralOptico.actual()
    problems = []
    for port in ports:
        level, reasons, _metrics = assess_optic(dict(port['optica'], oper=port['estado_operativo']), limits)
        if level != 'ok':
            problems.append(dict(switch_id=port['switch_id'], puerto=port['nombre'], nivel=level,
                                 motivos=[r for r in reasons if r['level'] == level]))
    return problems


def _worst(a, b):
    return b if LEVEL_RANK[b] > LEVEL_RANK[a] else a


def _reason(level, kind, text):
    return dict(level=level, tipo=kind, text=text)


# Motivos guardados antes de que existiera 'tipo' (alertas antiguas): se deduce del texto.
LEGACY_REASON_TYPES = (
    ('No responde', 'snmp'), ('Aún no se ha consultado', 'lectura'), ('Última lectura', 'lectura'),
    ('CPU ', 'cpu'), ('Memoria ', 'memoria'), ('Reinicio', 'reinicio'), ('PoE ', 'poe'),
    ('errores nuevos', 'errores'), ('dañados', 'errores'), ('inestables', 'inestables'),
    ('capacidad', 'saturacion'), ('Óptica SFP', 'optica'), ('Sensor', 'hardware'), ('Ventilador', 'hardware'), ('Fuente', 'hardware'),
)


def reason_type(reason):
    """Tipo de un motivo; los antiguos sin 'tipo' se clasifican por su texto."""
    if reason.get('tipo'):
        return reason['tipo']
    text = reason.get('text', '')
    return next((kind for fragment, kind in LEGACY_REASON_TYPES if fragment in text), 'otro')


def _metric(value, warn, crit, name, kind, reasons):
    if value is None:
        return 'ok'
    if value >= crit:
        reasons.append(_reason('critical', kind, f'{name} en {round(value)}% (≥ {crit}%)'))
        return 'critical'
    if value >= warn:
        reasons.append(_reason('warning', kind, f'{name} en {round(value)}% (≥ {warn}%)'))
        return 'warning'
    return 'ok'


def assess(switch, stats, thresholds, now=None):
    """Devuelve (nivel, motivos) para un switch."""
    now = now or timezone.now()
    reasons = []
    if not switch.activo:
        return 'ok', [_reason('ok', 'inventario', 'Equipo desactivado en inventario')]
    level = 'ok'
    if switch.lectura_correcta is False:
        level = 'critical'
        reasons.append(_reason('critical', 'snmp', 'No responde a SNMP'))
    elif switch.ultima_consulta is None:
        level = 'warning'
        reasons.append(_reason('warning', 'lectura', 'Aún no se ha consultado'))
    else:
        minutes = (now - switch.ultima_consulta).total_seconds() / 60
        if minutes > STALE_MINUTES:
            level = 'warning'
            reasons.append(_reason('warning', 'lectura', f'Última lectura hace {round(minutes)} min'))
    level = _worst(level, _metric(switch.cpu_5m, thresholds['cpu_atencion'], thresholds['cpu_riesgo'], 'CPU', 'cpu', reasons))
    level = _worst(level, _metric(switch.memoria_usada_pct, thresholds['memoria_atencion'],
                                  thresholds['memoria_riesgo'], 'Memoria', 'memoria', reasons))
    if switch.ultimo_reinicio:
        hours = (now - switch.ultimo_reinicio).total_seconds() / 3600
        if hours < RECENT_REBOOT_HOURS:
            level = _worst(level, 'warning')
            reasons.append(_reason('warning', 'reinicio', f'Reinicio detectado hace {max(1, round(hours))} h'))
    if stats.get('con_errores'):
        level = _worst(level, 'warning')
        reasons.append(_reason('warning', 'errores', f"{stats['con_errores']} puerto(s) con errores nuevos en {RECENT_ERROR_HOURS} h"))
    if stats.get('danados'):
        level = _worst(level, 'warning')
        reasons.append(_reason('warning', 'errores', f"{stats['danados']} puerto(s) marcados como dañados"))
    if stats.get('inestables'):
        level = _worst(level, 'warning')
        reasons.append(_reason('warning', 'inestables', f"{stats['inestables']} puerto(s) inestables (≥ {FLAP_CHANGES} cambios en 1 h)"))
    # Condición compuesta: varios puertos fallando a la vez escalan el switch a riesgo.
    limit = thresholds.get('puertos_riesgo') or 0
    for key, what in (('con_errores', 'con errores nuevos'), ('inestables', 'inestables')):
        if limit and stats.get(key, 0) >= limit:
            level = 'critical'
            reasons.append(_reason('critical', 'compuesta',
                                   f"Falla generalizada: {stats[key]} puertos {what} a la vez (≥ {limit})"))
    if stats.get('saturados'):
        level = _worst(level, 'warning')
        reasons.append(_reason('warning', 'saturacion', f"{stats['saturados']} puerto(s) al {SATURATION_PCT}% o más de su capacidad"))
    for component in switch.hardware or []:
        if component.get('estado') in ('warning', 'critical'):
            label = HARDWARE_LABEL.get(component.get('tipo'), 'Componente')
            state = 'en falla' if component['estado'] == 'critical' else 'con advertencia'
            value = f" ({component['valor']} °C)" if component.get('valor') is not None else ''
            level = _worst(level, component['estado'])
            reasons.append(_reason(component['estado'], 'hardware', f"{label} {component.get('nombre', '')} {state}{value}".replace('  ', ' ')))
    for optic in stats.get('opticas', []):
        level = _worst(level, optic['nivel'])
        detail = '; '.join(r['text'] for r in optic['motivos'])
        reasons.append(_reason(optic['nivel'], 'optica', f"Óptica SFP {optic['puerto']}: {detail}"))
    if stats.get('poe_falla'):
        level = _worst(level, 'warning')
        reasons.append(_reason('warning', 'poe', f"{stats['poe_falla']} puerto(s) PoE en falla (el equipo conectado no recibe energía)"))
    if switch.poe_presupuesto_w and switch.poe_consumo_w is not None:
        used = switch.poe_consumo_w * 100 / switch.poe_presupuesto_w
        if used >= POE_BUDGET_PCT:
            level = _worst(level, 'warning')
            reasons.append(_reason('warning', 'poe', f'PoE al {round(used)}% del presupuesto ({switch.poe_consumo_w:g} de {switch.poe_presupuesto_w:g} W)'))
    return level, reasons


SITE_PORT_KEYS = ('total', 'up', 'con_errores', 'inestables', 'saturados')


def summarize_sites(planteles, devices, open_alerts=None, maintenance=None):
    """Estado por plantel a partir de los switches ya evaluados con assess().

    `devices`: [{plantel, activo, estado, lectura_correcta, puertos}] (el mismo
    dict que entrega /api/resumen/). El plantel toma el peor nivel de sus equipos
    activos; sin equipos activos queda como 'none'. `open_alerts` es
    {plantel_id: (abiertas, sin_reconocer)} y `maintenance` el conjunto de
    planteles con una ventana de mantenimiento vigente.
    """
    open_alerts = open_alerts or {}
    maintenance = maintenance or set()
    sites = {}
    for plantel in planteles:
        sites[plantel.pk] = dict(
            id=plantel.pk, nombre=plantel.nombre, division=plantel.division.nombre,
            estado='none', equipos=0, inactivos=0, niveles=dict(ok=0, warning=0, critical=0),
            sin_respuesta=0, puertos={key: 0 for key in SITE_PORT_KEYS},
            alertas_abiertas=open_alerts.get(plantel.pk, (0, 0))[0],
            alertas_sin_reconocer=open_alerts.get(plantel.pk, (0, 0))[1],
            mantenimiento=plantel.pk in maintenance, disponibilidad=None)
    for device in devices:
        site = sites.get(device['plantel'])
        if site is None:
            continue
        if not device['activo']:
            site['inactivos'] += 1
            continue
        site['equipos'] += 1
        site['niveles'][device['estado']] += 1
        site['estado'] = device['estado'] if site['estado'] == 'none' else _worst(site['estado'], device['estado'])
        if device['lectura_correcta'] is False:
            site['sin_respuesta'] += 1
        for key in SITE_PORT_KEYS:
            site['puertos'][key] += device['puertos'].get(key, 0)
    for site in sites.values():
        if site['equipos']:
            # Equipos que responden a SNMP en este momento.
            site['disponibilidad'] = round((site['equipos'] - site['sin_respuesta']) * 100 / site['equipos'], 1)
    order = {'critical': 0, 'warning': 1, 'ok': 2, 'none': 3}
    return sorted(sites.values(), key=lambda site: (order[site['estado']], site['nombre']))

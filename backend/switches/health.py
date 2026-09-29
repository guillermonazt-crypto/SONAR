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
LEVEL_RANK = {'ok': 0, 'warning': 1, 'critical': 2}
DEFAULTS = dict(cpu_atencion=70, cpu_riesgo=90, memoria_atencion=80, memoria_riesgo=90)


def thresholds_by_role():
    """Umbrales configurados en el admin; los roles sin fila usan DEFAULTS."""
    configured = {row.rol: dict(cpu_atencion=row.cpu_atencion, cpu_riesgo=row.cpu_riesgo,
                                memoria_atencion=row.memoria_atencion, memoria_riesgo=row.memoria_riesgo)
                  for row in UmbralRol.objects.all()}
    return {rol: configured.get(rol, dict(DEFAULTS)) for rol, _label in Switch.ROLES}


def port_stats(switch_ids, now=None):
    """Conteos de puertos físicos por switch, calculados en la base de datos."""
    now = now or timezone.now()
    since = now - timedelta(hours=RECENT_ERROR_HOURS)
    from .models import Puerto
    rows = (Puerto.objects.filter(switch_id__in=switch_ids, es_fisico=True)
            .values('switch_id')
            .annotate(total=Count('id'),
                      up=Count('id', filter=Q(estado_operativo='up')),
                      down=Count('id', filter=Q(estado_operativo='down')),
                      con_errores=Count('id', filter=Q(ultimo_error__gte=since)),
                      danados=Count('id', filter=Q(estado='rojo')),
                      troncales=Count('id', filter=Q(es_trunk=True)),
                      voz=Count('id', filter=Q(voice_vlan__gt=0) & ~Q(voice_vlan=4096))))
    empty = dict(total=0, up=0, down=0, con_errores=0, danados=0, troncales=0, voz=0)
    stats = {switch_id: dict(empty) for switch_id in switch_ids}
    for row in rows:
        stats[row.pop('switch_id')] = row
    return stats


def _worst(a, b):
    return b if LEVEL_RANK[b] > LEVEL_RANK[a] else a


def _metric(value, warn, crit, name, reasons):
    if value is None:
        return 'ok'
    if value >= crit:
        reasons.append(dict(level='critical', text=f'{name} en {round(value)}% (≥ {crit}%)'))
        return 'critical'
    if value >= warn:
        reasons.append(dict(level='warning', text=f'{name} en {round(value)}% (≥ {warn}%)'))
        return 'warning'
    return 'ok'


def assess(switch, stats, thresholds, now=None):
    """Devuelve (nivel, motivos) para un switch."""
    now = now or timezone.now()
    reasons = []
    if not switch.activo:
        return 'ok', [dict(level='ok', text='Equipo desactivado en inventario')]
    level = 'ok'
    if switch.lectura_correcta is False:
        level = 'critical'
        reasons.append(dict(level='critical', text='No responde a SNMP'))
    elif switch.ultima_consulta is None:
        level = 'warning'
        reasons.append(dict(level='warning', text='Aún no se ha consultado'))
    else:
        minutes = (now - switch.ultima_consulta).total_seconds() / 60
        if minutes > STALE_MINUTES:
            level = 'warning'
            reasons.append(dict(level='warning', text=f'Última lectura hace {round(minutes)} min'))
    level = _worst(level, _metric(switch.cpu_5m, thresholds['cpu_atencion'], thresholds['cpu_riesgo'], 'CPU', reasons))
    level = _worst(level, _metric(switch.memoria_usada_pct, thresholds['memoria_atencion'],
                                  thresholds['memoria_riesgo'], 'Memoria', reasons))
    if switch.ultimo_reinicio:
        hours = (now - switch.ultimo_reinicio).total_seconds() / 3600
        if hours < RECENT_REBOOT_HOURS:
            level = _worst(level, 'warning')
            reasons.append(dict(level='warning', text=f'Reinicio detectado hace {max(1, round(hours))} h'))
    if stats.get('con_errores'):
        level = _worst(level, 'warning')
        reasons.append(dict(level='warning', text=f"{stats['con_errores']} puerto(s) con errores nuevos en {RECENT_ERROR_HOURS} h"))
    if stats.get('danados'):
        level = _worst(level, 'warning')
        reasons.append(dict(level='warning', text=f"{stats['danados']} puerto(s) marcados como dañados"))
    return level, reasons

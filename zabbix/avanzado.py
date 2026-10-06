"""Monitoreo avanzado de SONAR en Zabbix 7.0 (lo usa init_zabbix.py --avanzado).

Todo es idempotente: la plantilla se importa con configuration.import (crea o
actualiza), y correlaciones, servicios, SLA, tablero, dependencias, inventario y
housekeeping se buscan por nombre y se actualizan en lugar de duplicarse.

- Plantilla "SONAR Cisco avanzado" (se enlaza junto a "Cisco IOS by SNMP"):
  ping rápido (30 s), uplinks a 30 s por SNMP con bulk, CRC, traps linkDown/linkUp,
  óptica RX (CISCO-ENTITY-SENSOR-MIB) y disparadores con funciones de tendencia
  (trendstl, baselinedev/baselinewma, forecast/timeleft).
- Correlación: etiquetas componente/equipo/interfaz/correlacion, disparador compuesto
  "Enlace físico dañado", dependencias acceso→core y reglas globales que cierran
  los síntomas.
- Tablero "SONAR – Planteles": Geomap (inventario location_lat/lon), SLA y problemas.
- Histórico: history 90 d, trends 365 d y compresión si la base tiene TimescaleDB.
"""
import json
import re
import time
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

TEMPLATE = 'SONAR Cisco avanzado'
TEMPLATE_GROUP = 'Templates/SONAR'
T = f'/{TEMPLATE}/'
DASHBOARD = 'SONAR – Planteles'
ROOT_SERVICE = 'SONAR · Red UAEH'
SLA_NAME = 'SONAR planteles 99.5%'
SLO = '99.5'
TIMEZONE = 'America/Mexico_City'
HIDALGO_VIEW = '20.35,-98.85,8'
FAST_PING = 'icmpping[,3]'
FAST_LOSS = 'icmppingloss[,10]'
FAST_LATENCY = 'icmppingsec[,10]'
TRAP_DOWN = 'snmptrap["linkDown|1\\.3\\.6\\.1\\.6\\.3\\.1\\.1\\.5\\.3"]'
TRAP_UP = 'snmptrap["linkUp|1\\.3\\.6\\.1\\.6\\.3\\.1\\.1\\.5\\.4"]'
PING_TRIGGER = 'SONAR: sin respuesta ICMP (30 s)'
# Ningún ifIndex coincide con este patrón: el valor por omisión de la macro por host.
NO_INDEX = '^SIN_UPLINKS$'

MACROS = {
    '{$SONAR.FAST.INTERVAL}': ('30s', 'Intervalo de ping y uplinks (10-30 s).'),
    '{$SONAR.LOSS.WARN}': ('5', 'Pérdida ICMP (%) que se considera síntoma.'),
    '{$SONAR.LATENCY.WARN}': ('0.1', 'Latencia ICMP (s) que se considera síntoma.'),
    '{$SONAR.CRC.WARN}': ('1', 'Errores CRC por segundo sostenidos en un uplink.'),
    '{$SONAR.ANOMALY.RATE}': ('0.5', 'Fracción de horas anómalas (trendstl) que dispara la anomalía.'),
    '{$SONAR.BASELINE.FACTOR}': ('2', 'Veces la línea base (baselinewma) que se considera tráfico anómalo.'),
    '{$SONAR.BASELINE.MIN.BPS}': ('10M', 'Tráfico mínimo para evaluar la línea base (evita ruido).'),
    '{$SONAR.BASELINE.DEVIATIONS}': ('3', 'Desviaciones estándar (baselinedev) para CPU fuera de lo normal.'),
    '{$SONAR.CPU.BASELINE.MIN}': ('40', 'CPU mínima (%) para avisar que salió de su línea base.'),
    '{$SONAR.CPU.MAX}': ('95', 'CPU (%) cuyo alcance pronostica timeleft.'),
    '{$SONAR.FORECAST.HORIZON}': ('7d', 'Avisar si la CPU llega al máximo antes de este plazo.'),
    '{$SONAR.OPTICAL.RX.MIN}': ('-24', 'RX (dBm) donde el enlace deja de ser confiable (igual que SONAR).'),
    '{$SONAR.OPTICAL.RX.NAME}': ('(?i)(receive|rx)', 'Sensores DOM que son potencia de recepción.'),
    '{$SONAR.OPTICAL.TIMELEFT.WARN}': ('14d', 'Avisar si la RX llegará al mínimo antes de este plazo.'),
    '{$SONAR.TREND.MIN.RATIO}': ('0.8', 'Fracción de horas con trends que exigen anomalías y líneas base (datos con huecos).'),
    '{$SONAR.TRAP.WINDOW}': ('5m', 'Tiempo que un trap linkDown mantiene el problema abierto.'),
    '{$SONAR.UPLINK.IFINDEX.MATCHES}': (NO_INDEX, 'ifIndex de los troncales; init_zabbix.py lo pone por host desde SONAR.'),
    '{$SONAR.UPLINK.IFNAME.MATCHES}': ('^(Te|Twe|Fo|Hu)', 'Nombres de interfaz que siempre son uplink.'),
    '{$SONAR.UPLINK.IFALIAS.MATCHES}': ('(?i)(uplink|troncal|trunk|core|enlace)', 'Descripciones que marcan un uplink.'),
}


def uid(*parts):
    """UUIDv4 estable (32 hex; Zabbix exige v4) para que reimportar actualice en lugar de duplicar."""
    seed = uuid.uuid5(uuid.NAMESPACE_URL, 'sonar-zabbix/' + '/'.join(parts)).bytes
    return uuid.UUID(bytes=seed, version=4).hex


def tags(**values):
    return [{'tag': key, 'value': value} for key, value in values.items()]


def trigger(name, expression, priority, *, description='', opdata='', depends=(), manual_close=False, recovery='',
            **tag_values):
    data = {'uuid': uid('trigger', name), 'name': name, 'expression': expression, 'priority': priority,
            'description': description, 'tags': tags(equipo='{HOST.HOST}', **tag_values)}
    if recovery:
        data.update(recovery_mode='RECOVERY_EXPRESSION', recovery_expression=recovery)
    if opdata:
        data['opdata'] = opdata
    if manual_close:
        data['manual_close'] = 'YES'
    if depends:
        data['dependencies'] = [{'name': dep['name'], 'expression': dep['expression']} for dep in depends]
    return data


def item(name, key, *, kind='SNMP_AGENT', oid='', delay='{$SONAR.FAST.INTERVAL}', value_type='FLOAT', units='',
         preprocessing=(), params='', history='90d', trends='365d', **tag_values):
    data = {'uuid': uid('item', key), 'name': name, 'type': kind, 'key': key, 'delay': delay,
            'value_type': value_type, 'history': history, 'tags': tags(**tag_values)}
    if value_type in ('FLOAT', 'UNSIGNED'):
        data['trends'] = trends
    else:
        data['trends'] = '0'
    if kind == 'SNMP_TRAP':
        del data['delay']
    if oid:
        data['snmp_oid'] = oid
    if units:
        data['units'] = units
    if params:
        data['params'] = params
    if preprocessing:
        data['preprocessing'] = [{'type': step, 'parameters': list(args)} for step, *args in preprocessing]
    return data


PER_SECOND = ('CHANGE_PER_SECOND', '')


def has_history(key):
    """Hay datos de hace 6 a 7 días: los pronósticos (timeleft/forecast) no extrapolan unas horas."""
    return f'count({key},1d:now-6d)>0'


def enough_trends(key, hours):
    """trendcount: al menos {$SONAR.TREND.MIN.RATIO} de las horas del periodo tienen trends (STL y línea base
    con huecos dan falsas anomalías, p. ej. con el histórico parcial que se copia de InfluxDB)."""
    return f'trendcount({key},{hours}h:now/h)>={{$SONAR.TREND.MIN.RATIO}}*{hours}'
# cpmCPUTotal1minRev de todas las CPU (switch apilado = varias): se toma la mayor.
CPU_JS = """var values = value.split('\\n').map(function (line) {
  var m = line.match(/=\\s*\\w+:\\s*(-?[0-9.]+)/); return m ? parseFloat(m[1]) : null;
}).filter(function (v) { return v !== null; });
if (!values.length) { throw 'Sin datos de cpmCPUTotal1minRev'; }
return Math.max.apply(null, values);"""


def template_export():
    """Plantilla en el formato de exportación de Zabbix 7.0 (JSON) para configuration.import."""
    ping, loss, latency = (f'{T}{FAST_PING}', f'{T}{FAST_LOSS}', f'{T}{FAST_LATENCY}')
    cpu = f'{T}sonar.cpu.util'
    items = [
        item('Ping rápido', FAST_PING, kind='SIMPLE', value_type='UNSIGNED', componente='disponibilidad'),
        item('Pérdida ICMP rápida', FAST_LOSS, kind='SIMPLE', units='%', componente='red'),
        item('Latencia ICMP rápida', FAST_LATENCY, kind='SIMPLE', units='s', componente='red'),
        item('CPU (máximo de cpmCPUTotal1minRev)', 'sonar.cpu.util', oid='walk[1.3.6.1.4.1.9.9.109.1.1.1.1.7]',
             delay='1m', units='%', preprocessing=[('JAVASCRIPT', CPU_JS)], componente='cpu'),
        item('CPU: tiempo para llegar a {$SONAR.CPU.MAX}% (timeleft 30 d)', 'sonar.cpu.timeleft', kind='CALCULATED',
             delay='1h', units='s', params='timeleft(//sonar.cpu.util,30d,{$SONAR.CPU.MAX})', componente='cpu'),
        item('Trap SNMP linkDown', TRAP_DOWN, kind='SNMP_TRAP', value_type='LOG', history='30d', componente='enlace'),
        item('Trap SNMP linkUp', TRAP_UP, kind='SNMP_TRAP', value_type='LOG', history='30d', componente='enlace'),
    ]
    unreachable = trigger(PING_TRIGGER, f'max({ping},#2)=0', 'HIGH',
                          description='Dos pings seguidos sin respuesta (cada 30 s). En los switches de acceso '
                                      'depende del mismo disparador del core de su plantel.',
                          componente='disponibilidad', correlacion='causa')
    triggers = [
        unreachable,
        trigger('SONAR: pérdida de paquetes', f'min({loss},2m)>{{$SONAR.LOSS.WARN}}', 'WARNING',
                opdata='Pérdida: {ITEM.LASTVALUE1}', depends=[unreachable], componente='red', correlacion='sintoma'),
        trigger('SONAR: latencia alta', f'avg({latency},2m)>{{$SONAR.LATENCY.WARN}}', 'WARNING',
                opdata='Latencia: {ITEM.LASTVALUE1}', depends=[unreachable], componente='red', correlacion='sintoma'),
        trigger('SONAR: CPU anómala (STL)', f'trendstl({cpu},168h:now/h,3h,1d,3,"mad")>{{$SONAR.ANOMALY.RATE}} and {enough_trends(cpu, 168)}', 'WARNING',
                description='Descomposición STL de las tendencias horarias de 7 días (estacionalidad diaria): '
                            'más de {$SONAR.ANOMALY.RATE} de las últimas 3 h fuera de 3 MAD.',
                componente='cpu', analisis='anomalia'),
        trigger('SONAR: CPU fuera de su línea base',
                f'baselinedev({cpu},1h:now/h,"d",7)>{{$SONAR.BASELINE.DEVIATIONS}} and '
                f'trendavg({cpu},1h:now/h)>{{$SONAR.CPU.BASELINE.MIN}} and {enough_trends(cpu, 168)}', 'WARNING',
                description='La última hora se separa más de {$SONAR.BASELINE.DEVIATIONS} desviaciones de la misma '
                            'hora de los 7 días anteriores.', componente='cpu', analisis='linea_base'),
        trigger('SONAR: CPU llegará a {$SONAR.CPU.MAX}% en menos de {$SONAR.FORECAST.HORIZON}',
                f'last({T}sonar.cpu.timeleft)<{{$SONAR.FORECAST.HORIZON}} and {has_history(cpu)}', 'AVERAGE',
                opdata='Faltan {ITEM.LASTVALUE1}',
                description='timeleft sobre 30 días de historia; sólo con al menos 6 días de datos.',
                componente='cpu', analisis='pronostico'),
        trigger('SONAR: trap linkDown recibido', f'nodata({T}{TRAP_DOWN},{{$SONAR.TRAP.WINDOW}})=0', 'AVERAGE',
                opdata='{ITEM.LASTVALUE1}', manual_close=True,
                description='El switch avisó al instante que una interfaz cayó (requiere snmp-server host).',
                componente='enlace', correlacion='causa', origen='trap'),
    ]
    template = {
        'uuid': uid('template', TEMPLATE), 'template': TEMPLATE, 'name': TEMPLATE,
        'description': 'SONAR: ping rápido, uplinks a 30 s, CRC, traps, óptica y disparadores con funciones de '
                       'tendencia (trendstl, baselinedev/wma, forecast/timeleft). Generada por init_zabbix.py '
                       '--avanzado; los cambios hechos a mano se pierden al volver a correrlo.',
        'groups': [{'name': TEMPLATE_GROUP}],
        'items': items,
        'discovery_rules': [uplink_discovery(ping, loss, latency), optical_discovery()],
        'macros': [{'macro': name, 'value': value, 'description': text} for name, (value, text) in MACROS.items()],
        'tags': tags(sonar='avanzado'),
    }
    return {'zabbix_export': {'version': '7.0', 'template_groups': [{'uuid': uid('group', TEMPLATE_GROUP),
                                                                     'name': TEMPLATE_GROUP}],
                              'templates': [template], 'triggers': triggers}}


def prototype(name, key, oid='', **options):
    data = item(name, key, oid=oid, interfaz='{#IFNAME}', **options)
    data['uuid'] = uid('prototype', key)
    return data


def uplink_discovery(ping, loss, latency):
    """Troncales (ifIndex de SONAR, nombre o descripción) consultados cada 30 s por SNMP bulk."""
    k = lambda key: f'{T}{key}[{{#SNMPINDEX}}]'
    crc, rx_in, tx_out = k('sonar.uplink.crc'), k('sonar.uplink.in'), k('sonar.uplink.out')
    damaged = trigger('SONAR: enlace físico dañado en {#IFNAME}',
                      f'min({crc},5m)>{{$SONAR.CRC.WARN}} and (avg({loss},5m)>{{$SONAR.LOSS.WARN}} or '
                      f'avg({latency},5m)>{{$SONAR.LATENCY.WARN}})', 'HIGH',
                      opdata='CRC: {ITEM.LASTVALUE1} · pérdida: {ITEM.LASTVALUE2} · latencia: {ITEM.LASTVALUE3}',
                      description='Disparador compuesto: errores CRC sostenidos en el uplink y, a la vez, pérdida o '
                                  'latencia hacia el switch. Suprime los síntomas (CRC, pérdida, latencia) del equipo.',
                      componente='enlace', interfaz='{#IFNAME}', correlacion='causa')
    crc_alone = trigger('SONAR: errores CRC en {#IFNAME}', f'min({crc},5m)>{{$SONAR.CRC.WARN}}', 'WARNING',
                        opdata='{ITEM.LASTVALUE1}', depends=[damaged],
                        componente='enlace', interfaz='{#IFNAME}', correlacion='sintoma')
    crc_baseline = trigger('SONAR: CRC de {#IFNAME} sobre su línea base',
                           f'trendavg({crc},1h:now/h)>{{$SONAR.CRC.WARN}} and '
                           f'trendavg({crc},1h:now/h)>3*baselinewma({crc},1h:now/h,"d",7) and '
                           f'{enough_trends(crc, 168)}', 'WARNING',
                           depends=[damaged], description='Última hora contra el promedio ponderado de la misma hora '
                                                          'de los 7 días anteriores.',
                           componente='enlace', interfaz='{#IFNAME}', correlacion='sintoma', analisis='linea_base')
    status = k('sonar.uplink.status')
    down = trigger('SONAR: uplink {#IFNAME} caído', f'last({status},#1)=2 and last({status},#2)=1', 'HIGH',
                   recovery=f'last({status})=1', manual_close=True,
                   description='ifOperStatus pasó de up a down (consulta cada 30 s). Los troncales que nunca han '
                               'tenido enlace no disparan; se cierra cuando la interfaz vuelve a up.',
                   componente='enlace', interfaz='{#IFNAME}', correlacion='causa')
    anomaly = trigger('SONAR: tráfico anómalo en {#IFNAME} (STL)',
                      f'(trendstl({rx_in},336h:now/h,3h,1d,3,"mad")>{{$SONAR.ANOMALY.RATE}} or '
                      f'trendstl({tx_out},336h:now/h,3h,1d,3,"mad")>{{$SONAR.ANOMALY.RATE}}) and '
                      f'{enough_trends(rx_in, 336)}', 'WARNING',
                      componente='enlace', interfaz='{#IFNAME}', analisis='anomalia')
    baseline = trigger('SONAR: tráfico de {#IFNAME} sobre su línea base',
                       f'((trendavg({rx_in},1h:now/h)>{{$SONAR.BASELINE.FACTOR}}*baselinewma({rx_in},1h:now/h,"d",7) and '
                       f'trendavg({rx_in},1h:now/h)>{{$SONAR.BASELINE.MIN.BPS}}) or '
                       f'(trendavg({tx_out},1h:now/h)>{{$SONAR.BASELINE.FACTOR}}*baselinewma({tx_out},1h:now/h,"d",7) and '
                       f'trendavg({tx_out},1h:now/h)>{{$SONAR.BASELINE.MIN.BPS}})) and {enough_trends(rx_in, 168)}',
                       'WARNING',
                       componente='enlace', interfaz='{#IFNAME}', analisis='linea_base')
    saturation = trigger('SONAR: {#IFNAME} se saturará en 7 días (forecast)',
                         f'last({k("sonar.uplink.forecast")})>{{$IF.UTIL.MAX}} and {has_history(rx_in)}', 'AVERAGE',
                         opdata='Uso previsto: {ITEM.LASTVALUE1}', componente='enlace', interfaz='{#IFNAME}',
                         analisis='pronostico')
    triggers = [damaged, crc_alone, crc_baseline, down, anomaly, baseline, saturation]
    for data in triggers:
        data['uuid'] = uid('trigger-prototype', data['name'])
    if_oid = lambda base: f'{base}.{{#SNMPINDEX}}'
    traffic = [PER_SECOND, ('MULTIPLIER', '8')]
    return {
        'uuid': uid('lld', 'sonar.uplink.discovery'), 'name': 'Uplinks SONAR', 'type': 'SNMP_AGENT',
        'key': 'sonar.uplink.discovery', 'delay': '1h',
        'snmp_oid': 'discovery[{#IFNAME},1.3.6.1.2.1.31.1.1.1.1,{#IFALIAS},1.3.6.1.2.1.31.1.1.1.18,'
                    '{#IFTYPE},1.3.6.1.2.1.2.2.1.3]',
        'filter': {'evaltype': 'FORMULA', 'formula': '(A or B or C) and D', 'conditions': [
            {'macro': '{#SNMPINDEX}', 'value': '{$SONAR.UPLINK.IFINDEX.MATCHES}', 'formulaid': 'A'},
            {'macro': '{#IFNAME}', 'value': '{$SONAR.UPLINK.IFNAME.MATCHES}', 'formulaid': 'B'},
            {'macro': '{#IFALIAS}', 'value': '{$SONAR.UPLINK.IFALIAS.MATCHES}', 'formulaid': 'C'},
            {'macro': '{#IFTYPE}', 'value': '^6$', 'formulaid': 'D'}]},
        'description': 'Uplinks: ifIndex de los troncales que conoce SONAR, nombres Te/Twe/Fo/Hu o descripción.',
        'item_prototypes': [
            prototype('Uplink {#IFNAME}({#IFALIAS}): estado operativo', 'sonar.uplink.status[{#SNMPINDEX}]',
                      if_oid('1.3.6.1.2.1.2.2.1.8'), value_type='UNSIGNED', componente='enlace'),
            prototype('Uplink {#IFNAME}({#IFALIAS}): bits recibidos', 'sonar.uplink.in[{#SNMPINDEX}]',
                      if_oid('1.3.6.1.2.1.31.1.1.1.6'), units='bps', preprocessing=traffic, componente='enlace'),
            prototype('Uplink {#IFNAME}({#IFALIAS}): bits enviados', 'sonar.uplink.out[{#SNMPINDEX}]',
                      if_oid('1.3.6.1.2.1.31.1.1.1.10'), units='bps', preprocessing=traffic, componente='enlace'),
            prototype('Uplink {#IFNAME}({#IFALIAS}): errores de entrada', 'sonar.uplink.errors[{#SNMPINDEX}]',
                      if_oid('1.3.6.1.2.1.2.2.1.14'), units='err/s', preprocessing=[PER_SECOND], componente='enlace'),
            prototype('Uplink {#IFNAME}({#IFALIAS}): errores CRC (FCS)', 'sonar.uplink.crc[{#SNMPINDEX}]',
                      if_oid('1.3.6.1.2.1.10.7.2.1.3'), units='err/s', preprocessing=[PER_SECOND], componente='enlace'),
            prototype('Uplink {#IFNAME}({#IFALIAS}): velocidad', 'sonar.uplink.speed[{#SNMPINDEX}]',
                      if_oid('1.3.6.1.2.1.31.1.1.1.15'), delay='1h', value_type='UNSIGNED', units='bps',
                      preprocessing=[('MULTIPLIER', '1000000')], componente='enlace'),
            prototype('Uplink {#IFNAME}({#IFALIAS}): uso previsto en 7 días (forecast 30 d)',
                      'sonar.uplink.forecast[{#SNMPINDEX}]', kind='CALCULATED', delay='1h', units='%',
                      params='100*max(forecast(//sonar.uplink.in[{#SNMPINDEX}],30d,7d),'
                             'forecast(//sonar.uplink.out[{#SNMPINDEX}],30d,7d))/last(//sonar.uplink.speed[{#SNMPINDEX}])',
                      componente='enlace', analisis='pronostico'),
        ],
        'trigger_prototypes': triggers,
    }


def optical_discovery():
    """Potencia RX de los transceptores (sensores dBm de CISCO-ENTITY-SENSOR-MIB, como el worker de SONAR)."""
    rx = f'{T}sonar.optical.rx[{{#SNMPINDEX}}]'
    port = '{{#SENSOR_NAME}.regsub("^(\\S+)", "\\1")}'
    low = trigger('SONAR: RX óptica baja en {#SENSOR_NAME}',
                  f'max({rx},15m)<{{$SONAR.OPTICAL.RX.MIN}} and last({rx})>-40', 'AVERAGE',
                  opdata='RX: {ITEM.LASTVALUE1}', componente='optica', interfaz=port, correlacion='causa')
    triggers = [
        low,
        trigger('SONAR: RX de {#SENSOR_NAME} llegará a {$SONAR.OPTICAL.RX.MIN} dBm pronto (timeleft)',
                f'last({T}sonar.optical.rx.timeleft[{{#SNMPINDEX}}])<{{$SONAR.OPTICAL.TIMELEFT.WARN}} and '
                f'{has_history(rx)}', 'WARNING',
                opdata='Faltan {ITEM.LASTVALUE1}', depends=[low], componente='optica', interfaz=port,
                analisis='pronostico'),
        trigger('SONAR: RX anómala en {#SENSOR_NAME} (STL)',
                f'trendstl({rx},336h:now/h,6h,1d,3,"mad")>{{$SONAR.ANOMALY.RATE}} and {enough_trends(rx, 336)}',
                'WARNING',
                depends=[low], componente='optica', interfaz=port, analisis='anomalia'),
    ]
    for data in triggers:
        data['uuid'] = uid('trigger-prototype', data['name'])

    def optical(name, key, **options):
        data = item(name, key, componente='optica', interfaz=port, **options)
        data['uuid'] = uid('prototype', key)
        return data
    return {
        'uuid': uid('lld', 'sonar.optical.discovery'), 'name': 'Óptica RX SONAR', 'type': 'SNMP_AGENT',
        'key': 'sonar.optical.discovery', 'delay': '1h',
        'snmp_oid': 'discovery[{#SENSOR_TYPE},1.3.6.1.4.1.9.9.91.1.1.1.1.1,{#SENSOR_PRECISION},'
                    '1.3.6.1.4.1.9.9.91.1.1.1.1.3,{#SENSOR_NAME},1.3.6.1.2.1.47.1.1.1.1.7]',
        'filter': {'evaltype': 'AND', 'conditions': [
            {'macro': '{#SENSOR_TYPE}', 'value': '^14$', 'formulaid': 'A'},
            {'macro': '{#SENSOR_NAME}', 'value': '{$SONAR.OPTICAL.RX.NAME}', 'formulaid': 'B'}]},
        'item_prototypes': [
            optical('{#SENSOR_NAME}: potencia RX', 'sonar.optical.rx[{#SNMPINDEX}]',
                    oid='1.3.6.1.4.1.9.9.91.1.1.1.1.4.{#SNMPINDEX}', delay='5m', units='dBm',
                    preprocessing=[('JAVASCRIPT', "return Number(value) / Math.pow(10, Number('{#SENSOR_PRECISION}'));")]),
            optical('{#SENSOR_NAME}: tiempo para llegar a {$SONAR.OPTICAL.RX.MIN} dBm (timeleft 30 d)',
                    'sonar.optical.rx.timeleft[{#SNMPINDEX}]', kind='CALCULATED', delay='1h', units='s',
                    params='timeleft(//sonar.optical.rx[{#SNMPINDEX}],30d,{$SONAR.OPTICAL.RX.MIN})', analisis='pronostico'),
        ],
        'trigger_prototypes': triggers,
    }


IMPORT_RULES = {
    'template_groups': {'createMissing': True, 'updateExisting': True},
    'templates': {'createMissing': True, 'updateExisting': True},
    'items': {'createMissing': True, 'updateExisting': True, 'deleteMissing': True},
    'discoveryRules': {'createMissing': True, 'updateExisting': True, 'deleteMissing': True},
    'triggers': {'createMissing': True, 'updateExisting': True, 'deleteMissing': True},
    'templateLinkage': {'createMissing': True},
    'valueMaps': {'createMissing': True, 'updateExisting': True},
}


def import_template(api):
    api.call('configuration.import', {'format': 'json', 'rules': IMPORT_RULES,
                                      'source': json.dumps(template_export(), ensure_ascii=False)})
    found = api.call('template.get', {'output': ['templateid'], 'filter': {'host': [TEMPLATE]}})
    print(f'· Plantilla "{TEMPLATE}" importada.')
    return found[0]['templateid']


# --- Hosts: plantilla, uplinks, inventario y dependencias ---------------------------------------

def sonar_hosts(api):
    """Hosts de switches de SONAR (etiqueta sonar=switch) con interfaces, plantillas, etiquetas y macros."""
    return api.call('host.get', {'output': ['hostid', 'host', 'name', 'inventory_mode'],
                                 'tags': [{'tag': 'sonar', 'value': 'switch', 'operator': 1}],
                                 'selectInterfaces': ['ip'], 'selectParentTemplates': ['templateid'],
                                 'selectTags': ['tag', 'value'], 'selectMacros': ['hostmacroid', 'macro', 'value'],
                                 'selectGroups': ['groupid', 'name']}) or []


def host_tag(host, name):
    return next((tag['value'] for tag in host.get('tags', []) if tag['tag'] == name), None)


def host_ip(host):
    return next((i['ip'] for i in host.get('interfaces', []) if i.get('ip')), None)


def link_template(api, hosts, templateid):
    missing = [{'hostid': h['hostid']} for h in hosts
               if templateid not in {t['templateid'] for t in h.get('parentTemplates', [])}]
    if missing:
        api.call('host.massadd', {'hosts': missing, 'templates': [{'templateid': templateid}]})
    print(f'· "{TEMPLATE}" enlazada a {len(missing)} switches nuevos ({len(hosts)} en total).')


def uplink_pattern(indexes):
    indexes = sorted({int(i) for i in indexes if str(i).strip().lstrip('-').isdigit()})
    return '^(' + '|'.join(str(i) for i in indexes) + ')$' if indexes else NO_INDEX


def set_host_macro(api, host, macro, value):
    current = next((m for m in host.get('macros', []) if m['macro'] == macro), None)
    if current is None:
        api.call('usermacro.create', {'hostid': host['hostid'], 'macro': macro, 'value': value})
    elif current['value'] != value:
        api.call('usermacro.update', {'hostmacroid': current['hostmacroid'], 'value': value})


def apply_uplinks(api, hosts, trunks):
    """{$SONAR.UPLINK.IFINDEX.MATCHES} por host con los ifIndex de los troncales que SONAR ya conoce."""
    done = 0
    for host in hosts:
        indexes = trunks.get(host_ip(host))
        if indexes:
            set_host_macro(api, host, '{$SONAR.UPLINK.IFINDEX.MATCHES}', uplink_pattern(indexes))
            done += 1
    print(f'· Uplinks desde SONAR: {done} switches con troncales conocidos.')


def normalize(text):
    text = unicodedata.normalize('NFD', str(text or ''))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', text.lower()).strip()


def parse_coordinates(text):
    match = re.search(r'(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)', str(text or ''))
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    return (lat, lon) if abs(lat) <= 90 and abs(lon) <= 180 else None


def known_coordinates(sonar_root):
    """Tabla KNOWN de frontend/src/utils/locations.js (la misma que usa el mapa del NOC)."""
    path = Path(sonar_root) / 'frontend' / 'src' / 'utils' / 'locations.js'
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8')
    return {normalize(name): (float(lat), float(lon))
            for name, lat, lon in re.findall(r'"([^"]+)":\s*\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]', text)}


def plantel_coordinates(name, ubicaciones, known):
    """Igual que siteCoordinates() del frontend: "lat, lon" en ubicacion o la tabla por nombre."""
    return parse_coordinates(ubicaciones.get(name)) or known.get(normalize(name))


def apply_inventory(api, hosts, ubicaciones, known):
    located = 0
    for host in hosts:
        plantel = host_tag(host, 'plantel') or ''
        coords = plantel_coordinates(plantel, ubicaciones, known)
        inventory = {'location': plantel[:255], 'site_notes': 'Posición del plantel en SONAR'}
        if coords:
            inventory.update(location_lat=f'{coords[0]:.6f}'[:16], location_lon=f'{coords[1]:.6f}'[:16])
            located += 1
        api.call('host.update', {'hostid': host['hostid'], 'inventory_mode': 0, 'inventory': inventory})
    print(f'· Inventario geográfico: {located} de {len(hosts)} switches con coordenadas.')


def apply_dependencies(api, hosts):
    """En cada plantel, el ping rápido de los switches de acceso depende del core (trigger dependency)."""
    triggers = api.call('trigger.get', {'output': ['triggerid'], 'hostids': [h['hostid'] for h in hosts],
                                        'filter': {'description': PING_TRIGGER}, 'selectHosts': ['hostid'],
                                        'selectDependencies': ['triggerid']}) or []
    by_host = {t['hosts'][0]['hostid']: t for t in triggers if t.get('hosts')}
    cores = {}
    for host in hosts:
        if host_tag(host, 'rol') == 'core' and host['hostid'] in by_host:
            cores.setdefault(host_tag(host, 'plantel'), []).append(by_host[host['hostid']]['triggerid'])
    changed = 0
    for host in hosts:
        own = by_host.get(host['hostid'])
        if own is None or host_tag(host, 'rol') == 'core':
            continue
        wanted = sorted(cores.get(host_tag(host, 'plantel'), []))
        current = sorted(d['triggerid'] for d in own.get('dependencies', []))
        if wanted != current:
            api.call('trigger.update', {'triggerid': own['triggerid'],
                                        'dependencies': [{'triggerid': pk} for pk in wanted]})
            changed += 1
    print(f'· Dependencias acceso->core: {changed} actualizadas ({sum(map(len, cores.values()))} cores).')


# --- Correlación global de eventos ----------------------------------------------------------------

OLD_TAG_VALUE, NEW_TAG_VALUE, TAG_PAIR = 4, 5, 3
CLOSE_OLD, CLOSE_NEW = 0, 1


def correlation_rules():
    def value(kind, tag, val):
        return {'type': kind, 'tag': tag, 'value': val, 'operator': 0}
    same_host = {'type': TAG_PAIR, 'oldtag': 'equipo', 'newtag': 'equipo'}
    return [
        ('SONAR · causa suprime síntomas nuevos del mismo equipo',
         'Con un problema causa abierto (enlace dañado, uplink caído, trap linkDown, sin ping, RX baja) se cierran '
         'al llegar los síntomas (CRC, pérdida, latencia) del mismo switch.',
         [value(OLD_TAG_VALUE, 'correlacion', 'causa'), value(NEW_TAG_VALUE, 'correlacion', 'sintoma'), same_host],
         CLOSE_NEW),
        ('SONAR · causa cierra síntomas previos del mismo equipo',
         'Si el síntoma llegó antes que la causa, al abrirse la causa se cierran los síntomas anteriores.',
         [value(NEW_TAG_VALUE, 'correlacion', 'causa'), value(OLD_TAG_VALUE, 'correlacion', 'sintoma'), same_host],
         CLOSE_OLD),
        ('SONAR · core sin ping suprime accesos del plantel',
         'Con el core de un plantel sin respuesta, los switches de acceso del mismo plantel que dejan de responder '
         'son síntoma (además de la dependencia de disparadores).',
         [value(OLD_TAG_VALUE, 'rol', 'core'), value(OLD_TAG_VALUE, 'componente', 'disponibilidad'),
          value(NEW_TAG_VALUE, 'rol', 'access'), value(NEW_TAG_VALUE, 'componente', 'disponibilidad'),
          {'type': TAG_PAIR, 'oldtag': 'plantel', 'newtag': 'plantel'}],
         CLOSE_NEW),
    ]


def apply_correlations(api):
    existing = {c['name']: c['correlationid'] for c in api.call('correlation.get', {'output': ['name']}) or []}
    for name, description, conditions, operation in correlation_rules():
        body = {'description': description, 'status': 0,
                'filter': {'evaltype': 1, 'conditions': conditions}, 'operations': [{'type': operation}]}
        if name in existing:
            api.call('correlation.update', dict(body, correlationid=existing[name]))
        else:
            api.call('correlation.create', dict(body, name=name))
    print(f'· Correlación global: {len(correlation_rules())} reglas SONAR.')


# --- Servicios, SLA y tablero ---------------------------------------------------------------------

def find_one(api, method, key, name, field='name'):
    found = api.call(f'{method}.get', {'output': [key], 'filter': {field: name}}) or []
    return found[0][key] if found else None


def apply_services(api, planteles):
    """Servicio por plantel (problemas de disponibilidad con su etiqueta) bajo "SONAR · Red UAEH" y su SLA."""
    root = find_one(api, 'service', 'serviceid', ROOT_SERVICE)
    root_body = {'algorithm': 1, 'sortorder': 0, 'tags': tags(sonar='red'),
                 'description': 'Disponibilidad de la red de planteles de la UAEH (SONAR).'}
    if root:
        api.call('service.update', dict(root_body, serviceid=root))
    else:
        root = api.call('service.create', dict(root_body, name=ROOT_SERVICE))['serviceids'][0]
    for index, plantel in enumerate(sorted(planteles)):
        name = f'Plantel: {plantel}'
        body = {'algorithm': 1, 'sortorder': index, 'parents': [{'serviceid': root}],
                'problem_tags': [{'tag': 'plantel', 'operator': 0, 'value': plantel},
                                 {'tag': 'componente', 'operator': 0, 'value': 'disponibilidad'}],
                'tags': tags(sonar='plantel', plantel=plantel)}
        current = find_one(api, 'service', 'serviceid', name)
        if current:
            api.call('service.update', dict(body, serviceid=current))
        else:
            api.call('service.create', dict(body, name=name))
    now = datetime.now()
    sla_body = {'period': 2, 'slo': SLO, 'timezone': TIMEZONE, 'status': 1,
                'description': 'Disponibilidad mensual de cada plantel (ping de sus switches).',
                'service_tags': [{'tag': 'sonar', 'operator': 0, 'value': 'plantel'}]}
    slaid = find_one(api, 'sla', 'slaid', SLA_NAME)
    if slaid:
        api.call('sla.update', dict(sla_body, slaid=slaid))
    else:
        effective = int(time.mktime(datetime(now.year, now.month, 1).timetuple()))
        slaid = api.call('sla.create', dict(sla_body, name=SLA_NAME, effective_date=effective))['slaids'][0]
    print(f'· Servicios: {len(planteles)} planteles bajo "{ROOT_SERVICE}" y SLA "{SLA_NAME}".')
    return root, slaid


def field(kind, name, value):
    return {'type': kind, 'name': name, 'value': value}


STR, INT, GROUP, SLA = 1, 0, 2, 10


def dashboard_pages(groupids, slaid):
    groups = [field(GROUP, f'groupids.{i}', pk) for i, pk in enumerate(groupids)]
    widgets = [
        {'type': 'geomap', 'name': 'Planteles en Hidalgo', 'x': 0, 'y': 0, 'width': 44, 'height': 9,
         'fields': groups + [field(STR, 'default_view', HIDALGO_VIEW)]},
        {'type': 'slareport', 'name': f'SLA {SLO}% por plantel', 'x': 44, 'y': 0, 'width': 28, 'height': 5,
         'fields': [field(SLA, 'slaid.0', slaid), field(INT, 'show_periods', 6)]},  # todos los planteles del SLA
        {'type': 'problemsbysv', 'name': 'Problemas por severidad', 'x': 44, 'y': 5, 'width': 28, 'height': 4,
         'fields': list(groups)},
        {'type': 'problems', 'name': 'Problemas (síntomas agrupados bajo su causa)', 'x': 0, 'y': 9, 'width': 72,
         'height': 6, 'fields': groups + [field(INT, 'show_tags', 3), field(INT, 'show_timeline', 0),
                                          field(STR, 'tag_priority', 'plantel,componente,interfaz,correlacion')]},
    ]
    return [{'name': 'Planteles', 'widgets': widgets}]


def apply_dashboard(api, groupids, slaid):
    body = {'display_period': 60, 'auto_start': 1, 'private': 0, 'pages': dashboard_pages(groupids, slaid)}
    current = find_one(api, 'dashboard', 'dashboardid', DASHBOARD)
    if current:
        api.call('dashboard.update', dict(body, dashboardid=current))
    else:
        current = api.call('dashboard.create', dict(body, name=DASHBOARD))['dashboardids'][0]
    print(f'· Tablero "{DASHBOARD}" (Geomap, SLA y problemas) id {current}.')
    return current


# --- Histórico y proxy --------------------------------------------------------------------------

def apply_housekeeping(api, history_days=90, trends_days=365):
    """history N días y trends 365 d; con TimescaleDB además comprime lo mayor a 7 días."""
    current = api.call('housekeeping.get', {'output': 'extend'}) or {}
    body = {'hk_history_mode': 1, 'hk_history_global': 1, 'hk_history': f'{history_days}d',
            'hk_trends_mode': 1, 'hk_trends_global': 1, 'hk_trends': f'{trends_days}d'}
    timescale = current.get('db_extension') == 'timescaledb'
    if timescale:
        body.update(compression_status=1, compress_older='7d')
    api.call('housekeeping.update', body)
    extra = 'TimescaleDB con compresión > 7 d' if timescale else 'sin TimescaleDB (sin compresión)'
    print(f'· Housekeeping: history {history_days} d, trends {trends_days} d, {extra}.')
    return timescale


def apply_proxy(api, name):
    """Proxy activo (empuja datos al server); los hosts se le asignan con monitored_by=1."""
    body = {'operating_mode': 0, 'description': 'Proxy activo de SONAR para una zona/sede (zabbix-proxy-sqlite3).'}
    proxyid = find_one(api, 'proxy', 'proxyid', name)
    if proxyid:
        api.call('proxy.update', dict(body, proxyid=proxyid))
    else:
        proxyid = api.call('proxy.create', dict(body, name=name))['proxyids'][0]
    print(f'· Proxy activo "{name}" registrado (id {proxyid}).')
    return proxyid


def apply(api, sonar_root, trunks=None, ubicaciones=None, history_days=90):
    """Configura todo lo avanzado. trunks={ip: [ifIndex]}, ubicaciones={plantel: "lat, lon"}."""
    templateid = import_template(api)
    hosts = sonar_hosts(api)
    if not hosts:
        print('! No hay switches con la etiqueta sonar=switch: corre antes --switches.')
    link_template(api, hosts, templateid)
    apply_uplinks(api, hosts, trunks or {})
    apply_inventory(api, hosts, ubicaciones or {}, known_coordinates(sonar_root))
    apply_dependencies(api, hosts)
    apply_correlations(api)
    planteles = sorted({host_tag(h, 'plantel') for h in hosts} - {None})
    _root, slaid = apply_services(api, planteles)
    groupids = sorted({g['groupid'] for h in hosts for g in h.get('groups', []) if g['name'].startswith('SONAR/')},
                      key=int)
    apply_dashboard(api, groupids, slaid)
    apply_housekeeping(api, history_days)

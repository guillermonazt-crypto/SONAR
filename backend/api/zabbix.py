"""Zabbix como fuente en tiempo real para SONAR (opcional).

Sin ZABBIX_URL y ZABBIX_TOKEN nada de esto se consulta y SONAR funciona igual.
El token viaja en la cabecera Authorization: Bearer (Zabbix 7.2 ya no acepta el
campo "auth"). Las lecturas se guardan CACHE_SECONDS en la caché de Django y
cualquier falla se convierte en ZabbixError para que la API nunca se caiga.
"""
import json
import os
import re
import time
from datetime import datetime, timezone as dt_timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.cache import cache

TIMEOUT_SECONDS = 4
CACHE_SECONDS = 15
SEVERITIES = {0: 'Sin clasificar', 1: 'Información', 2: 'Advertencia', 3: 'Media', 4: 'Alta', 5: 'Desastre'}
# Claves de la plantilla "Cisco IOS by SNMP" (y equivalentes genéricas) que se leen con item.get.
BASIC_KEYS = ('icmpping', 'system.cpu.util', 'vm.memory.util', 'zabbix[host,snmp,available]')
INTERFACE_KEYS = ('net.if.in[', 'net.if.out[', 'net.if.in.errors[', 'net.if.out.errors[')
UPLINKS = 4
# Interfaces lógicas (VLAN, loopback, port-channel…): se omiten para no contar el tráfico dos veces.
LOGICAL_PREFIXES = ('vl', 'lo', 'po', 'nu', 'tu', 'stack', 'bdi', 'ap')
INTERFACE_PREFIXES = {'gigabitethernet': 'gi', 'tengigabitethernet': 'te', 'fastethernet': 'fa',
                      'twentyfivegige': 'twe', 'fortygigabitethernet': 'fo', 'hundredgige': 'hu',
                      'twogigabitethernet': 'tw', 'fivegigabitethernet': 'fi', 'ethernet': 'eth',
                      'port-channel': 'po', 'vlan': 'vl', 'loopback': 'lo'}


class ZabbixError(RuntimeError):
    pass


def settings():
    """(endpoint, token) o None si la integración no está configurada."""
    base = os.getenv('ZABBIX_URL', '').strip().rstrip('/')
    token = os.getenv('ZABBIX_TOKEN', '').strip()
    if not base or not token:
        return None
    return (base if base.endswith('api_jsonrpc.php') else f'{base}/api_jsonrpc.php'), token


def configured():
    return settings() is not None


def call(method, params=None, timeout=TIMEOUT_SECONDS):
    config = settings()
    if config is None:
        raise ZabbixError('Zabbix no está configurado (ZABBIX_URL y ZABBIX_TOKEN).')
    endpoint, token = config
    payload = {'jsonrpc': '2.0', 'method': method, 'params': params if params is not None else {}, 'id': 1}
    request = Request(endpoint, data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json-rpc', 'Authorization': f'Bearer {token}'})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        raise ZabbixError(f'Zabbix no disponible: {error}') from error
    if not isinstance(body, dict):
        raise ZabbixError('Respuesta inválida de Zabbix.')
    if body.get('error'):
        error = body['error']
        raise ZabbixError(f"Zabbix: {error.get('data') or error.get('message') or 'error'}")
    return body.get('result')


def cached(key, producer, seconds=CACHE_SECONDS):
    key = f'sonar-zabbix:{key}'
    value = cache.get(key)
    if value is None:
        value = producer()
        cache.set(key, value, seconds)
    return value


def status():
    """Respuesta de /api/integrations/zabbix/ (se conserva el formato anterior)."""
    if settings() is None:
        return {'configured': False, 'hosts': [], 'detail': 'Configura ZABBIX_URL y ZABBIX_TOKEN para activar la integración.'}
    try:
        return {'configured': True, 'hosts': hosts(), 'detail': None}
    except ZabbixError as error:
        return {'configured': True, 'hosts': [], 'detail': str(error)}


def hosts():
    """Hosts monitoreados con sus interfaces (cacheados)."""
    return cached('hosts', lambda: call('host.get', {
        'output': ['hostid', 'host', 'name', 'status'],
        'selectInterfaces': ['ip', 'dns', 'type', 'available', 'error'],
        'filter': {'status': 0}}) or [])


def host_available(host):
    """True/False/None según las interfaces del host (1 disponible, 2 no disponible)."""
    states = [str(i.get('available')) for i in host.get('interfaces', [])]
    if '1' in states:
        return True
    if '2' in states:
        return False
    return None


def _norm_name(value):
    return re.sub(r'[^0-9a-z]', '', (value or '').lower())


def match_switches(zabbix_hosts, switches):
    """{switch.pk: host} por IP de la interfaz; el nombre (técnico o visible) es el respaldo."""
    by_ip, by_name = {}, {}
    for host in zabbix_hosts:
        for interface in host.get('interfaces', []):
            for value in (interface.get('ip'), interface.get('dns')):
                if value:
                    by_ip.setdefault(value, host)
        for value in (host.get('host'), host.get('name')):
            if value:
                by_name.setdefault(_norm_name(value), host)
    matched = {}
    for switch in switches:
        host = by_ip.get(switch.hostname) or by_name.get(_norm_name(switch.nombre))
        if host is not None:
            matched[switch.pk] = host
    return matched


def problems():
    """Problemas activos con el hostid de su disparador, del más grave al más leve."""
    def load():
        rows = call('problem.get', {'output': ['eventid', 'objectid', 'name', 'severity', 'acknowledged', 'clock',
                                               'suppressed', 'opdata'],
                                    'source': 0, 'object': 0, 'recent': False,
                                    'sortfield': ['eventid'], 'sortorder': 'DESC', 'limit': 500}) or []
        triggerids = list({row['objectid'] for row in rows})
        owners = {}
        if triggerids:
            for trigger in call('trigger.get', {'output': ['triggerid'], 'triggerids': triggerids,
                                                'selectHosts': ['hostid']}) or []:
                owners[trigger['triggerid']] = [host['hostid'] for host in trigger.get('hosts', [])]
        for row in rows:
            row['hostids'] = owners.get(row['objectid'], [])
        rows.sort(key=lambda row: (-int(row['severity']), -int(row['clock'])))
        return rows
    return cached('problems', load)


def latest(hostids, interfaces=False):
    """{hostid: [items]} con lastvalue/lastclock de ping, CPU, memoria y (opcional) interfaces."""
    hostids = sorted({str(pk) for pk in hostids})
    if not hostids:
        return {}
    keys = BASIC_KEYS + (INTERFACE_KEYS if interfaces else ())

    def load():
        items = call('item.get', {'output': ['itemid', 'hostid', 'key_', 'name', 'lastvalue', 'lastclock', 'units',
                                             'value_type'],
                                  'hostids': hostids, 'monitored': True,
                                  'search': {'key_': list(keys)}, 'searchByAny': True, 'startSearch': True}) or []
        grouped = {}
        for item in items:
            grouped.setdefault(item['hostid'], []).append(item)
        return grouped
    return cached(f"latest:{int(interfaces)}:{','.join(hostids)}", load)


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _when(clock):
    clock = int(clock or 0)
    return datetime.fromtimestamp(clock, dt_timezone.utc).isoformat() if clock else None


def interface_name(item_name):
    """"Interface Gi1/0/1(Uplink): Bits received" → "Gi1/0/1"."""
    match = re.match(r'Interface\s+(.+?)(\(.*\))?:', item_name or '')
    return match.group(1).strip() if match else None


def short_port(name):
    """GigabitEthernet1/0/1 y Gi1/0/1 dan la misma clave para comparar puertos de SONAR y Zabbix."""
    text = (name or '').strip().lower()
    match = re.match(r'([a-z\-]+)\s*(.*)', text)
    if not match:
        return text
    prefix, rest = match.groups()
    for long, short in INTERFACE_PREFIXES.items():
        if prefix == long or (prefix.startswith(short) and long.startswith(prefix)):
            return short + rest
    return prefix + rest


def is_physical(name):
    return bool(name) and not short_port(name).startswith(LOGICAL_PREFIXES)


def summarize_items(items, interfaces=False):
    """Últimos valores legibles: ping, pérdida, latencia, CPU, memoria, SNMP y uplinks."""
    values = dict(ping=None, perdida_pct=None, latencia_ms=None, cpu=None, memoria=None, snmp=None,
                  momento=None, interfaces=[])
    ports = {}
    newest = 0
    for item in items:
        key, value = item['key_'], _number(item.get('lastvalue'))
        clock = int(item.get('lastclock') or 0)
        if not clock:
            continue
        newest = max(newest, clock)
        if key == 'icmpping':
            values['ping'] = None if value is None else value >= 1
        elif key == 'icmppingloss':
            values['perdida_pct'] = value
        elif key == 'icmppingsec':
            values['latencia_ms'] = None if value is None else round(value * 1000, 1)
        elif key.startswith('system.cpu.util'):
            values['cpu'] = value if values['cpu'] is None else max(values['cpu'], value or 0)
        elif key.startswith('vm.memory.util'):
            values['memoria'] = value if values['memoria'] is None else max(values['memoria'], value or 0)
        elif key == 'zabbix[host,snmp,available]':
            values['snmp'] = None if value is None else value == 1
        elif interfaces and key.startswith('net.if.'):
            name = interface_name(item.get('name'))
            if not is_physical(name):
                continue
            port = ports.setdefault(name, dict(nombre=name, entrada_bps=None, salida_bps=None,
                                               errores_entrada=None, errores_salida=None))
            field = {'net.if.in[': 'entrada_bps', 'net.if.out[': 'salida_bps',
                     'net.if.in.errors[': 'errores_entrada', 'net.if.out.errors[': 'errores_salida'}
            for prefix, target in field.items():
                if key.startswith(prefix):
                    port[target] = value
    for key in ('cpu', 'memoria', 'perdida_pct'):
        if values[key] is not None:
            values[key] = round(values[key], 1)
    values['momento'] = _when(newest)
    # Uplinks: las interfaces con más tráfico (los troncales suelen encabezar la lista).
    busy = sorted(ports.values(), key=lambda p: -((p['entrada_bps'] or 0) + (p['salida_bps'] or 0)))
    values['interfaces'] = busy[:UPLINKS] if interfaces else []
    return values


def problem_data(row, now, switch=None):
    severity = int(row['severity'])
    clock = int(row['clock'])
    return dict(eventid=row['eventid'], nombre=row['name'], severidad=severity,
                severidad_nombre=SEVERITIES.get(severity, str(severity)),
                reconocido=str(row.get('acknowledged')) == '1', suprimido=str(row.get('suppressed')) == '1',
                datos=row.get('opdata') or '', desde=_when(clock), antiguedad_s=max(0, int(now) - clock),
                switch=switch and dict(id=switch.pk, nombre=switch.nombre),
                plantel=switch and dict(id=switch.plantel_id, nombre=switch.plantel.nombre))


def _owners(switches):
    matched = match_switches(hosts(), switches)
    switch_of_host = {}
    for pk, host in matched.items():
        switch_of_host.setdefault(host['hostid'], pk)
    return matched, switch_of_host


def live(switches, now=None, interfaces=False):
    """Vista en vivo para /api/vivo/: problemas, disponibilidad y últimos valores por switch.

    Lanza ZabbixError si Zabbix no responde.
    """
    now = now or time.time()
    switches = list(switches)
    matched, switch_of_host = _owners(switches)
    by_pk = {s.pk: s for s in switches}
    values = latest([host['hostid'] for host in matched.values()], interfaces=interfaces)
    rows = []
    for switch in switches:
        host = matched.get(switch.pk)
        rows.append(dict(id=switch.pk, nombre=switch.nombre, ip=switch.hostname, plantel=switch.plantel_id,
                         plantel_nombre=switch.plantel.nombre,
                         hostid=host and host['hostid'], host=host and host['name'],
                         disponible=host and host_available(host),
                         ultimos=host and summarize_items(values.get(host['hostid'], []), interfaces=interfaces)))
    active = []
    for row in problems():
        owner = next((switch_of_host[h] for h in row['hostids'] if h in switch_of_host), None)
        if owner is not None:
            active.append(problem_data(row, now, by_pk[owner]))
    counts = {name: 0 for name in SEVERITIES.values()}
    for problem in active:
        counts[problem['severidad_nombre']] += 1
    return dict(problemas=active, switches=rows,
                resumen=dict(problemas=len(active), sin_reconocer=sum(not p['reconocido'] for p in active),
                             por_severidad=counts, relacionados=len(matched), sin_relacionar=len(switches) - len(matched)))


def problems_by_switch(switches):
    """{switch.pk: {problemas, sin_reconocer, severidad}} para el resumen y el puntaje ponderado."""
    _, switch_of_host = _owners(list(switches))
    result = {}
    for row in problems():
        if str(row.get('suppressed')) == '1':
            continue
        owner = next((switch_of_host[h] for h in row['hostids'] if h in switch_of_host), None)
        if owner is None:
            continue
        entry = result.setdefault(owner, dict(problemas=0, sin_reconocer=0, severidad=0))
        entry['problemas'] += 1
        entry['sin_reconocer'] += str(row.get('acknowledged')) != '1'
        entry['severidad'] = max(entry['severidad'], int(row['severity']))
    return result


def acknowledge(eventid, message='', ack=True):
    """Reconoce un problema y/o le agrega un comentario (event.acknowledge)."""
    action = (2 if ack else 0) | (4 if message else 0)
    if not action:
        raise ZabbixError('Escribe un comentario o marca el problema como reconocido.')
    params = {'eventids': [str(eventid)], 'action': action}
    if message:
        params['message'] = message[:2048]
    result = call('event.acknowledge', params)
    cache.delete('sonar-zabbix:problems')
    return result


# --- Historial (respaldo cuando InfluxDB no responde) ---------------------------------

def _history(items, time_from, time_till):
    """history.get agrupado por tipo de valor (0 flotante, 3 entero)."""
    rows = []
    for value_type in sorted({int(item['value_type']) for item in items}):
        ids = [item['itemid'] for item in items if int(item['value_type']) == value_type]
        rows += call('history.get', {'output': ['itemid', 'clock', 'value'], 'history': value_type, 'itemids': ids,
                                     'time_from': int(time_from), 'time_till': int(time_till),
                                     'sortfield': 'clock', 'sortorder': 'ASC', 'limit': 100000},
                     timeout=TIMEOUT_SECONDS * 3) or []
    return rows


def _trends(items, time_from, time_till):
    return [dict(itemid=row['itemid'], clock=row['clock'], value=row['value_avg'])
            for row in call('trend.get', {'output': ['itemid', 'clock', 'value_avg'],
                                          'itemids': [item['itemid'] for item in items],
                                          'time_from': int(time_from), 'time_till': int(time_till)},
                            timeout=TIMEOUT_SECONDS * 3) or []]


def _series(items, hours, every_seconds, now=None):
    """{itemid: {bucket: promedio}} desde history (≤ 24 h) o trends (más tiempo)."""
    now = int(now or time.time())
    since = now - int(hours * 3600)
    rows = _history(items, since, now) if hours <= 24 else _trends(items, since, now)
    sums = {}
    for row in rows:
        value = _number(row.get('value'))
        if value is None:
            continue
        bucket = int(row['clock']) // every_seconds * every_seconds
        total, count = sums.setdefault(row['itemid'], {}).get(bucket, (0.0, 0))
        sums[row['itemid']][bucket] = (total + value, count + 1)
    return {itemid: {bucket: total / count for bucket, (total, count) in buckets.items()}
            for itemid, buckets in sums.items()}


def _host_items(switch, keys):
    host = match_switches(hosts(), [switch]).get(switch.pk)
    if host is None:
        raise ZabbixError(f'{switch.nombre} no está dado de alta en Zabbix.')
    items = call('item.get', {'output': ['itemid', 'hostid', 'key_', 'name', 'value_type'], 'hostids': [host['hostid']],
                              'search': {'key_': list(keys)}, 'searchByAny': True, 'startSearch': True}) or []
    return [item for item in items if item.get('hostid') == host['hostid'] and item['key_'].startswith(tuple(keys))]


def _traffic_only(items):
    """Ítems de tráfico de interfaces físicas (sin errores/descartes); CPU y memoria pasan tal cual."""
    return [item for item in items if not item['key_'].startswith(('net.if.in.', 'net.if.out.'))
            and (not item['key_'].startswith('net.if.') or is_physical(interface_name(item.get('name'))))]


def switch_history(switch, hours=24, every_seconds=900, now=None):
    """Mismo formato que history.switch_histories: [{time, cpu, memoria, uptime, entrada_bps, salida_bps}]."""
    items = _traffic_only(_host_items(switch, ('system.cpu.util', 'vm.memory.util', 'net.if.in[', 'net.if.out[')))
    if not items:
        return []
    kinds = {}
    for item in items:
        key = item['key_']
        kinds[item['itemid']] = ('cpu' if key.startswith('system.cpu') else 'memoria' if key.startswith('vm.memory')
                                 else 'entrada_bps' if key.startswith('net.if.in[') else 'salida_bps')
    points = {}
    for itemid, buckets in _series(items, hours, every_seconds, now).items():
        kind = kinds[itemid]
        for bucket, value in buckets.items():
            slot = points.setdefault(bucket, dict(cpu=None, memoria=None, uptime=None, entrada_bps=None, salida_bps=None))
            if kind in ('cpu', 'memoria'):
                slot[kind] = round(value if slot[kind] is None else max(slot[kind], value), 1)
            else:
                slot[kind] = (slot[kind] or 0) + value
    return [dict(time=_when(bucket), **values) for bucket, values in sorted(points.items())]


def port_history(switch, port_name, hours=24, every_seconds=180, now=None):
    """[{time, entrada_bps, salida_bps}] del puerto (Zabbix ya entrega bits por segundo)."""
    wanted = short_port(port_name)
    items = [item for item in _traffic_only(_host_items(switch, ('net.if.in[', 'net.if.out[')))
             if short_port(interface_name(item.get('name'))) == wanted]
    if not items:
        raise ZabbixError(f'Zabbix no tiene tráfico de {port_name}.')
    kinds = {item['itemid']: 'entrada_bps' if item['key_'].startswith('net.if.in[') else 'salida_bps' for item in items}
    points = {}
    for itemid, buckets in _series(items, hours, every_seconds, now).items():
        for bucket, value in buckets.items():
            points.setdefault(bucket, dict(entrada_bps=None, salida_bps=None))[kinds[itemid]] = value
    return [dict(time=_when(bucket), **values) for bucket, values in sorted(points.items())]

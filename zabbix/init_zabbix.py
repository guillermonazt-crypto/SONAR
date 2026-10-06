"""Configura el Zabbix de SONAR (idempotente; se puede correr las veces que haga falta).

    python zabbix/init_zabbix.py                    contraseña de Admin e interfaz del agente
    python zabbix/init_zabbix.py --switches         además da de alta los switches de SONAR
    python zabbix/init_zabbix.py --token            además crea el token "SONAR" para Django
    python zabbix/init_zabbix.py --timescaledb      activa TimescaleDB (hypertables y compresión)
    python zabbix/init_zabbix.py --avanzado         plantilla SONAR, correlación, Geomap, SLA e histórico
    python zabbix/init_zabbix.py --proxy [NOMBRE]   registra un proxy activo para una zona
    python zabbix/init_zabbix.py --backfill         copia el histórico de InfluxDB/SONAR a Zabbix

Lee zabbix/.env (ZBX_URL, ZBX_ADMIN_PASSWORD, ZBX_SNMP_COMMUNITY) y el .env de SONAR
(INVENTORY_SOURCE, SNMP_*). Sólo usa la biblioteca estándar y PyYAML; con
INVENTORY_SOURCE=django lee los switches de la base de SONAR mediante su ORM.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import avanzado  # noqa: E402
import backfill  # noqa: E402
DEFAULT_PASSWORD = 'zabbix'
TEMPLATES = ('Cisco IOS by SNMP', 'Network Generic Device by SNMP')
COMMUNITY_MACRO = '{$SNMP_COMMUNITY}'
V3_MACROS = {'user': '{$SNMPV3_USER}', 'auth': '{$SNMPV3_AUTHPASS}', 'priv': '{$SNMPV3_PRIVPASS}'}
# Códigos de Zabbix 7.0 para SNMPv3
AUTH_PROTOCOLS = {'md5': 0, 'sha': 1, 'sha1': 1, 'sha224': 2, 'sha256': 3, 'sha384': 4, 'sha512': 5}
PRIV_PROTOCOLS = {'des': 0, 'aes': 1, 'aes128': 1, 'aes192': 2, 'aes256': 3}
TOKEN_NAME = 'SONAR'


class ZabbixError(RuntimeError):
    pass


def read_env(path):
    """KEY=VALUE de un archivo .env (sin sobrescribir el entorno ya definido)."""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Api:
    def __init__(self, url, timeout=15):
        base = url.rstrip('/')
        self.endpoint = base if base.endswith('api_jsonrpc.php') else f'{base}/api_jsonrpc.php'
        self.timeout = timeout
        self.token = None
        self._id = 0

    def call(self, method, params=None, auth=True):
        self._id += 1
        payload = {'jsonrpc': '2.0', 'method': method, 'params': params if params is not None else {}, 'id': self._id}
        headers = {'Content-Type': 'application/json-rpc'}
        if auth and self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        request = Request(self.endpoint, data=json.dumps(payload).encode(), headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise ZabbixError(f'{method}: Zabbix no responde ({error})') from error
        if body.get('error'):
            error = body['error']
            raise ZabbixError(f"{method}: {error.get('data') or error.get('message')}")
        return body.get('result')

    def login(self, username, password):
        try:
            self.token = self.call('user.login', {'username': username, 'password': password}, auth=False)
            return True
        except ZabbixError:
            self.token = None
            return False


def sign_in(api, new_password):
    """Entra como Admin; si aún tiene la contraseña de fábrica la reemplaza por ZBX_ADMIN_PASSWORD."""
    if api.login('Admin', DEFAULT_PASSWORD):
        if new_password and len(new_password) >= 8 and new_password != DEFAULT_PASSWORD:
            userid = admin_id(api)
            api.call('user.update', {'userid': userid, 'passwd': new_password, 'current_passwd': DEFAULT_PASSWORD})
            print('· Contraseña de Admin cambiada (ZBX_ADMIN_PASSWORD).')
            if not api.login('Admin', new_password):
                raise ZabbixError('No se pudo entrar con la contraseña nueva de Admin.')
        elif new_password:
            print('! ZBX_ADMIN_PASSWORD debe tener al menos 8 caracteres; Admin sigue con la de fábrica.')
        else:
            print('! Admin sigue con la contraseña de fábrica: define ZBX_ADMIN_PASSWORD.')
        return
    if new_password and api.login('Admin', new_password):
        return
    raise ZabbixError('No se pudo entrar como Admin (ni con "zabbix" ni con ZBX_ADMIN_PASSWORD).')


def admin_id(api):
    users = api.call('user.get', {'output': ['userid'], 'filter': {'username': 'Admin'}})
    if not users:
        raise ZabbixError('No existe el usuario Admin.')
    return users[0]['userid']


def fix_agent_interface(api):
    """El host "Zabbix server" viene con 127.0.0.1; en Docker el agente es otro contenedor."""
    hosts = api.call('host.get', {'output': ['hostid'], 'filter': {'host': 'Zabbix server'},
                                  'selectInterfaces': ['interfaceid', 'type', 'useip', 'dns']})
    for host in hosts or []:
        for interface in host.get('interfaces', []):
            if str(interface['type']) == '1' and (str(interface['useip']) != '0' or interface['dns'] != 'zabbix-agent'):
                api.call('hostinterface.update', {'interfaceid': interface['interfaceid'], 'useip': 0,
                                                  'dns': 'zabbix-agent', 'port': '10050'})
                print('· Interfaz del agente de "Zabbix server" -> zabbix-agent (DNS).')


def set_global_macro(api, macro, value, secret=True):
    existing = api.call('usermacro.get', {'globalmacro': True, 'output': ['globalmacroid', 'macro'],
                                          'filter': {'macro': macro}})
    params = {'value': value, 'type': 1 if secret else 0}
    if existing:
        api.call('usermacro.updateglobal', dict(params, globalmacroid=existing[0]['globalmacroid']))
    else:
        api.call('usermacro.createglobal', dict(params, macro=macro))


def group_id(api, name, cache):
    if name not in cache:
        groups = api.call('hostgroup.get', {'output': ['groupid'], 'filter': {'name': [name]}})
        cache[name] = groups[0]['groupid'] if groups else api.call('hostgroup.create', {'name': name})['groupids'][0]
    return cache[name]


def template_id(api):
    for name in TEMPLATES:
        found = api.call('template.get', {'output': ['templateid'], 'filter': {'host': [name]}})
        if found:
            return found[0]['templateid'], name
    raise ZabbixError('No se encontró la plantilla "Cisco IOS by SNMP" ni "Network Generic Device by SNMP".')


def technical_name(name):
    """El nombre técnico de Zabbix sólo admite letras, números, espacio, punto, guion y guion bajo."""
    return re.sub(r'[^0-9A-Za-z_. \-]', '_', name).strip() or 'switch'


def load_switches(sonar_root, sonar_env):
    """[{nombre, ip, rol, plantel}] de la base de SONAR (INVENTORY_SOURCE=django) o de devices.yaml."""
    if sonar_env.get('INVENTORY_SOURCE', 'django') == 'django':
        try:
            return django_switches(sonar_root)
        except Exception as error:  # sin Django instalado o sin base: intenta el YAML
            print(f'! No se pudo leer la base de SONAR ({error}); se intenta inventory/devices.yaml.')
    path = sonar_root / 'inventory' / 'devices.yaml'
    if not path.exists():
        return []
    import yaml
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    return [dict(nombre=d.get('name') or d['hostname'], ip=d['hostname'], rol=d.get('role', 'access'),
                 plantel=d.get('site') or 'sin_plantel') for d in data.get('devices', [])]


def django_switches(sonar_root):
    backend = str(sonar_root / 'backend')
    if backend not in sys.path:
        sys.path.insert(0, backend)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from switches.models import Switch
    return [dict(nombre=s.nombre, ip=s.hostname, rol=s.rol, plantel=s.plantel.nombre)
            for s in Switch.objects.filter(activo=True).select_related('plantel')]


def snmp_interface(ip, sonar_env):
    interface = {'type': 2, 'main': 1, 'useip': 1, 'ip': ip, 'dns': '', 'port': '161'}
    if sonar_env.get('SNMP_VERSION', '2c') == '3':
        interface['details'] = {
            'version': 3, 'bulk': 1, 'securityname': V3_MACROS['user'], 'securitylevel': 2, 'contextname': '',
            'authprotocol': AUTH_PROTOCOLS.get(sonar_env.get('SNMP_V3_AUTH_PROTOCOL', 'sha').lower(), 1),
            'authpassphrase': V3_MACROS['auth'],
            'privprotocol': PRIV_PROTOCOLS.get(sonar_env.get('SNMP_V3_PRIV_PROTOCOL', 'aes').lower(), 1),
            'privpassphrase': V3_MACROS['priv']}
    else:
        interface['details'] = {'version': 2, 'bulk': 1, 'community': COMMUNITY_MACRO}
    return interface


def add_switches(api, switches, sonar_env, zabbix_env):
    if not switches:
        print('· No hay switches que dar de alta.')
        return 0
    if sonar_env.get('SNMP_VERSION', '2c') == '3':
        for key, env in (('user', 'SNMP_V3_USER'), ('auth', 'SNMP_V3_AUTH_KEY'), ('priv', 'SNMP_V3_PRIV_KEY')):
            if sonar_env.get(env):
                set_global_macro(api, V3_MACROS[key], sonar_env[env], secret=key != 'user')
    else:
        community = zabbix_env.get('ZBX_SNMP_COMMUNITY') or sonar_env.get('SNMP_COMMUNITY')
        if community:
            set_global_macro(api, COMMUNITY_MACRO, community)
        else:
            print('! Sin ZBX_SNMP_COMMUNITY ni SNMP_COMMUNITY: define la macro {$SNMP_COMMUNITY} en Zabbix.')
    template, template_name = template_id(api)
    existing = api.call('host.get', {'output': ['host'], 'selectInterfaces': ['ip']})
    known_names = {host['host'] for host in existing}
    known_ips = {interface['ip'] for host in existing for interface in host.get('interfaces', [])}
    groups, created = {}, 0
    for switch in switches:
        host = technical_name(switch['nombre'])
        if host in known_names or switch['ip'] in known_ips:
            continue
        api.call('host.create', {
            'host': host, 'name': switch['nombre'],
            'interfaces': [snmp_interface(switch['ip'], sonar_env)],
            'groups': [{'groupid': group_id(api, f"SONAR/{switch['plantel']}", groups)}],
            'templates': [{'templateid': template}],
            'tags': [{'tag': 'plantel', 'value': switch['plantel']}, {'tag': 'rol', 'value': switch['rol']},
                     {'tag': 'sonar', 'value': 'switch'}]})
        known_names.add(host)
        known_ips.add(switch['ip'])
        created += 1
    print(f'· Switches: {created} nuevos con "{template_name}", {len(switches) - created} ya existían.')
    return created


def sonar_extras(sonar_root):
    """({ip: [ifIndex de troncales]}, {plantel: ubicacion}) de la base de SONAR; vacíos si no hay Django."""
    try:
        django_switches(sonar_root)  # prepara Django
        from planteles.models import Plantel
        from switches.models import Puerto
        trunks = {}
        for ip, index in Puerto.objects.filter(es_trunk=True, switch__activo=True).values_list('switch__hostname',
                                                                                             'indice'):
            trunks.setdefault(ip, []).append(index)
        return trunks, dict(Plantel.objects.exclude(ubicacion='').values_list('nombre', 'ubicacion'))
    except Exception as error:
        print(f'! Sin la base de SONAR ({error}): uplinks por nombre/descripción y coordenadas por nombre.')
        return {}, {}


def compose(*args, stdin=None):
    """docker compose del stack de Zabbix (carpeta zabbix/)."""
    return subprocess.run(['docker', 'compose', *args], cwd=HERE, input=stdin, capture_output=True, check=False)


def psql_runner(zabbix_env):
    """psql(*args, stdin=None) -> stdout dentro del contenedor postgres; ZabbixError si falla."""
    user, db = zabbix_env.get('ZBX_POSTGRES_USER', 'zabbix'), zabbix_env.get('ZBX_POSTGRES_DB', 'zabbix')

    def psql(*args, stdin=None):
        result = compose('exec', '-T', 'postgres', 'psql', '-v', 'ON_ERROR_STOP=1', '-q', '-U', user, '-d', db, *args,
                         stdin=stdin.encode() if isinstance(stdin, str) else stdin)
        if result.returncode:
            raise ZabbixError(f'psql: {result.stderr.decode(errors="replace").strip()}')
        return result.stdout.decode(errors='replace')
    return psql


def run_backfill(api, sonar_root, sonar_env, zabbix_env):
    django_switches(sonar_root)  # prepara Django (puertos y óptica de SONAR)
    hosts = avanzado.sonar_hosts(api)
    return backfill.run(api, hosts, sonar_env, psql_runner(zabbix_env),
                        restart=lambda: (print('· Reiniciando zabbix-server para recargar su caché de valores...'),
                                         compose('restart', 'zabbix-server')))


def enable_timescaledb(zabbix_env):
    """Extensión TimescaleDB e hypertables de Zabbix (timescaledb.sql es idempotente)."""
    user, db = zabbix_env.get('ZBX_POSTGRES_USER', 'zabbix'), zabbix_env.get('ZBX_POSTGRES_DB', 'zabbix')
    psql = ['exec', '-T', 'postgres', 'psql', '-v', 'ON_ERROR_STOP=1', '-q', '-U', user, '-d', db]
    result = compose(*psql, '-c', 'CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;')
    if result.returncode:
        raise ZabbixError('TimescaleDB no disponible en postgres (¿imagen timescale/timescaledb y '
                          f'shared_preload_libraries?): {result.stderr.decode(errors="replace").strip()}')
    check = compose(*psql, '-tAc', "SELECT count(*) FROM timescaledb_information.hypertables "
                                   "WHERE hypertable_name IN ('history','trends')")
    if check.stdout.decode().strip() == '2':
        print('· TimescaleDB ya activo (history y trends son hypertables).')
        return
    script = compose('exec', '-T', 'zabbix-server', 'cat', '/usr/share/doc/zabbix-server-postgresql/timescaledb.sql')
    if script.returncode or not script.stdout:
        raise ZabbixError('No se encontró timescaledb.sql en el contenedor zabbix-server.')
    print('· Convirtiendo history/trends a hypertables (se detiene zabbix-server un momento)...')
    compose('stop', 'zabbix-server')
    try:
        result = compose(*psql, stdin=script.stdout)
    finally:
        compose('start', 'zabbix-server')
    if result.returncode:
        raise ZabbixError(f'timescaledb.sql falló: {result.stderr.decode(errors="replace").strip()}')
    print('· TimescaleDB activo con compresión (Zabbix la aplica a lo mayor de 7 días).')


def create_token(api):
    userid = admin_id(api)
    old = api.call('token.get', {'output': ['tokenid'], 'userids': [userid], 'filter': {'name': TOKEN_NAME}})
    if old:
        api.call('token.delete', [token['tokenid'] for token in old])
    tokenid = api.call('token.create', {'name': TOKEN_NAME, 'userid': userid})['tokenids'][0]
    return api.call('token.generate', [tokenid])[0]['token']


def main(argv=None):
    parser = argparse.ArgumentParser(description='Configura Zabbix para SONAR.')
    parser.add_argument('--switches', action='store_true', help='da de alta los switches de SONAR')
    parser.add_argument('--token', action='store_true', help='(re)crea el token "SONAR" e imprime ZABBIX_TOKEN')
    parser.add_argument('--avanzado', action='store_true',
                        help='plantilla SONAR (traps, uplinks 30 s, tendencias), correlación, Geomap, SLA e histórico')
    parser.add_argument('--timescaledb', action='store_true',
                        help='activa TimescaleDB en la base (docker compose exec; detiene el server un momento)')
    parser.add_argument('--backfill', action='store_true',
                        help='copia a Zabbix el histórico de InfluxDB y la óptica de SONAR (sólo lo anterior a sus datos)')
    parser.add_argument('--proxy', metavar='NOMBRE', nargs='?', const='',
                        help='registra un proxy activo (por omisión ZBX_PROXY_HOSTNAME o "SONAR-proxy-zona1")')
    parser.add_argument('--sonar-root', default=str(HERE.parent), help='carpeta de SONAR (.env, inventario, base)')
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')
    sonar_root = Path(args.sonar_root).resolve()
    zabbix_env = {**read_env(HERE / '.env'), **{k: v for k, v in os.environ.items() if k.startswith('ZBX_')}}
    sonar_env = {**read_env(sonar_root / '.env'), **os.environ}
    url = zabbix_env.get('ZBX_URL') or 'http://localhost:8090'
    api = Api(url)
    try:
        version = api.call('apiinfo.version', auth=False)
        print(f'· Zabbix {version} en {url}')
        sign_in(api, zabbix_env.get('ZBX_ADMIN_PASSWORD', ''))
        fix_agent_interface(api)
        if args.switches:
            add_switches(api, load_switches(sonar_root, sonar_env), sonar_env, zabbix_env)
        if args.timescaledb:
            enable_timescaledb(zabbix_env)
        if args.avanzado:
            trunks, ubicaciones = sonar_extras(sonar_root)
            history_days = int(zabbix_env.get('ZBX_HISTORY_DAYS') or 90)
            avanzado.apply(api, sonar_root, trunks, ubicaciones, history_days=max(30, min(history_days, 90)))
        if args.backfill:
            run_backfill(api, sonar_root, sonar_env, zabbix_env)
        if args.proxy is not None:
            avanzado.apply_proxy(api, args.proxy or zabbix_env.get('ZBX_PROXY_HOSTNAME') or 'SONAR-proxy-zona1')
        if args.token:
            token = create_token(api)
            print('\nAgrega al .env de SONAR:')
            print(f'ZABBIX_URL={url}')
            print(f'ZABBIX_TOKEN={token}')
    except ZabbixError as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

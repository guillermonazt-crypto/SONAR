import json
import os
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen


def _endpoint():
    base = os.getenv('ZABBIX_URL', '').strip().rstrip('/')
    if not base:
        return None
    return base if base.endswith('api_jsonrpc.php') else f'{base}/api_jsonrpc.php'


def status():
    endpoint = _endpoint()
    if not endpoint:
        return {'configured': False, 'hosts': [], 'detail': 'Configura ZABBIX_URL para activar la integración.'}
    payload = {
        'jsonrpc': '2.0', 'method': 'host.get', 'params': {
            'output': ['hostid', 'host', 'name', 'status', 'available'],
            'selectInterfaces': ['ip', 'available'],
        }, 'id': 1,
    }
    token = os.getenv('ZABBIX_TOKEN', '').strip()
    if token:
        payload['auth'] = token
    else:
        return {'configured': False, 'hosts': [], 'detail': 'Configura ZABBIX_TOKEN para consultar Zabbix.'}
    request = Request(endpoint, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=5) as response:
            body = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        return {'configured': True, 'hosts': [], 'detail': f'Zabbix no disponible: {error}'}
    if body.get('error'):
        return {'configured': True, 'hosts': [], 'detail': body['error'].get('data', 'Error de Zabbix')}
    return {'configured': True, 'hosts': body.get('result', []), 'detail': None}

"""Zabbix como fuente en tiempo real: cliente, /api/vivo/, reconocer, historial de respaldo y resumen."""
import io
import json
import os
from unittest import mock
from urllib.error import URLError

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from planteles.models import Division, Plantel
from switches.models import Puerto, Switch
from switches.scoring import device_events
from usuarios.models import Bitacora
from api import zabbix

ENV = {'ZABBIX_URL': 'http://zabbix.test', 'ZABBIX_TOKEN': 'secreto'}
NOW = 1_760_000_000


class FakeZabbix:
    """Sustituye a urlopen: responde por método JSON-RPC y guarda cada llamada."""

    def __init__(self, **results):
        self.results = results
        self.calls = []

    def __call__(self, request, timeout=None):
        payload = json.loads(request.data)
        self.calls.append(dict(method=payload['method'], params=payload['params'],
                               auth=request.get_header('Authorization'), timeout=timeout, body=payload))
        result = self.results.get(payload['method'], [])
        if isinstance(result, Exception):
            raise result
        if callable(result):
            result = result(payload['params'])
        return io.BytesIO(json.dumps({'jsonrpc': '2.0', 'result': result, 'id': 1}).encode())

    def methods(self):
        return [call['method'] for call in self.calls]


def item(itemid, hostid, key, value, name='', value_type=0, clock=NOW):
    return dict(itemid=itemid, hostid=hostid, key_=key, name=name, lastvalue=str(value), lastclock=str(clock),
                units='', value_type=str(value_type))


HOSTS = [
    dict(hostid='101', host='SW-APAN-1', name='SW-APAN-1', status='0',
         interfaces=[dict(ip='192.0.2.1', dns='', type='2', available='1', error='')]),
    # Sin IP coincidente: se relaciona por nombre.
    dict(hostid='102', host='SW_TULA', name='SW TULA', status='0',
         interfaces=[dict(ip='198.51.100.9', dns='', type='2', available='2', error='Timeout')]),
    dict(hostid='999', host='Zabbix server', name='Zabbix server', status='0',
         interfaces=[dict(ip='', dns='zabbix-agent', type='1', available='1', error='')]),
]
PROBLEMS = [
    dict(eventid='5001', objectid='9001', name='Unavailable by ICMP ping', severity='4', acknowledged='0',
         clock=str(NOW - 600), suppressed='0', opdata=''),
    dict(eventid='5002', objectid='9002', name='High CPU utilization', severity='2', acknowledged='1',
         clock=str(NOW - 60), suppressed='0', opdata='92 %'),
    dict(eventid='5003', objectid='9003', name='Zabbix agent is not available', severity='3', acknowledged='0',
         clock=str(NOW - 30), suppressed='0', opdata=''),
]
TRIGGERS = [dict(triggerid='9001', hosts=[dict(hostid='102')]), dict(triggerid='9002', hosts=[dict(hostid='101')]),
            dict(triggerid='9003', hosts=[dict(hostid='999')])]
ITEMS = [
    item('1', '101', 'icmpping', 1), item('2', '101', 'icmppingloss', 0), item('3', '101', 'icmppingsec', 0.0042),
    item('4', '101', 'system.cpu.util[cpmCPUTotal5minRev.1]', 92), item('5', '101', 'vm.memory.util[vm.memory.util.1]', 41.26),
    item('6', '101', 'zabbix[host,snmp,available]', 1),
    item('7', '101', 'net.if.in[ifHCInOctets.10101]', 9_000_000, 'Interface Gi1/1/1(Uplink): Bits received', 3),
    item('8', '101', 'net.if.out[ifHCOutOctets.10101]', 1_000_000, 'Interface Gi1/1/1(Uplink): Bits sent', 3),
    item('9', '101', 'net.if.in.errors[ifInErrors.10101]', 3, 'Interface Gi1/1/1(Uplink): Inbound packets with errors', 3),
    item('10', '101', 'net.if.in[ifHCInOctets.30]', 50_000_000, 'Interface Vl30(): Bits received', 3),
    item('11', '101', 'net.if.in[ifHCInOctets.10001]', 100, 'Interface Gi1/0/1(): Bits received', 3),
    item('20', '102', 'icmpping', 0), item('21', '102', 'icmppingloss', 100),
]


def fake(**overrides):
    results = {'host.get': HOSTS, 'problem.get': PROBLEMS, 'trigger.get': TRIGGERS, 'item.get': ITEMS}
    results.update(overrides)
    return FakeZabbix(**results)


@mock.patch.dict(os.environ, ENV)
@mock.patch('api.zabbix.time.time', return_value=NOW)
class ZabbixLiveTests(TestCase):
    def setUp(self):
        cache.clear()
        users = get_user_model().objects
        self.reader = users.create_user(username='lector', password='test-password', rol='lector')
        self.editor = users.create_user(username='editor', password='test-password', rol='editor')
        division = Division.objects.create(nombre='Escuelas')
        self.apan = Plantel.objects.create(nombre='Apan', division=division)
        self.tula = Plantel.objects.create(nombre='Tula', division=division)
        self.sw_apan = Switch.objects.create(nombre='SW-APAN-1', hostname='192.0.2.1', plantel=self.apan)
        self.sw_tula = Switch.objects.create(nombre='SW TULA', hostname='192.0.2.2', plantel=self.tula)
        self.sw_none = Switch.objects.create(nombre='SW-SIN-ZABBIX', hostname='192.0.2.3', plantel=self.tula)
        # Sondeados con éxito: en SONAR están bien y sólo Zabbix reporta problemas.
        now = timezone.now()
        Switch.objects.update(ultima_consulta=now, ultima_lectura_exitosa=now, lectura_correcta=True)
        self.port = Puerto.objects.create(switch=self.sw_apan, nombre='GigabitEthernet1/1/1', indice=10101)
        self.client.force_login(self.reader)

    def test_client_uses_bearer_header_and_short_timeout(self, _time):
        server = fake()
        with mock.patch('api.zabbix.urlopen', server):
            zabbix.hosts()
        call = server.calls[0]
        self.assertEqual(call['auth'], 'Bearer secreto')
        self.assertNotIn('auth', call['body'])
        self.assertLessEqual(call['timeout'], 5)

    def test_results_are_cached(self, _time):
        server = fake()
        with mock.patch('api.zabbix.urlopen', server):
            self.client.get('/api/vivo/')
            first = len(server.calls)
            self.client.get('/api/vivo/')
        self.assertEqual(len(server.calls), first)

    def test_live_matches_by_ip_then_name_and_reports_problems(self, _time):
        with mock.patch('api.zabbix.urlopen', fake()):
            data = self.client.get('/api/vivo/').json()
        self.assertTrue(data['configurado'])
        self.assertEqual(data['fuente'], 'zabbix')
        self.assertFalse(data['puede_reconocer'])
        rows = {row['nombre']: row for row in data['switches']}
        self.assertEqual(rows['SW-APAN-1']['hostid'], '101')
        self.assertEqual(rows['SW TULA']['hostid'], '102')
        self.assertIsNone(rows['SW-SIN-ZABBIX']['hostid'])
        self.assertTrue(rows['SW-APAN-1']['disponible'])
        self.assertFalse(rows['SW TULA']['disponible'])
        latest = rows['SW-APAN-1']['ultimos']
        self.assertEqual((latest['ping'], latest['latencia_ms'], latest['cpu'], latest['memoria'], latest['snmp']),
                         (True, 4.2, 92.0, 41.3, True))
        self.assertEqual(rows['SW TULA']['ultimos']['perdida_pct'], 100.0)
        # El problema del "Zabbix server" no es de un switch de SONAR.
        problems = data['problemas']
        self.assertEqual([p['eventid'] for p in problems], ['5001', '5002'])
        down = problems[0]
        self.assertEqual((down['severidad'], down['severidad_nombre'], down['reconocido']), (4, 'Alta', False))
        self.assertEqual(down['antiguedad_s'], 600)
        self.assertEqual(down['switch']['nombre'], 'SW TULA')
        self.assertEqual(down['plantel'], dict(id=self.tula.pk, nombre='Tula'))
        self.assertEqual(data['resumen']['sin_reconocer'], 1)
        self.assertEqual(data['resumen']['sin_relacionar'], 1)

    def test_live_filters_by_site(self, _time):
        with mock.patch('api.zabbix.urlopen', fake()):
            data = self.client.get('/api/vivo/', {'plantel': self.apan.pk}).json()
        self.assertEqual([row['nombre'] for row in data['switches']], ['SW-APAN-1'])
        self.assertEqual([p['eventid'] for p in data['problemas']], ['5002'])

    def test_switch_detail_includes_physical_uplinks(self, _time):
        with mock.patch('api.zabbix.urlopen', fake()):
            data = self.client.get(f'/api/vivo/switches/{self.sw_apan.pk}/').json()
        uplinks = data['switch']['ultimos']['interfaces']
        self.assertEqual([port['nombre'] for port in uplinks], ['Gi1/1/1', 'Gi1/0/1'])
        self.assertEqual(uplinks[0], dict(nombre='Gi1/1/1', entrada_bps=9e6, salida_bps=1e6,
                                          errores_entrada=3.0, errores_salida=None))
        self.assertEqual(self.client.get('/api/vivo/switches/9999/').status_code, 404)

    def test_errors_do_not_break_the_api(self, _time):
        with mock.patch('api.zabbix.urlopen', fake(**{'host.get': URLError('sin ruta')})):
            response = self.client.get('/api/vivo/')
            detail = self.client.get(f'/api/vivo/switches/{self.sw_apan.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Zabbix no disponible', response.json()['detalle'])
        self.assertEqual(response.json()['problemas'], [])
        self.assertEqual(detail.status_code, 200)
        self.assertIsNone(detail.json()['switch'])

    def test_api_error_message_is_reported(self, _time):
        def failing(request, timeout=None):
            return io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'error': {
                'code': -32602, 'message': 'Invalid params.', 'data': 'Not authorised.'}}).encode())
        with mock.patch('api.zabbix.urlopen', failing):
            data = self.client.get('/api/vivo/').json()
        self.assertEqual(data['detalle'], 'Zabbix: Not authorised.')

    def test_session_required(self, _time):
        self.client.logout()
        for path in ('/api/vivo/', f'/api/vivo/switches/{self.sw_apan.pk}/'):
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_acknowledge_requires_editor(self, _time):
        server = fake()
        with mock.patch('api.zabbix.urlopen', server):
            response = self.client.post('/api/vivo/problemas/5001/reconocer/', {'mensaje': 'x'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('event.acknowledge', server.methods())

    def test_acknowledge_with_comment(self, _time):
        self.client.force_login(self.editor)
        server = fake(**{'event.acknowledge': {'eventids': ['5001']}})
        with mock.patch('api.zabbix.urlopen', server):
            response = self.client.post('/api/vivo/problemas/5001/reconocer/',
                                        {'mensaje': 'Voy en camino', 'reconocer': True}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['reconocido'])
        ack = next(call for call in server.calls if call['method'] == 'event.acknowledge')
        self.assertEqual(ack['params'], {'eventids': ['5001'], 'action': 6, 'message': 'Voy en camino'})
        log = Bitacora.objects.get(objeto='zabbix')
        self.assertIn('SW TULA', log.descripcion)
        self.assertEqual(log.cambios, {'mensaje': 'Voy en camino'})

    def test_comment_only_on_acknowledged_problem(self, _time):
        self.client.force_login(self.editor)
        server = fake(**{'event.acknowledge': {'eventids': ['5002']}})
        with mock.patch('api.zabbix.urlopen', server):
            self.client.post('/api/vivo/problemas/5002/reconocer/', {'mensaje': 'Revisado'}, content_type='application/json')
        ack = next(call for call in server.calls if call['method'] == 'event.acknowledge')
        self.assertEqual(ack['params']['action'], 4)

    def test_acknowledge_rejects_foreign_events(self, _time):
        self.client.force_login(self.editor)
        server = fake()
        with mock.patch('api.zabbix.urlopen', server):
            missing = self.client.post('/api/vivo/problemas/5003/reconocer/', {}, content_type='application/json')
        self.assertEqual(missing.status_code, 404)
        self.assertNotIn('event.acknowledge', server.methods())

    def test_summary_adds_zabbix_problems_to_weighted_score(self, _time):
        with mock.patch('api.zabbix.urlopen', fake()):
            data = self.client.get('/api/resumen/').json()
        self.assertTrue(data['zabbix']['configurado'])
        sites = {site['nombre']: site for site in data['planteles']}
        self.assertEqual(sites['Tula']['zabbix'], dict(problemas=1, sin_reconocer=1, severidad=4))
        self.assertEqual(sites['Apan']['zabbix'], dict(problemas=1, sin_reconocer=0, severidad=2))
        # Alta (4) cuenta como caído en Tula; Advertencia (2) como lento en Apan.
        self.assertGreaterEqual(sites['Tula']['desglose']['caido'], 1)
        self.assertGreaterEqual(sites['Apan']['desglose']['lento'], 1)


@mock.patch.dict(os.environ, ENV)
class ZabbixHistoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username='lector', password='test-password', rol='lector')
        division = Division.objects.create(nombre='Escuelas')
        apan = Plantel.objects.create(nombre='Apan', division=division)
        self.switch = Switch.objects.create(nombre='SW-APAN-1', hostname='192.0.2.1', plantel=apan)
        self.port = Puerto.objects.create(switch=self.switch, nombre='GigabitEthernet1/1/1', indice=10101)
        self.client.force_login(self.user)

    def history_server(self):
        def history(params):
            rows = {'0': [dict(itemid='4', clock=str(NOW - 1000), value='10'), dict(itemid='4', clock=str(NOW - 900), value='30')],
                    '3': [dict(itemid='7', clock=str(NOW - 1000), value='8000'), dict(itemid='8', clock=str(NOW - 1000), value='2000'),
                          dict(itemid='10', clock=str(NOW - 1000), value='999999')]}
            return [row for row in rows[str(params['history'])] if row['itemid'] in params['itemids']]
        return fake(**{'history.get': history})

    @mock.patch('api.history.port_history', side_effect=RuntimeError('influx caído'))
    def test_port_history_falls_back_to_zabbix(self, _influx):
        server = self.history_server()
        with mock.patch('api.zabbix.urlopen', server), mock.patch('api.zabbix.time.time', return_value=NOW):
            data = self.client.get(f'/api/puertos/{self.port.pk}/historial/').json()
        self.assertEqual(data['fuente'], 'zabbix')
        self.assertEqual(data['unidad'], 'bps')
        self.assertEqual(len(data['points']), 1)
        self.assertEqual((data['points'][0]['entrada_bps'], data['points'][0]['salida_bps']), (8000.0, 2000.0))
        self.assertIn('influx caído', data['detail'])

    @mock.patch('api.history.switch_histories', side_effect=RuntimeError('influx caído'))
    def test_switch_history_skips_logical_interfaces(self, _influx):
        with mock.patch('api.zabbix.urlopen', self.history_server()), mock.patch('api.zabbix.time.time', return_value=NOW):
            data = self.client.get(f'/api/switches/{self.switch.pk}/historial/').json()
        self.assertEqual(data['fuente'], 'zabbix')
        point = data['points'][0]
        self.assertEqual((point['cpu'], point['entrada_bps'], point['salida_bps']), (20.0, 8000.0, 2000.0))

    @mock.patch('api.history.switch_histories', return_value={'SW-APAN-1': [dict(time='t', cpu=1)]})
    def test_influx_first_in_auto_mode(self, _influx):
        server = self.history_server()
        with mock.patch('api.zabbix.urlopen', server):
            data = self.client.get(f'/api/switches/{self.switch.pk}/historial/').json()
        self.assertEqual(data, {'points': [dict(time='t', cpu=1)], 'fuente': 'influx'})
        self.assertEqual(server.calls, [])

    @mock.patch('api.history.switch_histories', return_value={'SW-APAN-1': [dict(time='t', cpu=1)]})
    def test_history_source_zabbix_skips_influx(self, influx):
        with mock.patch.dict(os.environ, {'HISTORY_SOURCE': 'zabbix'}), \
                mock.patch('api.zabbix.urlopen', self.history_server()), mock.patch('api.zabbix.time.time', return_value=NOW):
            data = self.client.get(f'/api/switches/{self.switch.pk}/historial/').json()
        self.assertEqual(data['fuente'], 'zabbix')
        influx.assert_not_called()

    @mock.patch('api.history.switch_histories', side_effect=RuntimeError('influx caído'))
    def test_history_source_influx_never_asks_zabbix(self, _influx):
        server = self.history_server()
        with mock.patch.dict(os.environ, {'HISTORY_SOURCE': 'influx'}), mock.patch('api.zabbix.urlopen', server):
            data = self.client.get(f'/api/switches/{self.switch.pk}/historial/').json()
        self.assertIsNone(data['fuente'])
        self.assertIn('influx caído', data['detail'])
        self.assertEqual(server.calls, [])

    @mock.patch('api.history.port_history', side_effect=RuntimeError('influx caído'))
    def test_both_sources_down(self, _influx):
        with mock.patch('api.zabbix.urlopen', fake(**{'host.get': URLError('sin ruta')})):
            data = self.client.get(f'/api/puertos/{self.port.pk}/historial/').json()
        self.assertEqual((data['points'], data['fuente']), ([], None))
        self.assertIn('InfluxDB', data['detail'])
        self.assertIn('Zabbix no disponible', data['detail'])


class ZabbixDisabledTests(TestCase):
    """Sin ZABBIX_URL/ZABBIX_TOKEN no se hace ninguna llamada y todo responde como antes."""

    def setUp(self):
        cache.clear()
        self.client.force_login(get_user_model().objects.create_user(username='u', password='test-password', rol='editor'))

    @mock.patch.dict(os.environ, {'ZABBIX_URL': '', 'ZABBIX_TOKEN': ''})
    def test_nothing_is_called(self):
        with mock.patch('api.zabbix.urlopen') as opener:
            live = self.client.get('/api/vivo/').json()
            summary = self.client.get('/api/resumen/').json()
            ack = self.client.post('/api/vivo/problemas/1/reconocer/', {}, content_type='application/json')
        opener.assert_not_called()
        self.assertFalse(live['configurado'])
        self.assertFalse(summary['zabbix']['configurado'])
        self.assertEqual(ack.status_code, 503)


class ZabbixHelpersTests(TestCase):
    def test_short_port_names(self):
        self.assertEqual(zabbix.short_port('GigabitEthernet1/0/1'), zabbix.short_port('Gi1/0/1'))
        self.assertEqual(zabbix.short_port('TenGigabitEthernet1/1/1'), 'te1/1/1')
        self.assertEqual(zabbix.short_port('Twe1/0/1'), zabbix.short_port('TwentyFiveGigE1/0/1'))
        self.assertEqual(zabbix.interface_name('Interface Gi1/0/1(Oficina 2): Bits sent'), 'Gi1/0/1')
        self.assertFalse(zabbix.is_physical('Vl30'))
        self.assertFalse(zabbix.is_physical('Port-channel1'))

    def test_zabbix_signals_do_not_double_count(self):
        down = dict(motivos=[dict(level='critical', tipo='snmp')], zabbix=dict(severidad=4))
        self.assertEqual(device_events(down), dict(puerto=0, lento=0, caido=1, critico=0))
        disaster = dict(motivos=[], zabbix=dict(severidad=5))
        self.assertEqual(device_events(disaster)['critico'], 1)
        warning = dict(motivos=[dict(level='critical', tipo='hardware')], zabbix=dict(severidad=2))
        self.assertEqual(device_events(warning), dict(puerto=0, lento=0, caido=0, critico=1))
        self.assertEqual(device_events(dict(motivos=[], zabbix=dict(severidad=1))),
                         dict(puerto=0, lento=0, caido=0, critico=0))

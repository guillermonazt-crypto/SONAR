from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from planteles.models import Division, Plantel
from switches.models import Switch, Puerto
from switches.services import record_poll
from api.views import flux_string

class ApiTests(TestCase):
    def setUp(self):
        self.reader = get_user_model().objects.create_user(username='reader', password='test-password', rol='lector')
        self.editor = get_user_model().objects.create_user(username='editor', password='test-password', rol='editor')
        self.plantel = Plantel.objects.create(nombre='Lab', division=Division.objects.create(nombre='Test'))
        self.payload = dict(nombre='SW-LAB', hostname='192.0.2.1', rol='access', plantel=self.plantel.pk)

    def test_anonymous_and_reader_permissions(self):
        self.assertEqual(self.client.get('/api/switches/').status_code, 403)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get('/api/switches/').status_code, 200)
        for path, payload in [('switches',self.payload), ('divisiones',dict(nombre='Other')), ('planteles',dict(nombre='X',division=self.plantel.division_id))]:
            self.assertEqual(self.client.post(f'/api/{path}/', payload).status_code, 403)

    def test_editor_create_validate_update_and_read_ports(self):
        self.client.force_login(self.editor)
        response = self.client.post('/api/switches/', self.payload)
        self.assertEqual(response.status_code, 201, response.content)
        pk = response.json()['id']
        self.assertEqual(self.client.post('/api/switches/', self.payload).status_code, 400)
        self.assertEqual(self.client.post('/api/switches/', dict(self.payload,hostname='invalid')).status_code, 400)
        self.assertEqual(self.client.patch(f'/api/switches/{pk}/', data='{"activo":false,"cpu_5m":99}', content_type='application/json').status_code, 200)
        switch = Switch.objects.get(pk=pk)
        self.assertFalse(switch.activo)
        self.assertIsNone(switch.cpu_5m)
        self.assertEqual(self.client.delete(f'/api/switches/{pk}/').status_code, 405)
        self.assertEqual(self.client.get(f'/api/switches/{pk}/puertos/').json(), [])

    def test_csrf_login_logout_and_mutation(self):
        client = Client(enforce_csrf_checks=True)
        creds = dict(username='editor',password='test-password')
        self.assertEqual(client.post('/api/auth/login/',creds).status_code,403)
        token = client.get('/api/auth/session/').json()['csrfToken']
        response = client.post('/api/auth/login/',creds,HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code,200)
        token = response.json()['csrfToken']
        self.assertTrue(response.json()['user']['can_edit'])
        self.assertEqual(client.post('/api/switches/',self.payload).status_code,403)
        self.assertEqual(client.post('/api/switches/',self.payload,HTTP_X_CSRFTOKEN=token).status_code,201)
        self.assertEqual(client.post('/api/auth/logout/').status_code,403)
        self.assertEqual(client.post('/api/auth/logout/',HTTP_X_CSRFTOKEN=token).status_code,200)
        self.assertIsNone(client.get('/api/auth/session/').json()['user'])

    def test_history_and_zabbix_require_session(self):
        switch = Switch.objects.create(nombre='SW', hostname='192.0.2.9', plantel=self.plantel)
        port = Puerto.objects.create(switch=switch, nombre='Gi1/0/1', indice=1)
        for path in ('/api/integrations/zabbix/', f'/api/switches/{switch.pk}/historial/', f'/api/puertos/{port.pk}/historial/'):
            self.assertEqual(self.client.get(path).status_code, 403, path)
        self.client.force_login(self.reader)
        # Sin InfluxDB responde vacío, pero ya no falla por el import de Puerto.
        self.assertEqual(self.client.get(f'/api/puertos/{port.pk}/historial/').status_code, 200)
        self.assertEqual(self.client.get('/api/puertos/9999/historial/').status_code, 404)

    def test_flux_string_escapes_quotes(self):
        self.assertEqual(flux_string('a"b\\c'), 'a\\"b\\\\c')

    def test_inactive_user_cannot_login(self):
        self.editor.is_active=False
        self.editor.save()
        self.assertEqual(self.client.post('/api/auth/login/',dict(username='editor',password='test-password')).status_code,401)

class PollTests(TestCase):
    def setUp(self):
        plantel=Plantel.objects.create(nombre='Lab',division=Division.objects.create(nombre='Test'))
        self.switch=Switch.objects.create(nombre='Lab',hostname='192.0.2.1',plantel=plantel)
        self.data=dict(cpu_5s=0,cpu_1m=None,cpu_5m=1,interfaces=[dict(indice=1,nombre='Gi1',estado='up',errores_entrada=0,errores_salida=None,errores_crc=None)])

    def test_observation_preserves_manual_fields_and_unknown(self):
        port=Puerto.objects.create(switch=self.switch,nombre='Gi1',indice=1,estado='naranja',vlan=22,es_trunk=True)
        record_poll(self.switch.pk,self.switch.hostname,self.data)
        port.refresh_from_db(); self.switch.refresh_from_db()
        self.assertEqual((port.estado,port.vlan,port.es_trunk),('naranja',22,True))
        self.assertEqual(port.estado_operativo,'up')
        self.assertEqual(port.errores_entrada,0)
        self.assertIsNone(port.errores_crc)
        self.assertEqual(self.switch.cpu_5s,0)
        self.assertTrue(self.switch.lectura_correcta)
        record_poll(self.switch.pk,self.switch.hostname,None)
        port.refresh_from_db(); self.switch.refresh_from_db()
        self.assertEqual(port.estado_operativo,'unknown')
        self.assertIsNone(port.errores_entrada)
        self.assertFalse(self.switch.lectura_correcta)
        self.assertIsNone(self.switch.cpu_5m)

    def test_stale_inventory_does_not_update(self):
        record_poll(self.switch.pk,'192.0.2.2',self.data)
        self.assertFalse(Puerto.objects.exists())
        self.switch.activo=False; self.switch.save()
        record_poll(self.switch.pk,self.switch.hostname,self.data)
        self.assertFalse(Puerto.objects.exists())

    def test_invalid_index_rolls_back_poll(self):
        self.data['interfaces'][0]['indice']=None
        with self.assertRaises(ValueError): record_poll(self.switch.pk,self.switch.hostname,self.data)
        self.switch.refresh_from_db()
        self.assertIsNone(self.switch.ultima_consulta)


class SummaryAndSecurityTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.reader = get_user_model().objects.create_user(username='reader', password='test-password', rol='lector')
        plantel = Plantel.objects.create(nombre='Apan', division=Division.objects.create(nombre='Escuelas'))
        self.ok = Switch.objects.create(nombre='SW-OK', hostname='192.0.2.1', plantel=plantel)
        self.hot = Switch.objects.create(nombre='SW-HOT', hostname='192.0.2.2', plantel=plantel, rol='core')
        record_poll(self.ok.pk, self.ok.hostname, dict(cpu_5m=10, memoria_usada_pct=40, interfaces=[
            dict(indice=1, nombre='GigabitEthernet1/0/1', estado='up', errores_crc=5),
            dict(indice=2, nombre='Vlan1', estado='up')]))
        record_poll(self.hot.pk, self.hot.hostname, dict(cpu_5m=95, interfaces=[]))

    def test_summary_classifies_devices(self):
        self.assertEqual(self.client.get('/api/resumen/').status_code, 403)
        self.client.force_login(self.reader)
        data = self.client.get('/api/resumen/').json()
        by_name = {item['nombre']: item for item in data['switches']}
        self.assertEqual(by_name['SW-HOT']['estado'], 'critical')
        self.assertIn('CPU en 95% (≥ 90%)', [r['text'] for r in by_name['SW-HOT']['motivos']])
        self.assertEqual(by_name['SW-OK']['estado'], 'ok')
        # Vlan1 no es físico y no cuenta.
        self.assertEqual(by_name['SW-OK']['puertos']['total'], 1)
        self.assertFalse(data['worker_atrasado'])
        self.assertEqual(data['umbrales']['core']['cpu_riesgo'], 90)

    def test_thresholds_per_role_and_new_errors(self):
        from switches.models import UmbralRol
        UmbralRol.objects.update_or_create(rol='core', defaults=dict(cpu_riesgo=99, cpu_atencion=80))
        record_poll(self.ok.pk, self.ok.hostname, dict(cpu_5m=10, interfaces=[
            dict(indice=1, nombre='GigabitEthernet1/0/1', estado='up', errores_crc=8)]))
        port = Puerto.objects.get(switch=self.ok, indice=1)
        self.assertEqual(port.errores_nuevos, 3)
        self.assertIsNotNone(port.ultimo_error)
        self.client.force_login(self.reader)
        data = self.client.get('/api/resumen/?refresh=1').json()
        by_name = {item['nombre']: item for item in data['switches']}
        self.assertEqual(by_name['SW-HOT']['estado'], 'warning')
        self.assertEqual(by_name['SW-OK']['estado'], 'warning')
        self.assertEqual(by_name['SW-OK']['puertos']['con_errores'], 1)

    def test_login_is_throttled(self):
        for _ in range(5):
            self.assertEqual(self.client.post('/api/auth/login/', dict(username='reader', password='bad')).status_code, 401)
        response = self.client.post('/api/auth/login/', dict(username='reader', password='test-password'))
        self.assertEqual(response.status_code, 429)

    def test_optional_pagination(self):
        self.client.force_login(self.reader)
        self.assertIsInstance(self.client.get('/api/switches/').json(), list)
        page = self.client.get('/api/switches/?page=1&page_size=1').json()
        self.assertEqual((page['count'], len(page['results'])), (2, 1))

    def test_alert_on_transition_with_cooldown(self):
        from unittest.mock import patch
        from switches import alerts
        message = alerts.evaluate(self.hot.pk)
        self.assertIn('SW-HOT', message)
        self.assertIsNone(alerts.evaluate(self.hot.pk))
        record_poll(self.hot.pk, self.hot.hostname, dict(cpu_5m=5, interfaces=[]))
        # Recuperación dentro del cooldown: no se reenvía.
        self.assertIsNone(alerts.evaluate(self.hot.pk))
        with patch.dict('os.environ', ALERT_WEBHOOK_URL='http://hook.test'), patch.object(alerts, '_post') as post:
            alerts.send('hola')
        post.assert_called_once_with('http://hook.test', {'text': 'hola'})

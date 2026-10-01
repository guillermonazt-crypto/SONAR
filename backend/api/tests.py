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
        response = client.post('/api/auth/logout/',HTTP_X_CSRFTOKEN=token)
        self.assertEqual((response.status_code, response.content), (204, b''))
        # El token CSRF sigue valiendo para volver a iniciar sesión.
        self.assertEqual(client.post('/api/auth/login/',creds,HTTP_X_CSRFTOKEN=token).status_code,200)
        client.post('/api/auth/logout/',HTTP_X_CSRFTOKEN=client.get('/api/auth/session/').json()['csrfToken'])
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

    def test_global_search_by_mac_ip_and_description(self):
        switch = Switch.objects.create(nombre='SW-APAN', hostname='192.0.2.10', plantel=self.plantel)
        access = Puerto.objects.create(switch=switch, nombre='Gi1/0/5', indice=5, vlan=20, descripcion='Recepción',
                                       ip_equipo='10.1.1.10, 10.1.1.11', mac_equipo='00:50:56:ab:cd:ef',
                                       mac_telefono='00:11:22:33:44:55')
        Puerto.objects.create(switch=switch, nombre='Gi1/0/48', indice=48, es_trunk=True,
                              mac_equipo='00:50:56:ab:cd:ef')
        Puerto.objects.create(switch=switch, nombre='Vlan20', indice=900, es_fisico=False, ip_equipo='10.1.1.10')
        self.assertEqual(self.client.get('/api/buscar/?q=10.1.1.10').status_code, 403)
        self.client.force_login(self.reader)
        search = lambda q: self.client.get('/api/buscar/', {'q': q}).json()
        # Cualquier formato de MAC; el puerto de acceso va antes que el troncal.
        for query in ('0050.56ab.cdef', '00-50-56-AB-CD-EF', '00:50:56:ab'):
            ports = search(query)['puertos']
            self.assertEqual([p['nombre'] for p in ports], ['Gi1/0/5', 'Gi1/0/48'], query)
        result = search('10.1.1.11')['puertos'][0]
        self.assertEqual((result['id'], result['coincide'], result['valor'], result['exacto']), (access.pk, 'ip', '10.1.1.11', True))
        self.assertEqual(result['switch']['plantel_nombre'], 'Lab')
        self.assertEqual(search('10.1.1.1')['puertos'][0]['exacto'], False)
        self.assertEqual(search('1122.3344')['puertos'][0]['coincide'], 'telefono')
        self.assertEqual(search('recep')['puertos'][0]['coincide'], 'descripcion')
        self.assertEqual(search('192.0.2')['switches'][0]['nombre'], 'SW-APAN')
        self.assertEqual(search('10')['puertos'], [])

    def test_switch_list_includes_health(self):
        from django.utils import timezone
        down = Switch.objects.create(nombre='SW-DOWN', hostname='192.0.2.20', plantel=self.plantel,
                                     lectura_correcta=False, ultima_consulta=timezone.now())
        Switch.objects.create(nombre='SW-OK', hostname='192.0.2.21', plantel=self.plantel,
                              lectura_correcta=True, ultima_consulta=timezone.now(), cpu_5m=10)
        self.client.force_login(self.reader)
        items = {item['nombre']: item for item in self.client.get('/api/switches/').json()}
        self.assertEqual(items['SW-DOWN']['estado'], 'critical')
        self.assertEqual(items['SW-DOWN']['motivos'][0]['text'], 'No responde a SNMP')
        self.assertEqual((items['SW-OK']['estado'], items['SW-OK']['motivos']), ('ok', []))
        self.assertEqual(self.client.get(f'/api/switches/{down.pk}/').json()['estado'], 'critical')

    def test_optics_levels_and_links_ports(self):
        from django.core.cache import cache
        from switches.models import UmbralOptico
        cache.clear()
        switch = Switch.objects.create(nombre='SW-CORE', hostname='192.0.2.30', plantel=self.plantel)
        module = dict(rx=dict(alta_alarma=3.0, alta_aviso=0.0, baja_aviso=-17.0, baja_alarma=-21.0))
        base = dict(time='2026-01-01T00:00:00+00:00', estado='ok', sin_senal=False, admin='up', umbrales={})
        ports = {}
        for index, (name, reading) in enumerate([
            ('TenGigabitEthernet1/1/1', dict(rx_dbm=-3.1, tx_dbm=-2.0, temperatura=35.0, rx_base_dbm=-3.0)),
            ('TenGigabitEthernet1/1/2', dict(rx_dbm=-21.4, tx_dbm=-2.2, temperatura=36.0, rx_base_dbm=-8.0, umbrales=module)),
            ('TenGigabitEthernet1/1/3', dict(rx_dbm=-6.0, tx_dbm=-2.1, temperatura=71.0, rx_base_dbm=-6.0)),
            ('TenGigabitEthernet1/1/4', dict(rx_dbm=None, tx_dbm=-8.0, temperatura=None, rx_base_dbm=None, estado='alerta')),
        ], start=1):
            ports[name] = Puerto.objects.create(switch=switch, nombre=name, indice=100 + index,
                                                estado_operativo='up', optica=dict(base, **reading))
        Puerto.objects.create(switch=switch, nombre='GigabitEthernet1/0/1', indice=1)
        self.assertEqual(self.client.get('/api/opticas/').status_code, 403)
        self.client.force_login(self.reader)
        data = self.client.get('/api/opticas/').json()
        levels = {item['interfaz']: (item['nivel'], [r['text'] for r in item['motivos']]) for item in data['transceptores']}
        self.assertEqual(len(levels), 4)
        self.assertEqual(levels['TenGigabitEthernet1/1/1'], ('ok', []))
        # El umbral del módulo (-21 alarma) manda sobre el global; además cayó frente a su base.
        self.assertEqual(levels['TenGigabitEthernet1/1/2'][0], 'critical')
        self.assertIn('RX -21.4 dBm (≤ -21, umbral del módulo)', levels['TenGigabitEthernet1/1/2'][1])
        self.assertIn('RX cayó 13.4 dB frente a su línea base de 7 días (-8.0 dBm)', levels['TenGigabitEthernet1/1/2'][1])
        self.assertEqual(levels['TenGigabitEthernet1/1/3'], ('warning', ['Temperatura 71 °C (≥ 70, umbral global)']))
        self.assertEqual(levels['TenGigabitEthernet1/1/4'][0], 'warning')
        first = data['transceptores'][0]
        self.assertEqual(first['interfaz'], 'TenGigabitEthernet1/1/2')
        self.assertEqual((first['niveles']['rx'], first['umbrales']['rx']['origen']), ('critical', 'switch'))
        linked = next(item for item in data['transceptores'] if item['interfaz'] == 'TenGigabitEthernet1/1/1')
        self.assertEqual((linked['puerto_id'], linked['switch']['nombre']), (ports['TenGigabitEthernet1/1/1'].pk, 'SW-CORE'))
        self.assertEqual((linked['atenuacion'], linked['umbrales']['rx']['origen']), (1.1, 'global'))
        # Umbrales editables: bajar la temperatura de atención cambia el nivel.
        UmbralOptico.objects.create(temp_atencion=30)
        data = self.client.get('/api/opticas/?refresh=1').json()
        self.assertEqual(data['umbrales']['temp_atencion'], 30)
        self.assertEqual(next(i for i in data['transceptores'] if i['interfaz'] == 'TenGigabitEthernet1/1/1')['nivel'], 'warning')

    def test_unchanged_api_responses_return_304(self):
        Switch.objects.create(nombre='SW', hostname='192.0.2.40', plantel=self.plantel)
        self.client.force_login(self.reader)
        first = self.client.get('/api/switches/')
        self.assertEqual(first.status_code, 200)
        self.assertIn('no-cache', first['Cache-Control'])
        again = self.client.get('/api/switches/', HTTP_IF_NONE_MATCH=first['ETag'])
        self.assertEqual((again.status_code, again.content), (304, b''))
        Switch.objects.filter(nombre='SW').update(cpu_5m=50)
        self.assertEqual(self.client.get('/api/switches/', HTTP_IF_NONE_MATCH=first['ETag']).status_code, 200)

    def test_alert_center_maintenance_and_audit(self):
        from datetime import timedelta
        from unittest.mock import patch
        from django.utils import timezone
        from switches import alerts
        from switches.models import Alerta
        from usuarios.models import Bitacora
        now = timezone.now()
        down = Switch.objects.create(nombre='SW-DOWN', hostname='192.0.2.50', plantel=self.plantel,
                                     lectura_correcta=False, ultima_consulta=now)
        # Episodio notificado: se abre la alerta y se avisa.
        self.assertIn('SW-DOWN', alerts.evaluate(down.pk, now))
        alert = Alerta.objects.get()
        self.assertTrue(alert.notificada)
        self.assertEqual(alert.motivos[0]['text'], 'No responde a SNMP')
        # El lector ve las alertas pero no puede reconocerlas.
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get('/api/alertas/resumen/').json(), dict(abiertas=1, sin_reconocer=1))
        self.assertEqual(self.client.post(f'/api/alertas/{alert.pk}/reconocer/', {'nota': 'x'}).status_code, 403)
        self.assertEqual(self.client.get('/api/bitacora/').status_code, 403)
        self.client.force_login(self.editor)
        response = self.client.post(f'/api/alertas/{alert.pk}/reconocer/', {'nota': 'Cuadrilla en camino'})
        self.assertEqual(response.json()['reconocida_por'], 'editor')
        self.assertEqual(self.client.get('/api/alertas/resumen/').json(), dict(abiertas=1, sin_reconocer=0))
        self.assertEqual(self.client.get(f'/api/alertas/{alert.pk}/').json()['nota'], 'Cuadrilla en camino')
        # Se recupera: la alerta se cierra.
        Switch.objects.filter(pk=down.pk).update(lectura_correcta=True, ultima_consulta=now + timedelta(hours=1),
                                                 ultima_lectura_exitosa=now + timedelta(hours=1))
        alerts.evaluate(down.pk, now + timedelta(hours=1))
        self.assertIsNotNone(Alerta.objects.get().fin)
        self.assertEqual(self.client.get('/api/alertas/?estado=abiertas').json(), [])
        # Ventana de mantenimiento del plantel: se registra pero no se notifica.
        window = dict(plantel=self.plantel.pk, inicio=(now + timedelta(hours=1)).isoformat(),
                      fin=(now + timedelta(hours=5)).isoformat(), motivo='Cambio de UPS')
        self.assertEqual(self.client.post('/api/mantenimientos/', dict(window, switch=down.pk)).status_code, 400)
        self.assertEqual(self.client.post('/api/mantenimientos/', dict(window, fin=window['inicio'])).status_code, 400)
        created = self.client.post('/api/mantenimientos/', window)
        self.assertEqual(created.status_code, 201, created.content)
        Switch.objects.filter(pk=down.pk).update(lectura_correcta=False, nivel_alerta='ok')
        self.assertIsNone(alerts.evaluate(down.pk, now + timedelta(hours=2)))
        self.assertTrue(Alerta.objects.filter(fin__isnull=True).get().en_mantenimiento)
        with patch('api.views.timezone.now', return_value=now + timedelta(hours=2)):
            listed = {s['nombre']: s for s in self.client.get('/api/switches/').json()}
        self.assertEqual(listed['SW-DOWN']['mantenimiento']['motivo'], 'Cambio de UPS')
        # Bitácora: edición con los campos que cambiaron.
        self.client.patch(f'/api/switches/{down.pk}/', data='{"nombre":"SW-CAIDO"}', content_type='application/json')
        entries = self.client.get('/api/bitacora/').json()
        self.assertEqual(entries[0]['descripcion'], 'Editó switch SW-CAIDO (192.0.2.50)')
        self.assertEqual(entries[0]['cambios'], {'nombre': ['SW-DOWN', 'SW-CAIDO']})
        self.assertEqual({e['accion'] for e in entries}, {'editar', 'crear', 'reconocer'})
        self.assertEqual(self.client.delete(f"/api/mantenimientos/{created.json()['id']}/").status_code, 204)
        self.assertTrue(Bitacora.objects.filter(accion='eliminar', objeto='mantenimiento').exists())

    def test_reports_json_and_csv(self):
        from datetime import timedelta
        from django.utils import timezone
        from switches.models import Alerta, EventoPuerto
        now = timezone.now()
        core = Switch.objects.create(nombre='SW-CORE', hostname='192.0.2.60', plantel=self.plantel, rol='core',
                                     poe_presupuesto_w=370, poe_consumo_w=333,
                                     hardware=[dict(tipo='fuente', nombre='PS1', estado='critical', valor=None)])
        access = Switch.objects.create(nombre='SW-ACC', hostname='192.0.2.61', plantel=self.plantel)
        Puerto.objects.create(switch=core, nombre='Te1/1/1', indice=1, es_trunk=True, vecino_nombre='SW-ACC.uaeh.mx',
                              vecino_puerto='Gi1/1/1', vecino_ip='192.0.2.61', estado_operativo='up', uso_pct=95.5,
                              velocidad_mbps=10000)
        Puerto.objects.create(switch=core, nombre='Te1/1/2', indice=2, vecino_nombre='AP-01', estado_operativo='up',
                              vecino_tipo='ap', vecino_plataforma='cisco AIR-AP2802I', vlan=30, poe_mw=15400)
        Puerto.objects.create(switch=access, nombre='Gi1/0/3', indice=3, vecino_nombre='SEP001122334455',
                              vecino_tipo='telefono', vlan=10, voice_vlan=110, vecino_ip='192.0.2.90',
                              estado_operativo='up')
        Puerto.objects.create(switch=access, nombre='Gi1/0/4', indice=4, mac_telefono='00:11:22:33:44:66',
                              estado_operativo='up')
        unused = Puerto.objects.create(switch=access, nombre='Gi1/0/7', indice=7, estado_operativo='down',
                                       ultimo_activo=now - timedelta(days=45))
        Puerto.objects.create(switch=access, nombre='Gi1/0/8', indice=8, estado_operativo='down', ultimo_activo=now - timedelta(days=2))
        flapping = Puerto.objects.create(switch=access, nombre='Gi1/0/9', indice=9, estado_operativo='up')
        for minute in range(5):
            EventoPuerto.objects.create(puerto=flapping, estado='up' if minute % 2 else 'down', momento=now - timedelta(minutes=minute))
        Alerta.objects.create(switch=access, motivos=[dict(level='critical', text='No responde a SNMP')],
                              inicio=now - timedelta(hours=3), fin=now - timedelta(hours=1))
        self.assertEqual(self.client.get('/api/reportes/inventario/').status_code, 403)
        self.client.force_login(self.reader)
        get = lambda kind, **params: self.client.get(f'/api/reportes/{kind}/', params).json()
        self.assertEqual(self.client.get('/api/reportes/nada/').status_code, 404)
        self.assertEqual({r['switch'] for r in get('inventario')['filas']}, {'SW-CORE', 'SW-ACC'})
        availability = {r['switch']: r for r in get('disponibilidad', dias=1)['filas']}
        self.assertEqual(availability['SW-ACC']['minutos_caido'], 120)
        self.assertEqual(availability['SW-ACC']['disponibilidad'], round(100 - 120 * 100 / 1440, 3))
        self.assertEqual(availability['SW-CORE']['disponibilidad'], 100)
        self.assertEqual([r['puerto'] for r in get('puertos-sin-uso', dias=30)['filas']], ['Gi1/0/7'])
        self.assertEqual(get('puertos-sin-uso', dias=30)['filas'][0]['puerto_id'], unused.pk)
        self.assertEqual(get('puertos-inestables')['filas'][0]['cambios'], 5)
        self.assertEqual(get('puertos-saturados')['filas'][0]['uso_pct'], 95.5)
        self.assertEqual(get('poe')['filas'][0]['uso_pct'], 90.0)
        self.assertEqual(get('hardware')['filas'][0]['estado'], 'critical')
        topology = {r['vecino']: r for r in get('topologia')['filas']}
        self.assertEqual((topology['SW-ACC.uaeh.mx']['vecino_id'], topology['AP-01']['vecino_id']), (access.pk, None))
        self.assertEqual((topology['AP-01']['vecino_tipo'], topology['AP-01']['tipo_equipo']), ('ap', 'Access point'))
        endpoints = {r['puerto']: r for r in get('aps-telefonos')['filas']}
        self.assertEqual(set(endpoints), {'Te1/1/2', 'Gi1/0/3', 'Gi1/0/4'})
        self.assertEqual((endpoints['Te1/1/2']['tipo_equipo'], endpoints['Te1/1/2']['poe_w']), ('Access point', 15.4))
        self.assertEqual((endpoints['Gi1/0/3']['vecino_tipo'], endpoints['Gi1/0/3']['vlan']), ('telefono', 110))
        self.assertEqual(endpoints['Gi1/0/4']['vecino'], '00:11:22:33:44:66')
        self.assertIn('enlace', endpoints['Te1/1/2'])
        self.assertEqual([r['puerto'] for r in get('aps-telefonos', equipo='ap')['filas']], ['Te1/1/2'])
        csv = self.client.get('/api/reportes/puertos-sin-uso/', dict(formato='csv'))
        self.assertIn('attachment; filename="sonar-puertos-sin-uso-', csv['Content-Disposition'])
        lines = csv.content.decode('utf-8-sig').splitlines()
        self.assertEqual(lines[0], 'Switch,Plantel,Puerto,Descripción,VLAN,Sin enlace desde,Días')
        self.assertTrue(lines[1].startswith('SW-ACC,Lab,Gi1/0/7,'))
        Puerto.objects.filter(pk=unused.pk).update(descripcion='=HYPERLINK("http://x")')
        csv = self.client.get('/api/reportes/puertos-sin-uso/', dict(formato='csv')).content.decode('utf-8-sig')
        self.assertIn('"\'=HYPERLINK(""http://x"")"', csv)

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

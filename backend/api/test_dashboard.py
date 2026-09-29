from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from planteles.models import Division, Plantel
from switches.health import summarize_sites
from switches.models import Alerta, Mantenimiento, Switch
from switches.services import record_poll


class SiteDashboardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.reader = get_user_model().objects.create_user(username='reader', password='test-password', rol='lector')
        division = Division.objects.create(nombre='Escuelas')
        self.apan = Plantel.objects.create(nombre='Apan', division=division)
        self.tula = Plantel.objects.create(nombre='Tula', division=division)
        self.empty = Plantel.objects.create(nombre='Zimapán', division=division)
        Plantel.objects.create(nombre='Cerrado', division=division, activo=False)
        self.ok = Switch.objects.create(nombre='SW-OK', hostname='192.0.2.1', plantel=self.apan)
        self.down = Switch.objects.create(nombre='SW-DOWN', hostname='192.0.2.2', plantel=self.apan)
        self.warm = Switch.objects.create(nombre='SW-WARM', hostname='192.0.2.3', plantel=self.tula)
        Switch.objects.create(nombre='SW-OFF', hostname='192.0.2.4', plantel=self.tula, activo=False)
        record_poll(self.ok.pk, self.ok.hostname, dict(cpu_5m=10, interfaces=[
            dict(indice=1, nombre='GigabitEthernet1/0/1', estado='up'),
            dict(indice=2, nombre='GigabitEthernet1/0/2', estado='down')]))
        record_poll(self.down.pk, self.down.hostname, None)
        record_poll(self.warm.pk, self.warm.hostname, dict(cpu_5m=75, interfaces=[]))
        self.alert = Alerta.objects.create(switch=self.down, inicio=timezone.now(),
                                           motivos=[dict(level='critical', tipo='snmp', text='No responde a SNMP')])

    def test_summary_includes_every_active_site(self):
        Mantenimiento.objects.create(plantel=self.tula, inicio=timezone.now() - timezone.timedelta(hours=1),
                                     fin=timezone.now() + timezone.timedelta(hours=1), motivo='Cableado')
        self.client.force_login(self.reader)
        data = self.client.get('/api/resumen/').json()
        sites = {site['nombre']: site for site in data['planteles']}
        # Los planteles activos aparecen aunque no tengan equipos; los inactivos vacíos no.
        self.assertEqual(set(sites), {'Apan', 'Tula', 'Zimapán'})
        # El peor equipo manda y el orden pone primero lo urgente.
        self.assertEqual([site['nombre'] for site in data['planteles']], ['Apan', 'Tula', 'Zimapán'])
        apan, tula, empty = sites['Apan'], sites['Tula'], sites['Zimapán']
        self.assertEqual((apan['estado'], apan['equipos'], apan['sin_respuesta']), ('critical', 2, 1))
        self.assertEqual(apan['niveles'], dict(ok=1, warning=0, critical=1))
        self.assertEqual((apan['alertas_abiertas'], apan['alertas_sin_reconocer']), (1, 1))
        self.assertEqual(apan['disponibilidad'], 50.0)
        self.assertEqual((apan['puertos']['total'], apan['puertos']['up']), (2, 1))
        # Un equipo desactivado no cuenta para el estado del plantel.
        self.assertEqual((tula['estado'], tula['equipos'], tula['inactivos']), ('warning', 1, 1))
        self.assertTrue(tula['mantenimiento'])
        self.assertEqual((empty['estado'], empty['equipos'], empty['disponibilidad']), ('none', 0, None))
        by_name = {item['nombre']: item for item in data['switches']}
        self.assertEqual(by_name['SW-DOWN']['alerta'], dict(id=self.alert.pk, desde=self.alert.inicio.isoformat(),
                                                             reconocida=False))
        self.assertIsNone(by_name['SW-OK']['alerta'])
        self.assertEqual(by_name['SW-DOWN']['motivos'][0]['tipo'], 'snmp')

    def test_summarize_sites_uses_the_worst_level(self):
        devices = [dict(plantel=self.apan.pk, activo=True, estado=level, lectura_correcta=True, puertos={})
                   for level in ('ok', 'warning', 'ok')]
        (site,) = summarize_sites([self.apan], devices)
        self.assertEqual((site['estado'], site['niveles']['warning'], site['disponibilidad']), ('warning', 1, 100.0))


class AlertFilterTests(TestCase):
    def setUp(self):
        self.reader = get_user_model().objects.create_user(username='reader', password='test-password', rol='lector')
        division = Division.objects.create(nombre='Escuelas')
        apan = Plantel.objects.create(nombre='Apan', division=division)
        tula = Plantel.objects.create(nombre='Tula', division=division)
        self.apan_sw = Switch.objects.create(nombre='SW-APAN', hostname='192.0.2.1', plantel=apan)
        self.tula_sw = Switch.objects.create(nombre='SW-TULA', hostname='192.0.2.2', plantel=tula)
        now = timezone.now()
        # Alerta antigua: sin 'tipo' en sus motivos.
        self.legacy = Alerta.objects.create(switch=self.apan_sw, inicio=now, fin=now,
                                            motivos=[dict(level='critical', text='No responde a SNMP')])
        self.cpu = Alerta.objects.create(switch=self.tula_sw, inicio=now,
                                         motivos=[dict(level='critical', tipo='cpu', text='CPU en 95% (≥ 90%)')])
        self.plantel = apan

    def test_filters_by_site_type_and_state(self):
        self.client.force_login(self.reader)
        ids = lambda **params: [a['id'] for a in self.client.get('/api/alertas/', params).json()]
        self.assertEqual(set(ids()), {self.legacy.pk, self.cpu.pk})
        self.assertEqual(ids(plantel=self.plantel.pk), [self.legacy.pk])
        self.assertEqual(ids(tipo='snmp'), [self.legacy.pk])
        self.assertEqual(ids(tipo='cpu', estado='abiertas'), [self.cpu.pk])
        self.assertEqual(ids(estado='cerradas'), [self.legacy.pk])
        self.assertEqual(ids(sin_reconocer=1, tipo='memoria'), [])
        # Los motivos antiguos se entregan ya clasificados.
        legacy = self.client.get(f'/api/alertas/{self.legacy.pk}/').json()
        self.assertEqual(legacy['motivos'][0]['tipo'], 'snmp')


class TrendReportTests(TestCase):
    def setUp(self):
        from datetime import timedelta
        self.reader = get_user_model().objects.create_user(username='reader', password='test-password', rol='lector')
        plantel = Plantel.objects.create(nombre='Apan', division=Division.objects.create(nombre='Escuelas'))
        self.core = Switch.objects.create(nombre='SW-CORE', hostname='192.0.2.1', plantel=plantel, rol='core')
        self.edge = Switch.objects.create(nombre='SW-EDGE', hostname='192.0.2.2', plantel=plantel)
        self.now = timezone.now()
        Alerta.objects.create(switch=self.edge, inicio=self.now - timedelta(hours=2), fin=self.now - timedelta(hours=1))
        # Episodio que empezó antes del periodo: sólo cuenta la parte dentro.
        Alerta.objects.create(switch=self.core, inicio=self.now - timedelta(days=40), fin=self.now - timedelta(days=29, hours=23))

    def point(self, hours_ago, cpu, memoria, entrada, salida, uptime):
        from datetime import timedelta
        return dict(time=(self.now - timedelta(hours=hours_ago)).isoformat(), cpu=cpu, memoria=memoria,
                    entrada_bps=entrada, salida_bps=salida, uptime=uptime)

    def test_trends_from_influx(self):
        from unittest.mock import patch
        series = {'SW-CORE': [self.point(3, 20, 50, 1000, 3000, 900), self.point(2, 60, 70, 2000, 1000, 100),
                              self.point(1, None, None, None, None, 4000)],
                  'SW-EDGE': []}
        with patch('api.history.switch_trends', return_value=(series, 'red_15m')) as trends:
            self.client.force_login(self.reader)
            data = self.client.get('/api/reportes/tendencias/', {'dias': 30}).json()
        trends.assert_called_once()
        self.assertEqual(trends.call_args.args[1], 30)
        self.assertEqual(data['titulo'], 'Tendencias · últimos 30 días')
        self.assertIn('red_15m', data['descripcion'])
        rows = {row['switch']: row for row in data['filas']}
        core = rows['SW-CORE']
        self.assertEqual((core['cpu_prom'], core['cpu_max'], core['memoria_max']), (40.0, 60.0, 70.0))
        self.assertEqual((core['entrada_bps'], core['pico_bps'], core['reinicios']), (1500.0, 3000.0, 1))
        self.assertEqual((core['alertas'], core['minutos_riesgo']), (0, 60))
        self.assertEqual((rows['SW-EDGE']['alertas'], rows['SW-EDGE']['cpu_prom']), (1, None))
        self.assertEqual(len(data['serie']), 31)
        today = data['serie'][-1]
        self.assertEqual(today['alertas'], 1)

    def test_trends_fall_back_when_influx_is_down(self):
        from unittest.mock import patch
        with patch('api.history.switch_trends', side_effect=ConnectionError('sin ruta')):
            self.client.force_login(self.reader)
            data = self.client.get('/api/reportes/tendencias/', {'dias': 9}).json()
            csv = self.client.get('/api/reportes/tendencias/', {'formato': 'csv'})
        # Sólo 7 o 30 días: 9 se ajusta a 7.
        self.assertEqual(data['titulo'], 'Tendencias · últimos 7 días')
        self.assertIn('InfluxDB no respondió', data['detalle'])
        rows = {row['switch']: row for row in data['filas']}
        self.assertEqual((rows['SW-EDGE']['alertas'], rows['SW-EDGE']['minutos_riesgo']), (1, 60))
        self.assertIsNone(rows['SW-EDGE']['reinicios'])
        self.assertEqual(csv.status_code, 200)

    def test_trend_bucket_fallback(self):
        from unittest.mock import patch
        from api import history

        def fake(names, hours, every, bucket):
            if bucket.endswith('_15m'):
                raise RuntimeError('bucket not found')
            return {'SW': [dict(time='2026-01-01T00:00:00+00:00')]}
        with patch.object(history, 'switch_histories', side_effect=fake):
            series, bucket = history.switch_trends(['SW'], 30)
        self.assertEqual(bucket, history.influx_settings()[3])
        self.assertEqual(len(series['SW']), 1)

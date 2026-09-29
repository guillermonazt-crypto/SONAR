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

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from planteles.models import Division, Plantel
from .alerts import evaluate
from .health import assess, connection_state, port_stats, thresholds_by_role
from .models import Alerta, EstadoMonitoreo, Puerto, Switch
from .services import mark_worker_started, record_poll

DATA = dict(cpu_5m=5, interfaces=[dict(indice=1, nombre='Gi1/0/1', estado='up')])


class LayeredValidationTests(TestCase):
    """Un switch sólo pasa a rojo tras 2 fallos SNMP seguidos y sin otro método que lo vea vivo."""

    def setUp(self):
        self.t0 = timezone.now()
        self.plantel = Plantel.objects.create(nombre='Lab', division=Division.objects.create(nombre='Test'))
        self.switch = Switch.objects.create(nombre='SW-A', hostname='192.0.2.1', plantel=self.plantel)
        mark_worker_started(self.t0 - timedelta(hours=1))
        self.poll(self.t0, DATA)

    def poll(self, at, datos, icmp=None, switch=None):
        switch = switch or self.switch
        with mock.patch('switches.services.timezone.now', return_value=at):
            record_poll(switch.pk, switch.hostname, datos, None if datos else dict(icmp=icmp))
        switch.refresh_from_db()

    def health(self, at):
        switch = Switch.objects.get(pk=self.switch.pk)
        started = EstadoMonitoreo.actual().iniciado
        level, reasons = assess(switch, port_stats([switch.pk], at)[switch.pk], thresholds_by_role()[switch.rol],
                                at, started=started)
        return connection_state(switch, started, at)[0], level, reasons

    def test_single_failure_does_not_flip(self):
        self.poll(self.t0 + timedelta(minutes=1), None, icmp=False)
        self.assertEqual(self.switch.fallos_consecutivos, 1)
        self.assertEqual(self.switch.metodos_fallidos, ['snmp', 'icmp'])
        at = self.t0 + timedelta(minutes=1, seconds=5)
        state, level, reasons = self.health(at)
        self.assertEqual((state, level), ('activo', 'ok'))
        self.assertEqual(reasons[0]['tipo'], 'verificando')
        self.assertIsNone(evaluate(self.switch.pk, at))
        self.assertFalse(Alerta.objects.exists())

    def test_two_failures_without_ping_is_critical(self):
        self.poll(self.t0 + timedelta(minutes=1), None, icmp=False)
        self.poll(self.t0 + timedelta(minutes=2), None, icmp=False)
        self.assertEqual(self.switch.fallos_consecutivos, 2)
        self.assertIs(self.switch.verificacion['icmp'], False)
        at = self.t0 + timedelta(minutes=2, seconds=5)
        state, level, reasons = self.health(at)
        self.assertEqual((state, level), ('inactivo', 'critical'))
        self.assertIn('ping', reasons[0]['text'])
        self.assertIn('SW-A', evaluate(self.switch.pk, at))

    def test_ping_alive_is_warning_not_critical(self):
        self.poll(self.t0 + timedelta(minutes=1), None, icmp=True)
        self.poll(self.t0 + timedelta(minutes=2), None, icmp=True)
        self.assertEqual(self.switch.metodos_fallidos, ['snmp'])
        at = self.t0 + timedelta(minutes=2, seconds=5)
        state, level, reasons = self.health(at)
        self.assertEqual((state, level), ('inactivo', 'warning'))
        self.assertIn('equipo encendido', reasons[0]['text'])
        self.assertIsNone(evaluate(self.switch.pk, at))

    def test_neighbor_view_is_third_method(self):
        neighbor = Switch.objects.create(nombre='SW-B', hostname='192.0.2.2', plantel=self.plantel)
        at = self.t0 + timedelta(minutes=1)
        self.poll(at, dict(DATA, interfaces=[dict(indice=1, nombre='Gi1/0/1', estado='up', vecino_ip='192.0.2.1')]),
                  switch=neighbor)
        self.poll(at, None, icmp=None)
        self.poll(at + timedelta(minutes=1), None, icmp=None)
        self.assertIs(self.switch.verificacion['vecinos'], True)
        self.assertEqual(self.health(at + timedelta(minutes=1, seconds=5))[1], 'warning')
        # El vecino ve el enlace caído: tercer método también en falla.
        Puerto.objects.filter(switch=neighbor).update(estado_operativo='down')
        self.poll(at + timedelta(minutes=2), None, icmp=False)
        self.assertEqual(self.switch.metodos_fallidos, ['snmp', 'icmp', 'vecinos'])
        self.assertEqual(self.health(at + timedelta(minutes=2, seconds=5))[1], 'critical')

    def test_success_resets_counter(self):
        self.poll(self.t0 + timedelta(minutes=1), None, icmp=False)
        self.poll(self.t0 + timedelta(minutes=2), DATA)
        self.assertEqual((self.switch.fallos_consecutivos, self.switch.metodos_fallidos), (0, []))
        self.assertIsNone(self.switch.verificacion)
        self.poll(self.t0 + timedelta(minutes=3), None, icmp=False)
        self.assertEqual(self.health(self.t0 + timedelta(minutes=3, seconds=5))[0], 'activo')

    def test_summary_exposes_failures(self):
        from django.contrib.auth import get_user_model
        self.poll(self.t0 + timedelta(minutes=1), None, icmp=False)
        self.client.force_login(get_user_model().objects.create_user('lector', password='x'))
        device = self.client.get('/api/resumen/?refresh=1').json()['switches'][0]
        self.assertEqual(device['fallos_consecutivos'], 1)
        self.assertEqual(device['metodos_fallidos'], ['snmp', 'icmp'])

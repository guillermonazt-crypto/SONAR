from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from planteles.models import Division, Plantel
from .health import assess, port_stats, thresholds_by_role
from .models import EventoPuerto, Puerto, Switch
from .services import record_poll

PORT = dict(indice=1, nombre='GigabitEthernet1/0/1', estado='up', errores_entrada=0, errores_salida=0, errores_crc=0)


def poll(switch, at, datos=None, **port):
    with mock.patch('switches.services.timezone.now', return_value=at):
        record_poll(switch.pk, switch.hostname, dict(dict(interfaces=[dict(PORT, **port)]), **(datos or {})))


class PollTests(TestCase):
    def setUp(self):
        plantel = Plantel.objects.create(nombre='Lab', division=Division.objects.create(nombre='Test'))
        self.switch = Switch.objects.create(nombre='SW', hostname='192.0.2.1', plantel=plantel)
        self.t0 = timezone.now()

    def health(self):
        switch = Switch.objects.get(pk=self.switch.pk)
        return assess(switch, port_stats([switch.pk])[switch.pk], thresholds_by_role()[switch.rol])

    def test_traffic_rate_and_utilization(self):
        poll(self.switch, self.t0, octetos_entrada=0, octetos_salida=0, velocidad_mbps=100)
        port = Puerto.objects.get()
        self.assertIsNone(port.bps_entrada)
        # 60 s después: 600 MB de entrada = 80 Mbps sobre un enlace de 100 Mbps.
        poll(self.switch, self.t0 + timedelta(seconds=60), octetos_entrada=600_000_000, octetos_salida=75_000_000, velocidad_mbps=100)
        port.refresh_from_db()
        self.assertEqual((port.bps_entrada, port.bps_salida, port.uso_pct), (80_000_000, 10_000_000, 80.0))
        # Contador reiniciado: no se inventa una tasa negativa.
        poll(self.switch, self.t0 + timedelta(seconds=120), octetos_entrada=10, octetos_salida=10, velocidad_mbps=100)
        port.refresh_from_db()
        self.assertIsNone(port.bps_entrada)

    def test_saturated_port_warns(self):
        poll(self.switch, self.t0, octetos_entrada=0, octetos_salida=0, velocidad_mbps=10)
        poll(self.switch, self.t0 + timedelta(seconds=10), octetos_entrada=12_000_000, octetos_salida=0, velocidad_mbps=10)
        self.assertIn('1 puerto(s) al 90% o más de su capacidad', [r['text'] for r in self.health()[1]])

    def test_link_changes_and_flapping(self):
        poll(self.switch, self.t0 - timedelta(minutes=1), estado='down', ultimo_cambio_hace_s=3600)
        port = Puerto.objects.get()
        # Primer sondeo: ifLastChange fija desde cuándo está caído.
        self.assertEqual(port.ultimo_cambio, self.t0 - timedelta(minutes=61))
        self.assertEqual(port.ultimo_activo, port.ultimo_cambio)
        for minute, state in enumerate(['up', 'down', 'up', 'down']):
            poll(self.switch, self.t0 + timedelta(minutes=minute), estado=state)
        port.refresh_from_db()
        self.assertEqual(EventoPuerto.objects.filter(puerto=port).count(), 4)
        self.assertEqual(port.ultimo_cambio, self.t0 + timedelta(minutes=3))
        self.assertEqual(port.ultimo_activo, self.t0 + timedelta(minutes=2))
        with mock.patch('switches.health.timezone.now', return_value=self.t0 + timedelta(minutes=4)):
            level, reasons = self.health()
        self.assertEqual(level, 'warning')
        self.assertIn('1 puerto(s) inestables (≥ 4 cambios en 1 h)', [r['text'] for r in reasons])

    def test_old_events_are_pruned(self):
        poll(self.switch, self.t0, estado='up')
        EventoPuerto.objects.create(puerto=Puerto.objects.get(), estado='down', momento=self.t0 - timedelta(days=8))
        poll(self.switch, self.t0 + timedelta(minutes=1), estado='up')
        self.assertFalse(EventoPuerto.objects.exists())

    def test_neighbor_poe_and_hardware(self):
        hardware = [dict(tipo='fuente', nombre='PS1', estado='critical', valor=None),
                    dict(tipo='temperatura', nombre='Inlet', estado='warning', valor=58)]
        poll(self.switch, self.t0, dict(hardware=hardware, temperatura_c=58.0, poe_presupuesto_w=370.0, poe_consumo_w=350.0),
             vecino_nombre='SW-DIST', vecino_puerto='Te1/1/4', poe_estado='deliveringPower', poe_mw=6500)
        port = Puerto.objects.get()
        self.assertEqual((port.vecino_nombre, port.poe_mw), ('SW-DIST', 6500))
        level, reasons = self.health()
        texts = [r['text'] for r in reasons]
        self.assertEqual(level, 'critical')
        self.assertIn('Fuente de poder PS1 en falla', texts)
        self.assertIn('Sensor de temperatura Inlet con advertencia (58 °C)', texts)
        self.assertIn('PoE al 95% del presupuesto (350 de 370 W)', texts)
        # El equipo dejó de publicar esas MIB: no se muestran lecturas antiguas.
        poll(self.switch, self.t0 + timedelta(minutes=1), vecino_nombre=None)
        switch = Switch.objects.get(pk=self.switch.pk)
        self.assertEqual((switch.hardware, switch.poe_presupuesto_w), (None, None))
        self.assertIsNone(Puerto.objects.get().vecino_nombre)

    def test_uptime_unit_change_is_not_a_reboot(self):
        Switch.objects.filter(pk=self.switch.pk).update(uptime_segundos=345_116_883)
        poll(self.switch, self.t0, dict(uptime_segundos=3_451_229))
        self.assertIsNone(Switch.objects.get(pk=self.switch.pk).ultimo_reinicio)
        poll(self.switch, self.t0 + timedelta(minutes=1), dict(uptime_segundos=120))
        self.assertIsNotNone(Switch.objects.get(pk=self.switch.pk).ultimo_reinicio)

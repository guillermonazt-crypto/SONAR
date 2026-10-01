from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from planteles.models import Division, Plantel
from switches.models import MuestraOptica, Puerto, Switch, UmbralOptico
from switches.optics import assess_optic, predict_rx
from switches.services import record_poll

SFP = dict(interfaz='GigabitEthernet1/0/25', indice=10125, tx_dbm=-5.6, temp_c=25.6, estado='ok', sin_senal=False,
           oper='up', admin='up', umbrales={})


def poll(rx):
    return dict(cpu_5m=1, interfaces=[dict(indice=10125, nombre='GigabitEthernet1/0/25', estado='up')],
                transceptores=[dict(SFP, rx_dbm=rx)])


def series(now, start, slope, hours=48, step=4):
    """Muestras cada `step` h durante `hours` h que terminan en `now`, cayendo `slope` dB/día."""
    return [(now - timedelta(hours=h), start + slope * (hours - h) / 24) for h in range(hours, -1, -step)]


class PredictRxTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def test_linear_decline_eta(self):
        # -10 dBm hace 2 días, cae 2 dB/día: hoy -14 dBm, faltan 10 dB → 5 días.
        prediction = predict_rx(series(self.now, -10.0, -2.0), self.now)
        self.assertAlmostEqual(prediction['pendiente_db_dia'], -2.0, places=2)
        self.assertAlmostEqual(prediction['eta_dias'], 5.0, places=1)
        self.assertEqual(prediction['nivel'], 'warning')

    def test_fast_decline_is_critical(self):
        prediction = predict_rx(series(self.now, -15.0, -2.0), self.now)
        self.assertLess(prediction['eta_dias'], 3)
        self.assertEqual(prediction['nivel'], 'critical')

    def test_stable_or_rising_has_no_eta(self):
        for slope in (0.0, 0.5, -0.01):
            prediction = predict_rx(series(self.now, -8.0, slope), self.now)
            self.assertIsNone(prediction['eta_dias'])
            self.assertEqual(prediction['nivel'], 'ok')

    def test_already_below_target(self):
        prediction = predict_rx(series(self.now, -23.0, -1.0), self.now)
        self.assertEqual((prediction['eta_dias'], prediction['nivel']), (0.0, 'critical'))

    def test_needs_enough_history(self):
        self.assertIsNone(predict_rx(series(self.now, -8.0, -3.0, hours=8, step=1), self.now))
        self.assertIsNone(predict_rx(series(self.now, -8.0, -3.0, hours=48, step=12), self.now))

    def test_reason_in_optic_assessment(self):
        reading = dict(rx_dbm=-12.0, tx_dbm=-5.6, temperatura=25.0, estado='ok', sin_senal=False, admin='up',
                       oper='up', umbrales={}, rx_base_dbm=-12.0,
                       prediccion=predict_rx(series(self.now, -15.0, -2.0), self.now))
        level, reasons, per_metric = assess_optic(reading, UmbralOptico.actual())
        self.assertEqual((level, per_metric['rx']), ('critical', 'critical'))
        self.assertIn('dB/día', reasons[-1]['text'])


class OpticSamplingTests(TestCase):
    def setUp(self):
        self.t0 = timezone.now() - timedelta(days=2)
        plantel = Plantel.objects.create(nombre='Lab', division=Division.objects.create(nombre='Test'))
        self.switch = Switch.objects.create(nombre='SW', hostname='192.0.2.1', plantel=plantel)

    def poll(self, at, rx):
        with mock.patch('switches.services.timezone.now', return_value=at):
            record_poll(self.switch.pk, self.switch.hostname, poll(rx))

    def test_hourly_samples_and_prediction_endpoint(self):
        # Sondeo cada 30 min durante 2 días con RX cayendo 3 dB/día desde -9 dBm.
        for step in range(0, 97):
            at = self.t0 + timedelta(minutes=30 * step)
            self.poll(at, round(-9.0 - 3.0 * step / 48, 2))
        # Una muestra por hora, no por sondeo (el primer sondeo sólo crea el puerto).
        self.assertEqual(MuestraOptica.objects.count(), 48)
        port = Puerto.objects.get()
        prediction = port.optica['prediccion']
        self.assertAlmostEqual(prediction['pendiente_db_dia'], -3.0, places=1)
        # Hoy ~-15 dBm: faltan ~9 dB → ~3 días.
        self.assertAlmostEqual(prediction['eta_dias'], 3.0, delta=0.3)
        self.client.force_login(get_user_model().objects.create_user('lector', password='x'))
        data = self.client.get('/api/opticas/prediccion/').json()
        self.assertEqual(data['objetivo_dbm'], -24.0)
        item = data['predicciones'][0]
        self.assertEqual((item['interfaz'], item['switch']['nombre']), ('GigabitEthernet1/0/25', 'SW'))
        self.assertIn('eta_dias', item)
        self.assertEqual(self.client.get(f'/api/opticas/prediccion/?plantel={self.switch.plantel_id + 1}').json()['predicciones'], [])

    def test_no_light_is_not_sampled(self):
        self.poll(self.t0, -6.0)
        self.poll(self.t0 + timedelta(hours=2), -40.0)
        self.assertFalse(MuestraOptica.objects.exists())

    def test_endpoint_requires_session(self):
        self.assertEqual(self.client.get('/api/opticas/prediccion/').status_code, 403)

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from planteles.models import Division, Plantel
from switches.health import DEFAULTS, assess, summarize_sites
from switches.models import Switch
from switches.scoring import device_events, level, site_score
from switches.services import record_poll, record_synthetic


def reason(level_, tipo):
    return dict(level=level_, tipo=tipo, text='')


def device(motivos=(), **ports):
    return dict(activo=True, motivos=list(motivos), puertos=ports)


class ScoringTests(SimpleTestCase):
    def test_weights(self):
        self.assertEqual(device_events(device(con_errores=2, poe_falla=1, inestables=1))['puerto'], 4)
        self.assertEqual(device_events(device([reason('critical', 'snmp')]))['caido'], 1)
        self.assertEqual(device_events(device([reason('warning', 'latencia'), reason('warning', 'cpu')]))['lento'], 1)
        # Sin SNMP pero responde ping: lento, no caído.
        events = device_events(device([reason('warning', 'snmp')]))
        self.assertEqual((events['lento'], events['caido']), (1, 0))
        events = device_events(device([reason('critical', 'hardware'), reason('critical', 'optica')]))
        self.assertEqual(events['critico'], 1)

    def test_down_device_is_not_also_slow(self):
        events = device_events(device([reason('critical', 'snmp'), reason('warning', 'cpu')]))
        self.assertEqual((events['caido'], events['lento']), (1, 0))

    def test_thresholds(self):
        self.assertEqual([level(p) for p in (0, 4.5, 5, 15, 15.5)], ['ok', 'ok', 'warning', 'warning', 'critical'])

    def test_site_score(self):
        devices = [device([reason('critical', 'snmp')], con_errores=1),  # 3 + 0.5
                   device([reason('critical', 'hardware')]),              # 5
                   device([reason('warning', 'latencia')]),               # 1
                   dict(device([reason('critical', 'snmp')]), activo=False)]
        result = site_score(devices)
        self.assertEqual((result['puntaje'], result['estado']), (9.5, 'warning'))
        self.assertEqual(result['desglose'], dict(puerto=1, lento=1, caido=1, critico=1))
        self.assertEqual(site_score([])['estado'], 'none')

    def test_red_above_fifteen(self):
        devices = [device([reason('critical', 'hardware')]) for _ in range(3)] + [device(con_errores=2)]
        self.assertEqual(site_score(devices)['estado'], 'critical')  # 15 + 1


class SyntheticHealthTests(TestCase):
    def setUp(self):
        cache.clear()
        division = Division.objects.create(nombre='Escuelas')
        self.apan = Plantel.objects.create(nombre='Apan', division=division)
        self.switch = Switch.objects.create(nombre='SW-1', hostname='192.0.2.1', plantel=self.apan, rol='core')
        record_poll(self.switch.pk, self.switch.hostname, dict(cpu_5m=10, interfaces=[]))

    def assess_now(self):
        self.switch.refresh_from_db()
        return assess(self.switch, {}, DEFAULTS, timezone.now())

    def test_record_synthetic_saves_latest(self):
        record_synthetic([(self.switch.pk, dict(rtt_avg_ms=12.5, jitter_ms=1.2, perdida_pct=0.0))])
        self.switch.refresh_from_db()
        self.assertEqual((self.switch.latencia_ms, self.switch.jitter_ms, self.switch.perdida_pct), (12.5, 1.2, 0.0))
        self.assertIsNotNone(self.switch.sintetico_en)

    def test_high_latency_and_loss_are_warnings(self):
        record_synthetic([(self.switch.pk, dict(rtt_avg_ms=250, jitter_ms=30, perdida_pct=40))])
        state, reasons = self.assess_now()
        self.assertEqual(state, 'warning')
        self.assertEqual([r['tipo'] for r in reasons], ['latencia', 'latencia'])

    def test_good_stale_or_total_loss_measurements_add_nothing(self):
        record_synthetic([(self.switch.pk, dict(rtt_avg_ms=3, jitter_ms=0.2, perdida_pct=0))])
        self.assertEqual(self.assess_now(), ('ok', []))
        # 100%: lo resuelve la validación SNMP + ping.
        record_synthetic([(self.switch.pk, dict(rtt_avg_ms=None, jitter_ms=None, perdida_pct=100))])
        self.assertEqual(self.assess_now()[0], 'ok')
        record_synthetic([(self.switch.pk, dict(rtt_avg_ms=500, jitter_ms=1, perdida_pct=0))],
                         now=timezone.now() - timedelta(hours=2))
        self.assertEqual(self.assess_now()[0], 'ok')

    def test_summary_carries_weighted_state_and_latency(self):
        record_synthetic([(self.switch.pk, dict(rtt_avg_ms=250, jitter_ms=3, perdida_pct=0))])
        reader = get_user_model().objects.create_user(username='reader', password='test-password', rol='lector')
        self.client.force_login(reader)
        (site,) = [s for s in self.client.get('/api/resumen/').json()['planteles'] if s['nombre'] == 'Apan']
        # Un equipo lento suma 1: el peor equipo está en atención pero el semáforo ponderado sigue verde.
        self.assertEqual((site['estado'], site['estado_ponderado'], site['puntaje']), ('warning', 'ok', 1.0))
        self.assertEqual((site['latencia_ms'], site['perdida_pct']), (250.0, 0.0))
        self.assertEqual(site['desglose']['lento'], 1)

    def test_summarize_sites_without_devices(self):
        (site,) = summarize_sites([self.apan], [])
        self.assertEqual((site['estado_ponderado'], site['puntaje'], site['latencia_ms']), ('none', 0, None))

    def test_synthetic_history_endpoint(self):
        record_synthetic([(self.switch.pk, dict(rtt_avg_ms=5, jitter_ms=1, perdida_pct=0))])
        reader = get_user_model().objects.create_user(username='reader', password='test-password', rol='lector')
        self.client.force_login(reader)
        points = [dict(time='2026-10-06T10:00:00+00:00', rtt_avg_ms=5.0, rtt_max_ms=7.0, jitter_ms=1.0, perdida_pct=0.0)]
        with patch('api.history.synthetic_history', return_value=points) as query:
            data = self.client.get(f'/api/switches/{self.switch.pk}/sintetico/?horas=999').json()
        query.assert_called_once_with('SW-1', hours=168, every='1h')
        self.assertEqual((data['points'], data['ultima']['latencia_ms']), (points, 5.0))
        with patch('api.history.synthetic_history', side_effect=OSError('down')):
            data = self.client.get(f'/api/switches/{self.switch.pk}/sintetico/').json()
        self.assertEqual(data['points'], [])
        self.assertIn('no disponible', data['detail'])
        self.assertEqual(self.client.get('/api/switches/999/sintetico/').status_code, 404)

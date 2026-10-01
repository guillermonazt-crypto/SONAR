"""SONAR no está encendido 24/7: apagarlo y volver a abrirlo no debe inventar fallas."""
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from planteles.models import Division, Plantel
from . import alerts
from .health import port_stats
from .models import Alerta, EstadoMonitoreo, EventoPuerto, Puerto, Switch
from .services import UPTIME_WRAP_SECONDS, detect_reboot, mark_worker_started, record_poll

HOUR = 3600
PORT = dict(indice=1, nombre='GigabitEthernet1/0/1', estado='up', errores_entrada=0, errores_salida=0, errores_crc=0,
            octetos_entrada=0, octetos_salida=0, velocidad_mbps=1000)


class DetectRebootTests(TestCase):
    def test_pause_without_reboot(self):
        # Ocho horas apagado: el uptime avanzó lo mismo que el reloj.
        self.assertFalse(detect_reboot(10 * HOUR, 18 * HOUR + 30, 8 * HOUR))
        self.assertFalse(detect_reboot(10 * HOUR, 10 * HOUR + 60, 60))

    def test_reboot_during_pause_even_if_uptime_grew(self):
        # Apagado 3 días; el switch reinició hace 1 día (uptime 1 d > anterior 2 h).
        self.assertTrue(detect_reboot(2 * HOUR, 24 * HOUR, 72 * HOUR))

    def test_reboot_between_polls(self):
        self.assertTrue(detect_reboot(10 * HOUR, 45, 60))

    def test_sysuptime_wrap_is_not_a_reboot(self):
        self.assertFalse(detect_reboot(UPTIME_WRAP_SECONDS - 30, 30, 60))

    def test_legacy_units_and_missing_values(self):
        self.assertFalse(detect_reboot(345_116_883, 3_451_229, 60))
        self.assertFalse(detect_reboot(None, 10, 60))
        self.assertFalse(detect_reboot(10, None, 60))
        self.assertTrue(detect_reboot(240 * HOUR, 30, None))

    def test_clock_drift_on_long_pause(self):
        # Una semana apagado con 5 min de deriva entre relojes no es reinicio.
        week = 7 * 24 * HOUR
        self.assertFalse(detect_reboot(HOUR, HOUR + week - 300, week))


class PauseResumeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.t0 = timezone.now() - timedelta(days=2)
        plantel = Plantel.objects.create(nombre='Lab', division=Division.objects.create(nombre='Test'))
        self.switch = Switch.objects.create(nombre='SW', hostname='192.0.2.1', plantel=plantel)

    def poll(self, at, datos=None, **port):
        """Sondeo en `at`; datos=False simula que el switch no respondió."""
        payload = None if datos is False else dict(dict(interfaces=[dict(PORT, **port)]), **(datos or {}))
        with mock.patch('switches.services.timezone.now', return_value=at):
            record_poll(self.switch.pk, self.switch.hostname, payload)
        self.switch.refresh_from_db()
        return Puerto.objects.first()

    def test_errors_accumulated_while_off_are_not_new(self):
        self.poll(self.t0, errores_entrada=100)
        port = self.poll(self.t0 + timedelta(minutes=1), errores_entrada=100)
        self.assertEqual(port.errores_nuevos, 0)
        # SONAR apagado 8 h: los contadores siguieron sumando.
        resumed = self.t0 + timedelta(hours=8)
        port = self.poll(resumed, errores_entrada=5000, octetos_entrada=10**12, octetos_salida=10**12)
        self.assertIsNone(port.errores_nuevos)
        self.assertIsNone(port.ultimo_error)
        self.assertIsNone(port.bps_entrada)
        self.assertEqual(port_stats([self.switch.pk], resumed)[self.switch.pk]['con_errores'], 0)
        # El siguiente sondeo vuelve a medir normal.
        port = self.poll(resumed + timedelta(minutes=1), errores_entrada=5003,
                         octetos_entrada=10**12 + 7_500_000, octetos_salida=10**12)
        self.assertEqual(port.errores_nuevos, 3)
        self.assertEqual(port.bps_entrada, 1_000_000)

    def test_reboot_time_is_when_it_booted(self):
        self.poll(self.t0, dict(uptime_segundos=2 * HOUR))
        # Tras 8 h sin SONAR el uptime de 10 h es lo esperado: no hubo reinicio.
        later = self.t0 + timedelta(hours=8)
        self.poll(later, dict(uptime_segundos=10 * HOUR))
        self.assertIsNone(self.switch.ultimo_reinicio)
        # Uptime de 30 min: arrancó hace 30 min, no "cuando SONAR lo notó".
        at = later + timedelta(minutes=1)
        self.poll(at, dict(uptime_segundos=1800))
        self.assertEqual(self.switch.ultimo_reinicio, at - timedelta(seconds=1800))

    def test_pause_without_reboot_is_not_flagged(self):
        self.poll(self.t0, dict(uptime_segundos=5 * HOUR))
        self.poll(self.t0 + timedelta(hours=12), dict(uptime_segundos=17 * HOUR + 20))
        self.assertIsNone(self.switch.ultimo_reinicio)

    def test_link_change_after_failed_poll_uses_iflastchange(self):
        self.poll(self.t0)
        self.poll(self.t0 + timedelta(minutes=1), False)
        self.assertEqual(Puerto.objects.get().estado_operativo, 'unknown')
        at = self.t0 + timedelta(minutes=30)
        port = self.poll(at, estado='down', ultimo_cambio_hace_s=600)
        self.assertEqual(port.ultimo_cambio, at - timedelta(seconds=600))
        # unknown → down no es un cambio observado: no suma a puertos inestables.
        self.assertFalse(EventoPuerto.objects.exists())

    def test_startup_keeps_previous_episode_without_noise(self):
        # Antes de apagar SONAR el switch estaba caído y se avisó.
        self.poll(self.t0)
        self.poll(self.t0 + timedelta(minutes=1), False)
        self.assertIn('en riesgo', alerts.evaluate(self.switch.pk, self.t0 + timedelta(minutes=1)))
        # Se reabre 2 días después: durante la gracia no se cierra ni se re-notifica.
        start = self.t0 + timedelta(days=2)
        mark_worker_started(start)
        self.poll(start + timedelta(seconds=20), False)
        self.assertIsNone(alerts.evaluate(self.switch.pk, start + timedelta(seconds=20)))
        self.assertIsNone(Alerta.objects.get().fin)
        # Sigue caído al terminar la gracia: mismo episodio, sin aviso ni escalamiento inmediato.
        after = start + timedelta(minutes=3)
        self.poll(after, False)
        self.assertIsNone(alerts.evaluate(self.switch.pk, after))
        self.assertEqual(Alerta.objects.count(), 1)
        self.assertIsNone(Alerta.objects.get().escalada_en)
        # El escalamiento cuenta desde el arranque (acceso: 60 min), no desde hace 2 días.
        late = start + timedelta(minutes=61)
        self.poll(late, False)
        self.assertTrue(alerts.evaluate(self.switch.pk, late).escalamiento)

    def test_recovery_after_restart_closes_episode(self):
        self.poll(self.t0)
        self.poll(self.t0 + timedelta(minutes=1), False)
        alerts.evaluate(self.switch.pk, self.t0 + timedelta(minutes=1))
        start = self.t0 + timedelta(days=1)
        mark_worker_started(start)
        self.poll(start + timedelta(seconds=30))
        self.assertTrue(alerts.evaluate(self.switch.pk, start + timedelta(seconds=30)).startswith('🟢'))
        self.assertIsNotNone(Alerta.objects.get().fin)

    def test_worker_restart_invalidates_cached_summary(self):
        from django.contrib.auth import get_user_model
        self.client.force_login(get_user_model().objects.create_user('lector', password='x'))
        now = timezone.now()
        Switch.objects.filter(pk=self.switch.pk).update(lectura_correcta=False,
                                                        ultima_consulta=now - timedelta(minutes=9))
        mark_worker_started(now - timedelta(hours=1))
        self.assertEqual(self.client.get('/api/resumen/').json()['switches'][0]['conexion'], 'inactivo')
        mark_worker_started(now)
        self.assertEqual(self.client.get('/api/resumen/').json()['switches'][0]['conexion'], 'iniciando')
        self.assertEqual(EstadoMonitoreo.objects.count(), 1)

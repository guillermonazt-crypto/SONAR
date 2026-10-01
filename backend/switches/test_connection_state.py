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


class ConnectionStateTests(TestCase):
    """Activo / iniciando / inactivo: un reinicio del worker no marca caídos los switches."""

    def setUp(self):
        self.t0 = timezone.now()
        plantel = Plantel.objects.create(nombre='Lab', division=Division.objects.create(nombre='Test'))
        # Último sondeo exitoso hace 10 min: el worker estuvo detenido.
        self.switch = Switch.objects.create(nombre='SW', hostname='192.0.2.1', plantel=plantel, lectura_correcta=True,
                                            ultima_consulta=self.t0 - timedelta(minutes=10),
                                            ultima_lectura_exitosa=self.t0 - timedelta(minutes=10))

    def poll(self, at, datos):
        with mock.patch('switches.services.timezone.now', return_value=at):
            record_poll(self.switch.pk, self.switch.hostname, datos)
        self.switch.refresh_from_db()

    def state(self, at):
        return connection_state(self.switch, EstadoMonitoreo.actual().iniciado, at)[0]

    def level(self, at):
        switch = Switch.objects.get(pk=self.switch.pk)
        return assess(switch, port_stats([switch.pk], at)[switch.pk], thresholds_by_role()[switch.rol], at,
                      started=EstadoMonitoreo.actual().iniciado)

    def test_startup_grace_even_if_polls_fail(self):
        mark_worker_started(self.t0)
        self.assertEqual(self.state(self.t0), 'iniciando')
        self.poll(self.t0 + timedelta(seconds=30), None)
        at = self.t0 + timedelta(seconds=90)
        self.assertEqual(self.state(at), 'iniciando')
        level, reasons = self.level(at)
        self.assertEqual(level, 'warning')
        self.assertEqual(reasons[0]['tipo'], 'iniciando')
        # Sin rojo durante la gracia: no se abre alerta ni se notifica.
        self.assertIsNone(evaluate(self.switch.pk, at))
        self.assertFalse(Alerta.objects.exists())

    def test_grace_hides_stale_composite_risk(self):
        for index in range(1, 4):
            Puerto.objects.create(switch=self.switch, nombre=f'Gi1/0/{index}', indice=index, ultimo_error=self.t0)
        mark_worker_started(self.t0)
        self.assertEqual(self.level(self.t0 + timedelta(seconds=30))[0], 'warning')

    def test_successful_poll_is_always_active(self):
        mark_worker_started(self.t0)
        self.poll(self.t0 + timedelta(seconds=10), DATA)
        self.assertEqual(self.switch.ultima_lectura_exitosa, self.t0 + timedelta(seconds=10))
        self.assertEqual(self.state(self.t0 + timedelta(seconds=20)), 'activo')
        self.assertEqual(self.level(self.t0 + timedelta(seconds=20))[0], 'ok')
        # Mucho después del arranque, un sondeo exitoso reciente sigue en activo.
        self.poll(self.t0 + timedelta(hours=3), DATA)
        self.assertEqual(self.state(self.t0 + timedelta(hours=3, minutes=1)), 'activo')

    def test_failed_poll_keeps_last_success(self):
        self.poll(self.t0, DATA)
        self.poll(self.t0 + timedelta(minutes=1), None)
        self.assertEqual(self.switch.ultima_lectura_exitosa, self.t0)
        self.assertFalse(self.switch.lectura_correcta)

    def test_inactive_after_grace(self):
        mark_worker_started(self.t0)
        self.poll(self.t0 + timedelta(seconds=30), None)
        at = self.t0 + timedelta(minutes=2, seconds=5)
        self.assertEqual(self.state(at), 'inactivo')
        self.assertEqual(self.level(at)[0], 'critical')
        self.assertIn('SW', evaluate(self.switch.pk, at))

    def test_pause_without_worker_restart_is_inactive(self):
        # Worker arrancado hace tiempo y sin lecturas exitosas en más de 5 min.
        mark_worker_started(self.t0 - timedelta(hours=1))
        state, reason = connection_state(self.switch, EstadoMonitoreo.actual().iniciado, self.t0)
        self.assertEqual(state, 'inactivo')
        self.assertEqual(reason['text'], 'Sin lectura exitosa desde hace 10 min')

    def test_never_polled_is_starting(self):
        self.switch.ultima_consulta = self.switch.ultima_lectura_exitosa = self.switch.lectura_correcta = None
        self.assertEqual(connection_state(self.switch, None, self.t0)[0], 'iniciando')

    def test_summary_reports_connection(self):
        from django.contrib.auth import get_user_model
        mark_worker_started(self.t0)
        user = get_user_model().objects.create_user('lector', password='x')
        self.client.force_login(user)
        data = self.client.get('/api/resumen/?refresh=1').json()
        self.assertTrue(data['monitoreo']['iniciando'])
        self.assertFalse(data['worker_atrasado'])
        self.assertEqual(data['switches'][0]['conexion'], 'iniciando')
        site = next(site for site in data['planteles'] if site['nombre'] == 'Lab')
        self.assertEqual((site['iniciando'], site['sin_respuesta'], site['estado']), (1, 0, 'warning'))

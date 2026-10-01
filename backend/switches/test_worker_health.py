from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from .health import worker_offline
from .models import EstadoMonitoreo
from .services import mark_worker_started, worker_heartbeat


class WorkerHealthTests(TestCase):
    """Latido del worker cada 30 s: sin latido en 5 min la UI muestra "datos congelados"."""

    def setUp(self):
        cache.clear()
        self.now = timezone.now()
        self.client.force_login(get_user_model().objects.create_user('lector', password='x'))

    def status(self, at):
        with mock.patch('api.views.timezone.now', return_value=at):
            return self.client.get('/api/monitoreo/').json()

    def test_offline_after_five_minutes_without_heartbeat(self):
        mark_worker_started(self.now)
        worker_heartbeat(self.now + timedelta(seconds=30))
        self.assertFalse(self.status(self.now + timedelta(minutes=5))['worker_offline'])
        self.assertTrue(self.status(self.now + timedelta(minutes=5, seconds=31))['worker_offline'])

    def test_never_started_is_offline(self):
        self.assertTrue(worker_offline(EstadoMonitoreo.actual(), self.now))
        self.assertTrue(self.status(self.now)['worker_offline'])

    def test_heartbeat_reports_influx_queue(self):
        worker_heartbeat(self.now, influx=dict(disponible=False, en_cola=250))
        data = self.status(self.now)
        self.assertEqual(data['influx'], dict(disponible=False, en_cola=250))
        # Un latido sin datos de InfluxDB no borra el último estado conocido.
        worker_heartbeat(self.now + timedelta(seconds=30))
        self.assertEqual(EstadoMonitoreo.actual().influx_en_cola, 250)

    def test_summary_includes_worker_state(self):
        worker_heartbeat(self.now - timedelta(minutes=10))
        self.assertTrue(self.client.get('/api/resumen/?refresh=1').json()['monitoreo']['worker_offline'])

    def test_requires_session(self):
        self.client.logout()
        self.assertEqual(self.client.get('/api/monitoreo/').status_code, 403)

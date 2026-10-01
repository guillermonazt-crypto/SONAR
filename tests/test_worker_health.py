import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sonar import main as worker
from sonar.database.influx_writer import InfluxWriter

DATA = dict(nombre="sw", rol="access", sitio="lab", cpu_5s=1, cpu_1m=2, cpu_5m=3, interfaces=[])


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def writer(clock, queue_max=100):
    with patch("sonar.database.influx_writer.InfluxDBClient"):
        return InfluxWriter(clock=clock, queue_max=queue_max, retry_seconds=30)


class InfluxQueueTests(unittest.TestCase):
    def test_outage_queues_and_flushes_in_order(self):
        clock = Clock()
        w = writer(clock)
        w.write_api.write.side_effect = OSError("influx caído")
        w.escribir_cpu(DATA)
        self.assertEqual(w.estado(), dict(disponible=False, en_cola=1))
        # Dentro de la ventana de reintento ni siquiera se intenta: el ciclo no espera a InfluxDB.
        w.write_api.write.reset_mock()
        w.escribir_cpu(dict(DATA, cpu_5m=4))
        w.write_api.write.assert_not_called()
        self.assertEqual(w.estado()["en_cola"], 2)
        # Vuelve InfluxDB: primero la cola (en orden), luego lo nuevo.
        w.write_api.write.side_effect = None
        clock.now = 31
        w.escribir_cpu(dict(DATA, cpu_5m=5))
        backlog, latest = w.write_api.write.call_args_list
        self.assertEqual(len(backlog.kwargs["record"]), 2)
        self.assertIn("cpu_5m=3i", backlog.kwargs["record"][0])
        self.assertIn("cpu_5m=5i", latest.kwargs["record"].to_line_protocol())
        self.assertEqual(w.estado(), dict(disponible=True, en_cola=0))

    def test_queue_is_bounded(self):
        clock = Clock()
        w = writer(clock, queue_max=3)
        w.write_api.write.side_effect = OSError("influx caído")
        for value in range(10):
            w.escribir_cpu(dict(DATA, cpu_5m=value))
        queued = list(w._queue)
        self.assertEqual(len(queued), 3)
        # Al llenarse se descartan las métricas más antiguas.
        self.assertIn("cpu_5m=9i", queued[-1])

    def test_failed_retry_keeps_backlog(self):
        clock = Clock()
        w = writer(clock)
        w.write_api.write.side_effect = OSError("influx caído")
        w.escribir_cpu(DATA)
        clock.now = 31
        w.escribir_cpu(dict(DATA, cpu_5m=7))
        self.assertEqual(w.estado(), dict(disponible=False, en_cola=2))


class HeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_every_interval_with_influx_state(self):
        w = Mock()
        w.estado.return_value = dict(disponible=False, en_cola=5)
        with patch.object(worker, "worker_heartbeat") as beat, \
                patch.object(worker.asyncio, "sleep", AsyncMock(side_effect=[None, None, asyncio.CancelledError])) as sleep:
            with self.assertRaises(asyncio.CancelledError):
                await worker._latidos(w)
        self.assertEqual(beat.call_count, 3)
        beat.assert_called_with(dict(disponible=False, en_cola=5))
        sleep.assert_awaited_with(worker.HEARTBEAT_SECONDS)
        self.assertEqual(worker.HEARTBEAT_SECONDS, 30)

    async def test_poll_succeeds_while_influx_is_down(self):
        clock = Clock()
        w = writer(clock)
        w.write_api.write.side_effect = OSError("influx caído")
        with patch.object(worker, "obtener_datos_reales", AsyncMock(return_value=dict(DATA, transceptores=[]))):
            self.assertTrue(await worker.procesar_switch(dict(hostname="192.0.2.1", name="sw"), w))
        self.assertGreater(w.estado()["en_cola"], 0)

import unittest
from unittest.mock import AsyncMock, Mock, patch

from sonar import synthetic
from sonar import main as worker

WINDOWS_ES = """
Haciendo ping a 10.0.0.1 con 32 bytes de datos:
Respuesta desde 10.0.0.1: bytes=32 tiempo=4ms TTL=255
Respuesta desde 10.0.0.1: bytes=32 tiempo<1m TTL=255
Tiempo de espera agotado para esta solicitud.
Respuesta desde 10.0.0.1: bytes=32 tiempo=8ms TTL=255
Respuesta desde 10.0.0.9: Host de destino inaccesible.
"""
LINUX = """PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.
64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=0.500 ms
64 bytes from 10.0.0.1: icmp_seq=2 ttl=64 time=1.500 ms
--- 10.0.0.1 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss, time 1001ms
"""
CONFIG = dict(enabled=True, interval_minutes=5, roles=['core', 'access'], count=5, concurrency=4)


class ParseTests(unittest.TestCase):
    def test_windows_spanish_counts_only_ttl_replies(self):
        result = synthetic.parse_ping(WINDOWS_ES, 5)
        self.assertEqual((result['recibidos'], result['perdida_pct'], result['alcanzable']), (3, 40.0, True))
        # "<1m" cuenta como 0.5 ms.
        self.assertEqual((result['rtt_min_ms'], result['rtt_max_ms'], result['rtt_avg_ms']), (0.5, 8.0, 4.17))
        self.assertEqual(result['jitter_ms'], 5.5)

    def test_linux(self):
        result = synthetic.parse_ping(LINUX, 2)
        self.assertEqual((result['perdida_pct'], result['rtt_avg_ms'], result['jitter_ms']), (0.0, 1.0, 1.0))

    def test_no_reply_is_total_loss(self):
        result = synthetic.parse_ping('Tiempo de espera agotado para esta solicitud.', 5)
        self.assertEqual((result['alcanzable'], result['perdida_pct'], result['rtt_avg_ms']), (False, 100.0, None))


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_configured_roles_are_probed(self):
        inventory = [dict(hostname='10.0.0.1', role='core'), dict(hostname='10.0.0.2', role='distribution'),
                     dict(hostname='10.0.0.3', role='access')]
        prober = AsyncMock(return_value=synthetic.parse_ping(LINUX, 2))
        results = await synthetic.run(inventory, prober, CONFIG)
        self.assertEqual([r['dispositivo']['hostname'] for r in results], ['10.0.0.1', '10.0.0.3'])
        prober.assert_awaited_with('10.0.0.3', 5)

    async def test_failed_probe_is_skipped(self):
        prober = AsyncMock(side_effect=[None, RuntimeError('x')])
        inventory = [dict(hostname='10.0.0.1', role='core'), dict(hostname='10.0.0.2', role='core')]
        self.assertEqual(await synthetic.run(inventory, prober, CONFIG), [])

    async def test_scheduler_runs_once_per_interval_and_stores(self):
        now = [0.0]
        scheduler = synthetic.Scheduler(clock=lambda: now[0])
        writer, store = Mock(), Mock()
        prober = AsyncMock(return_value=synthetic.parse_ping(LINUX, 2))
        inventory = [dict(hostname='10.0.0.1', role='core', django_id=1)]
        self.assertEqual(len(await scheduler.maybe_run(inventory, writer, store, prober, CONFIG)), 1)
        now[0] = 200
        self.assertIsNone(await scheduler.maybe_run(inventory, writer, store, prober, CONFIG))
        now[0] = 301
        await scheduler.maybe_run(inventory, writer, store, prober, CONFIG)
        self.assertEqual((writer.escribir_sintetico.call_count, store.call_count), (2, 2))

    async def test_influx_failure_still_stores_in_django(self):
        writer, store = Mock(), Mock()
        writer.escribir_sintetico.side_effect = OSError('influx down')
        prober = AsyncMock(return_value=synthetic.parse_ping(LINUX, 2))
        await synthetic.Scheduler().maybe_run([dict(hostname='10.0.0.1', role='core')], writer, store, prober, CONFIG)
        store.assert_called_once()

    async def test_disabled(self):
        prober = AsyncMock()
        config = dict(CONFIG, enabled=False)
        self.assertIsNone(await synthetic.Scheduler().maybe_run([], Mock(), Mock(), prober, config))
        prober.assert_not_awaited()

    def test_ping_command_uses_count(self):
        from sonar.collector import icmp
        self.assertEqual(icmp.ping_command('10.0.0.1', windows=True, count=5)[:3], ['ping', '-n', '5'])


class WriterTests(unittest.TestCase):
    def test_writes_one_point_per_device(self):
        from sonar.database.influx_writer import InfluxWriter
        writer = InfluxWriter.__new__(InfluxWriter)
        writer._write = Mock()
        result = synthetic.parse_ping(LINUX, 2)
        writer.escribir_sintetico([dict(dispositivo=dict(hostname='10.0.0.1', name='SW-1', role='core', site='Apan'),
                                        resultado=result)])
        (points,), _ = writer._write.call_args
        line = points[0].to_line_protocol()
        self.assertIn('sintetico,device=SW-1,role=core,site=Apan,target=10.0.0.1', line)
        self.assertIn('rtt_avg_ms=1', line)
        self.assertIn('alcanzable=1i', line)

import asyncio
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from sonar.collector import snmp_collector as snmp
from sonar.database.influx_writer import InfluxWriter
from sonar.utils import config
from sonar import main as worker

DEVICE = dict(hostname="192.0.2.1", name="test")
DATA = dict(nombre="test", rol="access", sitio="lab", cpu_5s=0,
            cpu_1m=None, cpu_5m=None, interfaces=[], transceptores=[])

class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_cpu_unknown_and_zero(self):
        with patch.object(snmp, "_get_oid", AsyncMock(side_effect=[None, "No Such Object", "0"])):
            cpu = await snmp.obtener_cpu(DEVICE)
        self.assertEqual(cpu, dict(cpu_5m=None, cpu_1m=None, cpu_5s=0))

    async def test_missing_interface_readings(self):
        with patch.object(snmp, "_walk_oid", AsyncMock(side_effect=[{"1":"GigabitEthernet1/0/1"}, {"1":"6"}, {}, {"1":"0"}, {}, {}, {}, {}, {}])):
            result = (await snmp.obtener_interfaces(DEVICE))[0]
        self.assertEqual(result["estado"], "unknown")
        self.assertEqual(result["errores_entrada"], 0)
        self.assertIsNone(result["errores_salida"])
        self.assertIsNone(result["errores_crc"])

    async def test_write_does_not_block_event_loop(self):
        entered, release = threading.Event(), threading.Event()
        writer = Mock()
        def write(data):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("event loop blocked")
        writer.escribir_cpu.side_effect = write
        with patch.object(worker, "obtener_datos_reales", AsyncMock(return_value=DATA)):
            task = asyncio.create_task(worker.procesar_switch(DEVICE, writer))
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(.005)
            self.assertTrue(entered.is_set())
            release.set()
            self.assertTrue(await task)

    async def test_influx_down_is_not_a_failed_poll(self):
        # El sondeo SNMP salió bien: sin InfluxDB sólo falta el histórico y se avisa una vez.
        writer = Mock()
        writer.escribir_cpu.side_effect = OSError("offline")
        with patch.object(worker, "obtener_datos_reales", AsyncMock(return_value=DATA)),                 patch.object(worker, "_influx_disponible", True), patch.object(worker.log, "warning") as warning:
            self.assertTrue(await worker.procesar_switch(DEVICE, writer))
            self.assertTrue(await worker.procesar_switch(DEVICE, writer))
            self.assertEqual(warning.call_count, 1)
            writer.escribir_cpu.side_effect = None
            self.assertTrue(await worker.procesar_switch(DEVICE, writer))
            self.assertTrue(worker._influx_disponible)

    async def test_failed_snmp_poll_is_reported(self):
        with patch.object(worker, "obtener_datos_reales", AsyncMock(return_value=None)):
            self.assertFalse(await worker.procesar_switch(DEVICE, Mock()))

    async def test_inventory_reloaded_and_writer_closed(self):
        writer = Mock()
        with patch.object(worker, "validate_snmp"), patch.object(worker, "InfluxWriter", return_value=writer), patch.object(worker, "load_inventory", side_effect=[[DEVICE], []]) as load, patch.object(worker, "ejecutar_ciclo", AsyncMock()) as cycle, patch.object(worker.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])),                 patch.object(worker, "mark_worker_started") as started, patch.object(worker, "worker_heartbeat") as beat:
            with self.assertRaises(asyncio.CancelledError):
                await worker.main()
        # Arranque registrado una vez (abre la gracia) y un latido por ciclo completo.
        started.assert_called_once()
        self.assertEqual(beat.call_count, 2)
        self.assertEqual(load.call_count, 2)
        self.assertEqual(cycle.await_args_list[1].args[0], [])
        writer.cerrar.assert_called_once()

class ConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_cycle_respects_concurrency_limit(self):
        running = peak = 0
        async def fake(device, writer):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(.01)
            running -= 1
            return True
        with patch.object(worker, "procesar_switch", fake), patch.object(worker, "SNMP_CONCURRENCY", 2):
            await worker.ejecutar_ciclo([DEVICE] * 6, Mock())
        self.assertEqual(peak, 2)


class WriterTests(unittest.TestCase):
    def test_line_protocol_omits_unknown_preserves_zero(self):
        with patch("sonar.database.influx_writer.InfluxDBClient"):
            writer = InfluxWriter()
        writer.escribir_cpu(DATA)
        line = writer.write_api.write.call_args.kwargs["record"].to_line_protocol()
        self.assertIn("cpu_5s=0i", line)
        self.assertNotIn("cpu_1m=", line)
        writer.write_api.write.reset_mock()
        writer.escribir_cpu(dict(DATA, cpu_5s=None))
        writer.write_api.write.assert_not_called()
        interface = dict(nombre="Gi1", estado="unknown", errores_entrada=0, errores_salida=None, errores_crc=None)
        writer.escribir_interfaces(dict(DATA, interfaces=[interface, dict(interface, nombre="Gi2")]))
        records = writer.write_api.write.call_args.kwargs["record"]
        self.assertEqual(len(records), 2)
        line = records[0].to_line_protocol()
        self.assertNotIn("status=", line)
        self.assertIn('estado="unknown"', line)
        self.assertIn("errores_entrada=0i", line)
        self.assertNotIn("errores_crc=", line)

    def test_snmp_config_requires_credentials(self):
        with patch.object(config, "SNMP_VERSION", "2c"), patch.object(config, "SNMP_COMMUNITY", ""):
            with self.assertRaises(ValueError):
                config.validate_snmp()
        with patch.object(config, "SNMP_VERSION", "3"), patch.object(config, "SNMP_V3_USER", "sonar"), \
                patch.object(config, "SNMP_V3_AUTH_KEY", "clave-auth-1"), patch.object(config, "SNMP_V3_PRIV_KEY", "clave-priv-1"):
            config.validate_snmp()
            self.assertEqual(type(snmp._auth("x")).__name__, "UsmUserData")

    def test_empty_yaml(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "inventory").mkdir()
            (root / "inventory/devices.yaml").write_text("")
            with patch.object(config, "ROOT", root), patch.dict(os.environ, INVENTORY_SOURCE="yaml"):
                self.assertEqual(config.load_inventory(), [])

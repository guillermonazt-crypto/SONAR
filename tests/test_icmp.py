import unittest
from unittest.mock import AsyncMock, Mock, patch

from sonar.collector import icmp
from sonar import main as worker

DATA = dict(nombre="test", rol="access", sitio="lab", cpu_5s=0, cpu_1m=0, cpu_5m=0, interfaces=[])


class PingTests(unittest.IsolatedAsyncioTestCase):
    def test_command_per_platform(self):
        self.assertEqual(icmp.ping_command("10.0.0.1", windows=True)[:2], ["ping", "-n"])
        self.assertEqual(icmp.ping_command("10.0.0.1", windows=False)[:2], ["ping", "-c"])

    def test_windows_unreachable_is_failure(self):
        self.assertTrue(icmp.ping_succeeded(0, "Respuesta desde 10.0.0.1: bytes=32 tiempo<1m TTL=255"))
        self.assertFalse(icmp.ping_succeeded(0, "Respuesta desde 10.0.0.9: Host de destino inaccesible."))
        self.assertFalse(icmp.ping_succeeded(1, "Tiempo de espera agotado para esta solicitud."))

    async def test_missing_ping_binary_is_unknown(self):
        with patch.object(icmp.asyncio, "create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError("ping"))):
            self.assertIsNone(await icmp.ping("10.0.0.1"))

    async def test_failed_snmp_triggers_ping(self):
        device = dict(hostname="192.0.2.1", name="test", django_id=1)
        with patch.object(worker, "obtener_datos_reales", AsyncMock(return_value=None)), \
                patch.object(worker, "ping", AsyncMock(return_value=True)) as ping, \
                patch.object(worker, "record_poll") as record, patch.object(worker, "notify_alerts"):
            self.assertFalse(await worker.procesar_switch(device, Mock()))
        ping.assert_awaited_once_with("192.0.2.1")
        self.assertEqual(record.call_args.args[2], dict(icmp=True))

    async def test_successful_snmp_skips_ping(self):
        device = dict(hostname="192.0.2.1", name="test", django_id=1)
        with patch.object(worker, "obtener_datos_reales", AsyncMock(return_value=DATA)), \
                patch.object(worker, "ping", AsyncMock()) as ping, \
                patch.object(worker, "record_poll") as record, patch.object(worker, "notify_alerts"):
            self.assertTrue(await worker.procesar_switch(device, Mock()))
        ping.assert_not_awaited()
        self.assertIsNone(record.call_args.args[2])

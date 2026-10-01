"""Pruebas offline del descubrimiento con la red del simulador SNMP (sin tocar la red real)."""
import os
import unittest
from unittest.mock import patch

from scripts.snmp_simulator import sondeo_simulado
from sonar import discovery


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_sweep_finds_simulated_devices_and_skips_known(self):
        found = await discovery.sweep(['192.0.2.0/27'], sondeo_simulado, known={'192.0.2.10'})
        self.assertEqual({item['ip']: item['nombre'] for item in found},
                         {'192.0.2.21': 'SW-ACC-NUEVO', '192.0.2.30': 'AP-BIBLIOTECA'})

    async def test_sweep_respects_host_limit_and_probe_errors(self):
        calls = []

        async def probe(ip):
            calls.append(ip)
            if ip.endswith('.2'):
                raise TimeoutError('sin respuesta')
            return None

        self.assertEqual(await discovery.sweep(['10.0.0.0/16'], probe, max_hosts=5), [])
        self.assertEqual(len(calls), 5)

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('DISCOVERY_ENABLED', None)
            self.assertFalse(discovery.settings()['enabled'])
            self.assertFalse(discovery.Scheduler().due())

    def test_scheduler_interval(self):
        now = [0.0]
        scheduler = discovery.Scheduler(clock=lambda: now[0])
        with patch.dict(os.environ, DISCOVERY_ENABLED='true', DISCOVERY_INTERVAL_HOURS='2'):
            self.assertTrue(scheduler.due())
            scheduler.last = 0.0
            now[0] = 3600
            self.assertFalse(scheduler.due())
            now[0] = 7200
            self.assertTrue(scheduler.due())

    async def test_run_does_nothing_when_disabled(self):
        with patch.dict(os.environ, DISCOVERY_ENABLED='false'):
            self.assertEqual(await discovery.run(sondeo_simulado), 0)


if __name__ == '__main__':
    unittest.main()

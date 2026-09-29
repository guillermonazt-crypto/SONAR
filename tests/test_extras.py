"""Pruebas offline de sonar/collector/extras.py con respuestas SNMP simuladas."""
import unittest

from sonar.collector import extras


class Octets:
    """Imita un OctetString de pysnmp."""
    def __init__(self, raw):
        self.raw = raw

    def asOctets(self):
        return self.raw

    def __str__(self):
        return self.raw.decode('latin1')


INTERFACES = [
    dict(indice=10, nombre='GigabitEthernet1/0/1'),
    dict(indice=11, nombre='GigabitEthernet1/0/10'),
    dict(indice=50, nombre='TenGigabitEthernet1/1/1'),
]


def fake_walk(tables):
    async def walk(oid):
        value = tables.get(oid, [])
        if isinstance(value, Exception):
            raise value
        return value
    return walk


def subset(values, keys):
    return {key: values.get(key, 'ausente') for key in keys}


class ExtrasTests(unittest.IsolatedAsyncioTestCase):
    async def test_cdp_neighbors_skip_phones_and_decode_ip(self):
        walk = fake_walk({
            extras.OID_CDP['device']: [([50, 1], Octets(b'SW-DIST.uaeh.local')), ([10, 1], Octets(b'SEP001122334455'))],
            extras.OID_CDP['port']: [([50, 1], Octets(b'TenGigabitEthernet1/1/4'))],
            extras.OID_CDP['platform']: [([50, 1], Octets(b'cisco C9500-24Y4C'))],
            extras.OID_CDP['address']: [([50, 1], Octets(bytes([10, 0, 0, 2])))],
        })
        per_port, _switch = await extras.obtener_extras(walk, INTERFACES)
        self.assertEqual(per_port[50], dict(vecino_nombre='SW-DIST.uaeh.local', vecino_puerto='TenGigabitEthernet1/1/4',
                                            vecino_plataforma='cisco C9500-24Y4C', vecino_ip='10.0.0.2'))
        # Sin vecino (o sólo un teléfono): se limpia el vecino anterior.
        self.assertIsNone(per_port[10]['vecino_nombre'])

    async def test_cdp_failure_keeps_previous_neighbors(self):
        walk = fake_walk({extras.OID_CDP['address']: TimeoutError('sin respuesta')})
        per_port, _switch = await extras.obtener_extras(walk, INTERFACES)
        self.assertNotIn('vecino_nombre', per_port[10])

    async def test_speed_and_last_change(self):
        walk = fake_walk({
            extras.OID_IF_EXTRA['high_speed']: [([10], 1000), ([50], 10000), ([11], 0)],
            extras.OID_IF_EXTRA['last_change']: [([10], 90_000), ([50], 999_999_999)],
        })
        per_port, _switch = await extras.obtener_extras(walk, INTERFACES, uptime_ticks=100_000)
        keys = ('velocidad_mbps', 'ultimo_cambio_hace_s')
        self.assertEqual(subset(per_port[10], keys), dict(velocidad_mbps=1000, ultimo_cambio_hace_s=100))
        # Un ifLastChange mayor que el uptime (contador reiniciado) se ignora.
        self.assertEqual(subset(per_port[50], keys), dict(velocidad_mbps=10000, ultimo_cambio_hace_s='ausente'))
        self.assertNotIn('velocidad_mbps', per_port[11])

    async def test_poe_maps_group_and_port_to_interface(self):
        walk = fake_walk({
            extras.OID_POE_PORT['status']: [([1, 1], 3), ([1, 10], 2), ([2, 1], 4)],
            extras.OID_POE_PORT['consumption']: [([1, 1], 6500)],
            extras.OID_POE_MAIN['power']: [([1], 370)],
            extras.OID_POE_MAIN['consumption']: [([1], 42)],
        })
        per_port, switch = await extras.obtener_extras(walk, INTERFACES)
        keys = ('poe_estado', 'poe_mw')
        self.assertEqual(subset(per_port[10], keys), dict(poe_estado='deliveringPower', poe_mw=6500))
        self.assertEqual(subset(per_port[11], keys), dict(poe_estado='searching', poe_mw=None))
        self.assertEqual(subset(per_port[50], keys), dict(poe_estado=None, poe_mw=None))
        self.assertEqual(switch, dict(poe_presupuesto_w=370.0, poe_consumo_w=42.0))

    async def test_poe_on_non_stack_switch(self):
        ports, _switch = await extras.poe(fake_walk({
            extras.OID_POE_PORT['status']: [([1, 5], 3)],
            extras.OID_POE_MAIN['power']: [([1], 123)],
        }), [dict(indice=5, nombre='FastEthernet0/5')])
        self.assertEqual(ports[5]['poe_estado'], 'deliveringPower')

    async def test_hardware_states(self):
        walk = fake_walk({
            extras.OID_ENVMON['temp_descr']: [([1], Octets(b'SW#1, Sensor#1, GREEN'))],
            extras.OID_ENVMON['temp_value']: [([1], 41)],
            extras.OID_ENVMON['temp_state']: [([1], 1)],
            extras.OID_ENVMON['fan_descr']: [([2], Octets(b'Switch#1, Fan#2'))],
            extras.OID_ENVMON['fan_state']: [([2], 2)],
            extras.OID_ENVMON['supply_descr']: [([3], Octets(b'Sw1, PS1')), ([4], Octets(b'Sw1, PS2'))],
            extras.OID_ENVMON['supply_state']: [([3], 6), ([4], 5)],
        })
        _ports, switch = await extras.obtener_extras(walk, INTERFACES)
        self.assertEqual(switch['temperatura_c'], 41.0)
        states = {item['nombre']: (item['tipo'], item['estado']) for item in switch['hardware']}
        self.assertEqual(states, {
            'SW#1, Sensor#1, GREEN': ('temperatura', 'ok'),
            'Switch#1, Fan#2': ('ventilador', 'warning'),
            'Sw1, PS1': ('fuente', 'critical'),
        })

    async def test_nothing_published(self):
        per_port, switch = await extras.obtener_extras(fake_walk({}), INTERFACES)
        self.assertEqual(switch, {})
        self.assertEqual(per_port[10], dict(vecino_nombre=None, vecino_puerto=None, vecino_plataforma=None, vecino_ip=None))

    def test_sensor_labels_use_short_names(self):
        self.assertTrue(extras.mentions_interface('Te1/1/1 Receive Power Sensor', 'TenGigabitEthernet1/1/1'))
        self.assertTrue(extras.mentions_interface('GigabitEthernet1/0/1 Transmit Power', 'GigabitEthernet1/0/1'))
        self.assertFalse(extras.mentions_interface('Gi1/0/10 Receive Power Sensor', 'GigabitEthernet1/0/1'))
        self.assertFalse(extras.mentions_interface('Te1/1/1 Receive Power Sensor', 'TenGigabitEthernet1/1/10'))


if __name__ == '__main__':
    unittest.main()

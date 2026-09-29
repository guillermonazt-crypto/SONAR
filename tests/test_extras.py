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


MAC_A = [0, 0x50, 0x56, 0xab, 0xcd, 0xef]
MAC_B = [0, 0x11, 0x22, 0x33, 0x44, 0x55]
MAC_C = [0, 0x11, 0x22, 0x33, 0x44, 0x66]


def vlan_walk(contexts, failing=()):
    """contexts: {vlan|None: {oid: filas}}; registra qué VLAN se consultaron."""
    asked = []

    async def walk(oid, vlan=None):
        asked.append((oid, vlan))
        if vlan in failing:
            raise TimeoutError('sin respuesta')
        return contexts.get(vlan, {}).get(oid, [])
    return walk, asked


def fdb(*entries):
    """(mac, bridge_port, ifIndex) -> tablas dot1dTpFdbPort y dot1dBasePortIfIndex."""
    return {extras.OID_FDB_PORT: [(mac, port) for mac, port, _ in entries],
            extras.OID_BRIDGE_IF: [([port], if_index) for _, port, if_index in entries]}


class MacTableTests(unittest.IsolatedAsyncioTestCase):
    async def test_macs_beyond_vlan_one_are_read_per_vlan_context(self):
        walk, asked = vlan_walk({
            None: fdb((MAC_A, 1, 10)),
            20: fdb((MAC_B, 2, 11)),
            30: fdb((MAC_C, 3, 12)),
        })
        table = await extras.tabla_mac(walk, port_vlans=[1, 20, 20, 30, None, 1002])
        self.assertEqual(table, {tuple(MAC_A): 10, tuple(MAC_B): 11, tuple(MAC_C): 12})
        # Sólo las VLAN con puertos asignados; nunca la 1 (contexto por defecto) ni las reservadas.
        self.assertEqual(sorted({vlan for _oid, vlan in asked if vlan}), [20, 30])

    async def test_mac_is_assigned_to_access_port_not_uplink(self):
        # El uplink (ifIndex 50) aprende muchas MAC, entre ellas la del equipo del puerto 10.
        uplink = [([0, 0, 0, 0, 0, n], 9, 50) for n in range(1, 6)]
        walk, _ = vlan_walk({None: fdb((MAC_A, 9, 50), *uplink), 20: fdb((MAC_A, 1, 10))})
        table = await extras.tabla_mac(walk, port_vlans=[20])
        self.assertEqual(table[tuple(MAC_A)], 10)
        self.assertEqual(table[(0, 0, 0, 0, 0, 3)], 50)

    async def test_failing_vlan_and_limit(self):
        walk, asked = vlan_walk({None: fdb((MAC_A, 1, 10)), 40: fdb((MAC_C, 3, 12))}, failing={20})
        table = await extras.tabla_mac(walk, port_vlans=[20, 40], limit=5)
        self.assertEqual(table, {tuple(MAC_A): 10, tuple(MAC_C): 12})
        walk, asked = vlan_walk({})
        await extras.tabla_mac(walk, port_vlans=range(2, 100), limit=3)
        self.assertEqual(sorted({vlan for _oid, vlan in asked if vlan}), [2, 3, 4])

    async def test_vtp_vlans_when_ports_do_not_publish_vlan(self):
        walk, asked = vlan_walk({None: {extras.OID_VTP_VLAN_STATE: [([1, 1], 1), ([1, 10], 1), ([1, 11], 2),
                                                                     ([1, 1003], 1)]}, 10: fdb((MAC_B, 2, 11))})
        table = await extras.tabla_mac(walk)
        self.assertEqual(table, {tuple(MAC_B): 11})
        self.assertEqual(sorted({vlan for _oid, vlan in asked if vlan}), [10])

"""Pruebas offline del DOM óptico (sonar/collector/dom.py y obtener_optica).

Los valores son los que devolvió SW_5_APAN (WS-C2960X, GLC-SX-MMD en Gi1/0/25).
"""
import asyncio
import unittest
from unittest import mock

from sonar.collector import dom, snmp_collector

INTERFACES = [
    dict(indice=10101, nombre='GigabitEthernet1/0/1', estado='up'),
    dict(indice=10125, nombre='GigabitEthernet1/0/25', estado='up'),
]
# entPhysicalIndex -> (entSensorType, entSensorScale, entSensorPrecision, entSensorValue, entSensorStatus, nombre)
SENSORS = {
    1040: (8, 9, 1, 256, 1, 'Gi1/0/25 Module Temperature Sensor'),
    1041: (4, 9, 2, 331, 1, 'Gi1/0/25 Supply Voltage Sensor'),
    1042: (5, 8, 1, 46, 1, 'Gi1/0/25 Bias Current Sensor'),
    1043: (14, 9, 1, -56, 1, 'Gi1/0/25 Transmit Power Sensor'),
    1044: (14, 9, 1, -64, 1, 'Gi1/0/25 Receive Power Sensor'),
}
THRESHOLDS = {  # (severity, relation, value)
    1040: [(20, 4, 900), (10, 4, 850), (10, 2, -50), (20, 2, -100)],
    1043: [(20, 4, 0), (10, 4, -30), (10, 2, -95), (20, 2, -135)],
    1044: [(20, 4, 30), (10, 4, 0), (10, 2, -170), (20, 2, -210)],
}
PARENTS = {index: 1039 for index in SENSORS}


def sensors(**overrides):
    result = {i: dict(type=t, scale=s, precision=p, value=v, status=st, name=n)
              for i, (t, s, p, v, st, n) in SENSORS.items()}
    for index, values in overrides.items():
        result[int(index.lstrip('_'))].update(values)
    return result


def build(readings=None, **kwargs):
    args = dict(thresholds=THRESHOLDS, parents=PARENTS, parent_names={1039: 'GigabitEthernet1/0/25'},
                parent_ifindex={1039: 10125}, interfaces=INTERFACES, admin_status={10125: 1})
    args.update(kwargs)
    return dom.build_transceivers(readings or sensors(), **args)


class ScaleTests(unittest.TestCase):
    def test_scale_is_an_enum_not_an_exponent(self):
        self.assertAlmostEqual(dom.sensor_value(-64, 9, 1), -6.4)    # units, precisión 1
        self.assertAlmostEqual(dom.sensor_value(46, 8, 1), 0.0046)   # milli: 4.6 mA
        self.assertAlmostEqual(dom.sensor_value(331, 9, 2), 3.31)
        self.assertAlmostEqual(dom.sensor_value(-400, 9, 1), -40.0)
        self.assertIsNone(dom.sensor_value(None, 9, 1))

    def test_power_in_watts_is_converted_to_dbm(self):
        self.assertAlmostEqual(dom.watts_to_dbm(0.001), 0.0)
        self.assertAlmostEqual(dom.watts_to_dbm(0.0002291), -6.4, places=2)
        self.assertEqual(dom.watts_to_dbm(0), dom.NO_SIGNAL_DBM)

    def test_alias_mapping(self):
        self.assertEqual(dom.if_index_from_alias('1.3.6.1.2.1.2.2.1.1.10125'), 10125)
        self.assertIsNone(dom.if_index_from_alias(''))


class TransceiverTests(unittest.TestCase):
    def test_real_2960x_reading(self):
        [sfp] = build()
        self.assertEqual((sfp['interfaz'], sfp['indice'], sfp['admin'], sfp['oper']),
                         ('GigabitEthernet1/0/25', 10125, 'up', 'up'))
        self.assertEqual((sfp['rx_dbm'], sfp['tx_dbm'], sfp['temp_c'], sfp['voltaje_v'], sfp['bias_ma']),
                         (-6.4, -5.6, 25.6, 3.31, 4.6))
        self.assertFalse(sfp['sin_senal'])
        self.assertEqual(sfp['umbrales']['rx'], dict(alta_alarma=3.0, alta_aviso=0.0, baja_aviso=-17.0, baja_alarma=-21.0))
        self.assertEqual(sfp['umbrales']['tx']['baja_aviso'], -9.5)
        self.assertEqual(sfp['umbrales']['temp']['alta_alarma'], 90.0)

    def test_chassis_sensors_are_not_optics(self):
        readings = sensors()
        readings[1012] = dict(type=8, scale=9, precision=0, value=24, status=1, name='Switch 1 - Inlet Temp Sensor')
        result = build(readings, parents={**PARENTS, 1012: 1000})
        self.assertEqual(len(result), 1)
        # Un switch sólo con sensores del chasis no tiene DOM.
        self.assertEqual(dom.optic_sensor_indexes({1012: 8}, {1012: 'Switch 1 - Inlet Temp Sensor'}), [])

    def test_no_light_and_unavailable_sensors(self):
        [sfp] = build(sensors(_1044=dict(value=-400)))
        self.assertTrue(sfp['sin_senal'])
        self.assertEqual(sfp['rx_dbm'], -40.0)
        [sfp] = build(sensors(_1044=dict(status=dom.STATUS_UNAVAILABLE)))
        self.assertIsNone(sfp['rx_dbm'])
        [sfp] = build(sensors(_1043=dict(status=dom.STATUS_NONOPERATIONAL)))
        self.assertEqual(sfp['estado'], 'alerta')

    def test_admin_down_and_name_fallback(self):
        [sfp] = build(admin_status={10125: 2}, parent_ifindex={}, parent_names={})
        self.assertEqual((sfp['interfaz'], sfp['admin']), ('GigabitEthernet1/0/25', 'down'))

    def test_empty_slot_has_no_reading(self):
        self.assertEqual(dom.build_transceivers({}, {}, {}, {}, {}, INTERFACES), [])


class ObtenerOpticaTests(unittest.TestCase):
    def run_optica(self, walks, gets):
        calls = []

        async def walk(ip, community, oid, vlan=None):
            calls.append(oid)
            return walks.get(oid, [])

        async def get_many(ip, community, oids, chunk=20):
            return {oid: gets[oid] for oid in oids if oid in gets}

        snmp_collector._DOM_CACHE.clear()
        with mock.patch.object(snmp_collector, '_walk_oid_rows', walk), \
                mock.patch.object(snmp_collector, '_get_many', get_many):
            result = asyncio.run(snmp_collector.obtener_optica(dict(hostname='192.0.2.5'), INTERFACES))
        return result, calls

    def test_copper_only_switch_costs_two_walks(self):
        result, calls = self.run_optica({}, {})
        self.assertEqual(result, [])
        self.assertEqual(calls, [dom.OID_CISCO_SENSOR['type'], dom.OID_STD_SENSOR['type']])

    def test_chassis_only_switch_costs_one_walk(self):
        result, calls = self.run_optica({dom.OID_CISCO_SENSOR['type']: [([1012], 8)]}, {})
        self.assertEqual((result, calls), ([], [dom.OID_CISCO_SENSOR['type']]))

    def test_full_read_and_cached_structure(self):
        cisco, entity = dom.OID_CISCO_SENSOR, dom.OID_ENTITY
        walks = {cisco['type']: [([i], t) for i, (t, *_rest) in SENSORS.items()]}
        for key, position in (('severity', 0), ('relation', 1), ('value', 2)):
            walks[dom.OID_THRESHOLD[key]] = [([i, n + 1], row[position]) for i, rows in THRESHOLDS.items()
                                             for n, row in enumerate(rows)]
        gets = {f'{dom.OID_IF_ADMIN}.10125': 1, f"{entity['name']}.1039": 'GigabitEthernet1/0/25',
                f"{entity['alias']}.1039.0": '1.3.6.1.2.1.2.2.1.1.10125'}
        for i, (_t, scale, precision, value, status, name) in SENSORS.items():
            gets.update({f"{entity['name']}.{i}": name, f"{entity['contained_in']}.{i}": 1039,
                         f"{cisco['scale']}.{i}": scale, f"{cisco['precision']}.{i}": precision,
                         f"{cisco['value']}.{i}": value, f"{cisco['status']}.{i}": status})
        [sfp], calls = self.run_optica(walks, gets)
        self.assertEqual((sfp['rx_dbm'], sfp['tx_dbm'], sfp['umbrales']['rx']['baja_alarma']), (-6.4, -5.6, -21.0))
        self.assertEqual(len(calls), 4)  # tipo + 3 columnas de umbrales

        async def walk(ip, community, oid, vlan=None):
            calls.append(oid)
            return walks.get(oid, [])

        async def get_many(ip, community, oids, chunk=20):
            return {oid: gets[oid] for oid in oids if oid in gets}

        calls.clear()
        with mock.patch.object(snmp_collector, '_walk_oid_rows', walk), \
                mock.patch.object(snmp_collector, '_get_many', get_many):
            [again] = asyncio.run(snmp_collector.obtener_optica(dict(hostname='192.0.2.5'), INTERFACES))
        # Segundo ciclo: la estructura sale de la caché, sólo se lee la columna de tipos.
        self.assertEqual((again['rx_dbm'], calls), (-6.4, [cisco['type']]))

    def test_snmp_failure_returns_none(self):
        async def broken(*args, **kwargs):
            raise OSError('timeout')

        with mock.patch.object(snmp_collector, '_walk_oid_rows', broken):
            self.assertIsNone(asyncio.run(snmp_collector.obtener_optica(dict(hostname='192.0.2.9'), INTERFACES)))


if __name__ == '__main__':
    unittest.main()

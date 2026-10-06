"""zabbix/avanzado.py: plantilla importable, uplinks, coordenadas y reglas de correlación (sin Zabbix real)."""
import re
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'zabbix'))

import avanzado  # noqa: E402
import backfill  # noqa: E402
import trap_relay  # noqa: E402


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


class FakeApi:
    """Responde por método y guarda las llamadas."""

    def __init__(self, **results):
        self.results = results
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        result = self.results.get(method, [])
        return result(params) if callable(result) else result


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.export = avanzado.template_export()['zabbix_export']
        self.template = self.export['templates'][0]

    def test_uuids_are_stable_unique_v4(self):
        uuids = [node['uuid'] for node in walk(self.export) if 'uuid' in node]
        self.assertEqual(len(uuids), len(set(uuids)))
        for value in uuids:
            self.assertEqual(uuid.UUID(value).version, 4)
        self.assertEqual(avanzado.template_export()['zabbix_export'], self.export)

    def test_trend_functions_and_composite_trigger(self):
        expressions = ' '.join(node['expression'] for node in walk(self.export) if 'expression' in node)
        for function in ('trendstl(', 'baselinedev(', 'baselinewma(', 'trendavg('):
            self.assertIn(function, expressions)
        formulas = ' '.join(node.get('params', '') for node in walk(self.export))
        self.assertIn('forecast(//sonar.uplink.in', formulas)
        self.assertIn('timeleft(//sonar.cpu.util,30d', formulas)
        self.assertIn('timeleft(//sonar.optical.rx', formulas)
        uplinks = self.template['discovery_rules'][0]
        damaged = next(t for t in uplinks['trigger_prototypes'] if 'enlace físico dañado' in t['name'])
        self.assertIn('sonar.uplink.crc', damaged['expression'])
        self.assertIn(avanzado.FAST_LOSS, damaged['expression'])
        crc = next(t for t in uplinks['trigger_prototypes'] if t['name'].startswith('SONAR: errores CRC'))
        self.assertEqual(crc['dependencies'][0]['name'], damaged['name'])

    def test_expressions_only_reference_the_template(self):
        for node in walk(self.export):
            for host in re.findall(r'\(/([^/]*)/', node.get('expression', '')):
                self.assertEqual(host, avanzado.TEMPLATE)

    def test_correlation_tags(self):
        for node in walk(self.export):
            if 'expression' in node and 'uuid' in node:  # disparadores (no sus dependencias)
                values = {tag['tag']: tag['value'] for tag in node['tags']}
                self.assertEqual(values['equipo'], '{HOST.HOST}')
                self.assertIn('componente', values)
                self.assertIn(values.get('correlacion', 'causa'), ('causa', 'sintoma'))

    def test_fast_items_and_traps(self):
        items = {item['key']: item for item in self.template['items']}
        self.assertEqual(items[avanzado.FAST_PING]['delay'], '{$SONAR.FAST.INTERVAL}')
        self.assertEqual(items[avanzado.TRAP_DOWN]['type'], 'SNMP_TRAP')
        self.assertNotIn('delay', items[avanzado.TRAP_DOWN])
        macros = {m['macro']: m['value'] for m in self.template['macros']}
        self.assertEqual(macros['{$SONAR.FAST.INTERVAL}'], '30s')


class HelperTests(unittest.TestCase):
    def test_uplink_pattern(self):
        self.assertEqual(avanzado.uplink_pattern([10102, 10101, '10101']), '^(10101|10102)$')
        self.assertEqual(avanzado.uplink_pattern([]), avanzado.NO_INDEX)
        self.assertIsNone(re.match(avanzado.NO_INDEX, '10101'))

    def test_coordinates_like_the_frontend(self):
        known = avanzado.known_coordinates(ROOT)
        self.assertEqual(known['escuela superior apan'], (19.7108, -98.4522))
        self.assertEqual(avanzado.plantel_coordinates('Escuela Superior Apan', {}, known), (19.7108, -98.4522))
        self.assertEqual(avanzado.plantel_coordinates('Instituto de Ciencias Básicas e Ingeniería', {}, known),
                         known['instituto de ciencias basicas e ingenieria'])
        manual = {'Escuela Superior Apan': '19.70, -98.45'}
        self.assertEqual(avanzado.plantel_coordinates('Escuela Superior Apan', manual, known), (19.70, -98.45))
        self.assertIsNone(avanzado.plantel_coordinates('Plantel nuevo', {}, known))

    def test_dependencies_point_access_to_core_of_same_site(self):
        hosts = [dict(hostid='1', tags=[dict(tag='rol', value='core'), dict(tag='plantel', value='Apan')]),
                 dict(hostid='2', tags=[dict(tag='rol', value='access'), dict(tag='plantel', value='Apan')]),
                 dict(hostid='3', tags=[dict(tag='rol', value='access'), dict(tag='plantel', value='Tula')])]
        triggers = [dict(triggerid=f'90{pk}', hosts=[dict(hostid=pk)], dependencies=[]) for pk in '123']
        api = FakeApi(**{'trigger.get': triggers})
        avanzado.apply_dependencies(api, hosts)
        updates = [params for method, params in api.calls if method == 'trigger.update']
        self.assertEqual(updates, [dict(triggerid='902', dependencies=[dict(triggerid='901')])])

    def test_correlations_are_updated_not_duplicated(self):
        name = avanzado.correlation_rules()[0][0]
        api = FakeApi(**{'correlation.get': [dict(correlationid='5', name=name)]})
        avanzado.apply_correlations(api)
        methods = [method for method, _ in api.calls]
        self.assertEqual(methods.count('correlation.update'), 1)
        self.assertEqual(methods.count('correlation.create'), len(avanzado.correlation_rules()) - 1)
        closes_new = api.calls[1][1]
        self.assertEqual(closes_new['operations'], [dict(type=avanzado.CLOSE_NEW)])
        self.assertIn(dict(type=avanzado.TAG_PAIR, oldtag='equipo', newtag='equipo'), closes_new['filter']['conditions'])

    def test_housekeeping_compresses_only_with_timescaledb(self):
        for extension, compressed in (('timescaledb', True), ('', False)):
            api = FakeApi(**{'housekeeping.get': dict(db_extension=extension)})
            avanzado.apply_housekeeping(api, 90)
            body = api.calls[-1][1]
            self.assertEqual((body['hk_history'], body['hk_trends']), ('90d', '365d'))
            self.assertEqual('compression_status' in body, compressed)


class TrendGuardTests(unittest.TestCase):
    def test_anomalies_and_baselines_require_trend_coverage(self):
        export = avanzado.template_export()['zabbix_export']
        for node in walk(export):
            expression = node.get('expression', '')
            if 'uuid' in node and ('trendstl(' in expression or 'baseline' in expression):
                self.assertIn('trendcount(', expression, node['name'])


def v2c_trap(community, trap_oid, extra=()):
    from pysnmp.proto import api
    from pyasn1.codec.ber import encoder
    module = api.PROTOCOL_MODULES[api.SNMP_VERSION_2C]
    pdu = module.SNMPv2TrapPDU()
    module.apiTrapPDU.set_defaults(pdu)
    module.apiTrapPDU.set_varbinds(pdu, [(module.ObjectIdentifier('1.3.6.1.2.1.1.3.0'), module.TimeTicks(5)),
                                         (module.ObjectIdentifier(trap_oid[0]), module.ObjectIdentifier(trap_oid[1])),
                                         *extra])
    message = module.Message()
    module.apiMessage.set_defaults(message)
    module.apiMessage.set_community(message, community)
    module.apiMessage.set_pdu(message, pdu)
    return encoder.encode(message)


class TrapRelayTests(unittest.TestCase):
    def test_decodes_link_down_and_writes_zabbix_format(self):
        from pysnmp.proto import api
        module = api.PROTOCOL_MODULES[api.SNMP_VERSION_2C]
        data = v2c_trap('secreta', (trap_relay.SNMP_TRAP_OID, '1.3.6.1.6.3.1.1.5.3'),
                        [(module.ObjectIdentifier('1.3.6.1.2.1.2.2.1.1.10101'), module.Integer(10101))])
        lines = trap_relay.decode(data, {'secreta'})
        self.assertIn('SNMPv2-MIB::snmpTrapOID.0 = 1.3.6.1.6.3.1.1.5.3 (linkDown)', lines)
        self.assertIn('1.3.6.1.2.1.2.2.1.1.10101 = 10101', lines)
        text = trap_relay.record('192.168.27.3', 50000, lines)
        self.assertRegex(text.splitlines()[0], r'^\S+ ZBXTRAP 192\.168\.27\.3$')
        # La clave del ítem de la plantilla encuentra el trap.
        regex = avanzado.TRAP_DOWN[len('snmptrap["'):-2]
        self.assertRegex(text, regex)

    def test_rejects_other_communities_and_garbage(self):
        data = v2c_trap('otra', (trap_relay.SNMP_TRAP_OID, '1.3.6.1.6.3.1.1.5.3'))
        self.assertIsNone(trap_relay.decode(data, {'secreta'}))
        self.assertIsNotNone(trap_relay.decode(data, set()))
        self.assertIsNone(trap_relay.decode(b'no es snmp', set()))


class BackfillTests(unittest.TestCase):
    def test_only_rows_before_existing_data(self):
        points = [(3600 * 10 + 60, 1.0), (3600 * 10 + 360, 3.0), (3600 * 11 + 60, 5.0), (3600 * 12 + 60, 7.0)]
        history, trends = backfill.rows_before(points, first_history=3600 * 12, first_trend=None)
        self.assertEqual(history, points[:3])
        self.assertEqual(trends, [(36000, 2, 1.0, 2.0, 3.0), (39600, 1, 5.0, 5.0, 5.0)])
        # Zabbix ya tiene trends desde la hora 11: esa hora no se toca.
        _history, trends = backfill.rows_before(points, first_history=3600 * 12, first_trend=3600 * 11)
        self.assertEqual([row[0] for row in trends], [36000])
        self.assertEqual(backfill.rows_before(points, first_history=0, first_trend=None), ([], []))

    def test_copy_script_is_one_transaction(self):
        script = backfill.copy_sql({'42': ([(100, 1.5)], [(0, 1, 1.5, 1.5, 1.5)])})
        self.assertTrue(script.startswith('BEGIN;\nCOPY history'))
        self.assertIn('42\t100\t1.5\t0\n\\.\n', script)
        self.assertIn('42\t0\t1\t1.5\t1.5\t1.5', script)
        self.assertTrue(script.endswith('COMMIT;\n'))

    def test_short_port_matches_backend(self):
        self.assertEqual(backfill.short_port('GigabitEthernet1/0/25'), backfill.short_port('Gi1/0/25'))
        self.assertEqual(backfill.short_port('TenGigabitEthernet1/1/1'), 'te1/1/1')


if __name__ == '__main__':
    unittest.main()

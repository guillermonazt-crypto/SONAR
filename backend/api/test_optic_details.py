from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from planteles.models import Division, Plantel
from switches.models import MuestraOptica, Puerto, Switch, UmbralOptico
from switches.optics import assess_optic
from switches.services import record_poll
from .optic_details import port_key, trends

MODULE = dict(descripcion='1000BaseSX SFP', modelo='GLC-SX-MMD', serie='AGM1234ABCD', longitud_onda_nm=850)
SFP = dict(interfaz='GigabitEthernet1/0/25', indice=10125, rx_dbm=-6.4, tx_dbm=-5.6, temp_c=25.6, voltaje_v=3.31,
           bias_ma=4.6, estado='ok', sin_senal=False, oper='up', admin='up', modulo=MODULE,
           umbrales=dict(voltaje=dict(baja_alarma=2.9, baja_aviso=3.0, alta_aviso=3.6, alta_alarma=3.7),
                         bias=dict(baja_alarma=1.0, alta_alarma=12.0)))


def poll(rx=-6.4, tx=-5.6, crc=0, **port):
    return dict(cpu_5m=1, interfaces=[dict(indice=10125, nombre='GigabitEthernet1/0/25', estado='up',
                                           errores_entrada=crc, errores_salida=0, errores_crc=crc, **port)],
                transceptores=[dict(SFP, rx_dbm=rx, tx_dbm=tx)])


class OpticDetailTests(TestCase):
    def setUp(self):
        cache.clear()
        plantel = Plantel.objects.create(nombre='Apan', division=Division.objects.create(nombre='Escuelas'))
        self.local = Switch.objects.create(nombre='SW_5_APAN', hostname='192.0.2.5', plantel=plantel)
        self.remote = Switch.objects.create(nombre='SW_6_APAN_CASETA', hostname='192.0.2.6', plantel=plantel)
        self.client.force_login(get_user_model().objects.create_user('lector', password='x'))

    def poll(self, switch, at, datos):
        with mock.patch('switches.services.timezone.now', return_value=at):
            record_poll(switch.pk, switch.hostname, datos)

    def optics(self):
        return {(item['device'], item['interfaz']): item
                for item in self.client.get('/api/opticas/?refresh=1').json()['transceptores']}

    def test_port_key_matches_cdp_and_lldp_names(self):
        self.assertEqual(port_key('Gi1/0/25'), port_key('GigabitEthernet1/0/25'))
        self.assertEqual(port_key('Te1/1/1'), port_key('TenGigabitEthernet 1/1/1'))
        self.assertNotEqual(port_key('Gi1/0/25'), port_key('Gi1/0/26'))

    def test_full_detail_per_optic(self):
        now = timezone.now()
        # 8 días de muestras horarias: RX baja 0.5 dB/día.
        for hours in range(8 * 24, -1, -1):
            self.poll(self.local, now - timedelta(hours=hours), poll(rx=round(-6.0 - 0.5 * (8 * 24 - hours) / 24, 3)))
        # El otro extremo publica DOM y lo ve por CDP: pérdida = su TX − nuestro RX.
        self.poll(self.remote, now, poll(rx=-7.0, tx=-5.0))
        Puerto.objects.filter(switch=self.local).update(vecino_nombre='SW_6_APAN_CASETA.uaeh.mx',
                                                        vecino_puerto='Gi1/0/25', errores_crc=17)
        item = self.optics()[('SW_5_APAN', 'GigabitEthernet1/0/25')]
        self.assertEqual(item['modulo']['serie'], 'AGM1234ABCD')
        self.assertEqual(item['modulo']['longitud_onda_nm'], 850)
        self.assertAlmostEqual(item['margen_rx_db'], item['rx_dbm'] + 24, places=2)
        self.assertAlmostEqual(item['perdida_enlace_db'], -5.0 - item['rx_dbm'], places=2)
        self.assertEqual(item['remoto'], dict(switch='SW_6_APAN_CASETA', puerto='GigabitEthernet1/0/25', tx_dbm=-5.0))
        self.assertAlmostEqual(item['delta_rx_24h'], -0.5, places=1)
        self.assertAlmostEqual(item['delta_rx_7d'], -3.5, places=1)
        self.assertTrue(item['serie'] and {'rx_dbm', 'tx_dbm', 'time'} <= set(item['serie'][0]))
        self.assertIsNotNone(item['serie'][-1]['tx_dbm'])
        self.assertAlmostEqual(item['prediccion']['pendiente_db_dia'], -0.5, places=1)
        self.assertEqual(item['errores']['errores_crc'], 17)
        self.assertEqual(item['umbrales']['voltaje']['baja_alarma'], 2.9)
        self.assertEqual(item['niveles']['voltaje'], 'ok')

    def test_no_remote_dom_means_no_loss(self):
        self.poll(self.local, timezone.now(), poll())
        item = self.optics()[('SW_5_APAN', 'GigabitEthernet1/0/25')]
        self.assertIsNone(item['perdida_enlace_db'])
        self.assertIsNone(item['remoto'])
        self.assertEqual((item['delta_rx_24h'], item['delta_rx_7d']), (None, None))

    def test_module_kept_when_reading_lacks_it(self):
        now = timezone.now()
        self.poll(self.local, now, poll())
        datos = poll()
        datos['transceptores'][0]['modulo'] = None
        self.poll(self.local, now + timedelta(minutes=1), datos)
        self.assertEqual(Puerto.objects.get(switch=self.local).optica['modulo']['modelo'], 'GLC-SX-MMD')

    def test_voltage_and_bias_use_module_thresholds(self):
        reading = dict(rx_dbm=-6.0, tx_dbm=-5.0, temperatura=30, voltaje_v=2.8, bias_ma=13.0, admin='up', oper='up',
                       umbrales=SFP['umbrales'], rx_base_dbm=-6.0)
        level, reasons, per_metric = assess_optic(reading, UmbralOptico.actual())
        self.assertEqual((per_metric['voltaje'], per_metric['bias'], level), ('critical', 'critical', 'critical'))
        self.assertTrue(any('Voltaje 2.80 V' in reason['text'] for reason in reasons))
        # Sin umbrales del módulo no hay respaldo global: no alerta.
        level, _reasons, per_metric = assess_optic(dict(reading, umbrales={}), UmbralOptico.actual())
        self.assertEqual((per_metric['voltaje'], per_metric['bias']), ('ok', 'ok'))

    def test_trend_deltas_need_a_nearby_sample(self):
        now = timezone.now()
        self.poll(self.local, now, poll())
        port = Puerto.objects.get(switch=self.local)
        MuestraOptica.objects.create(puerto=port, momento=now - timedelta(hours=10), rx_dbm=-5.0)
        self.assertIsNone(trends([port.pk], now)[port.pk]['delta_rx_24h'])

    def test_report_has_full_columns(self):
        self.poll(self.local, timezone.now(), poll())
        data = self.client.get('/api/reportes/opticas/').json()
        keys = [column['clave'] for column in data['columnas']]
        for key in ('voltaje_v', 'bias_ma', 'margen_rx_db', 'perdida_enlace_db', 'delta_rx_24h', 'delta_rx_7d',
                    'pendiente_db_dia', 'eta_dias', 'errores_crc', 'modelo', 'serie', 'longitud_onda_nm'):
            self.assertIn(key, keys)
        self.assertEqual(data['filas'][0]['serie'], 'AGM1234ABCD')
        self.assertEqual(data['rango']['total'], 1)

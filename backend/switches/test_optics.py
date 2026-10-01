from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from planteles.models import Division, Plantel
from switches import alerts
from switches.health import assess, port_stats, thresholds_by_role
from switches.models import Alerta, Puerto, Switch, UmbralOptico
from switches.optics import assess_optic, effective_limits, update_baseline
from switches.services import record_poll

# Lectura real de un GLC-SX-MMD en un 2960X (SW_5_APAN Gi1/0/25).
MODULE = dict(temp=dict(alta_alarma=90.0, alta_aviso=85.0, baja_aviso=-5.0, baja_alarma=-10.0),
              tx=dict(alta_alarma=0.0, alta_aviso=-3.0, baja_aviso=-9.5, baja_alarma=-13.5),
              rx=dict(alta_alarma=3.0, alta_aviso=0.0, baja_aviso=-17.0, baja_alarma=-21.0))
SFP = dict(interfaz='GigabitEthernet1/0/25', indice=10125, rx_dbm=-6.4, tx_dbm=-5.6, temp_c=25.6, voltaje_v=3.32,
           bias_ma=4.6, estado='ok', sin_senal=False, oper='up', admin='up', umbrales=MODULE)


def poll(**optic):
    return dict(cpu_5s=1, cpu_1m=1, cpu_5m=1, interfaces=[
        dict(indice=10125, nombre='GigabitEthernet1/0/25', estado='up'),
        dict(indice=10101, nombre='GigabitEthernet1/0/1', estado='up')],
        transceptores=[dict(SFP, **optic)])


class OpticAssessmentTests(TestCase):
    def setUp(self):
        self.limits = UmbralOptico.actual()

    def reading(self, **values):
        base = dict(rx_dbm=-6.4, tx_dbm=-5.6, temperatura=25.6, estado='ok', sin_senal=False, admin='up',
                    oper='up', umbrales=MODULE, rx_base_dbm=-6.4)
        return dict(base, **values)

    def test_new_defaults(self):
        self.assertEqual((self.limits.rx_atencion, self.limits.rx_riesgo, self.limits.temp_atencion, self.limits.caida_rx),
                         (-14.0, -17.0, 70.0, 2.0))

    def test_module_thresholds_win_over_global(self):
        self.assertEqual(assess_optic(self.reading(), self.limits)[0], 'ok')
        # -15 dBm: fuera del respaldo global (-14) pero dentro del módulo (aviso -17).
        self.assertEqual(assess_optic(self.reading(rx_dbm=-15.0, rx_base_dbm=-15.0), self.limits)[0], 'ok')
        level, reasons, metrics = assess_optic(self.reading(rx_dbm=-17.5, rx_base_dbm=-17.5), self.limits)
        self.assertEqual((level, metrics['rx']), ('warning', 'warning'))
        self.assertEqual(reasons[0]['text'], 'RX -17.5 dBm (≤ -17, umbral del módulo)')
        self.assertEqual(assess_optic(self.reading(rx_dbm=-21.0, rx_base_dbm=-21.0), self.limits)[0], 'critical')
        self.assertEqual(assess_optic(self.reading(tx_dbm=-14.0), self.limits)[2]['tx'], 'critical')
        self.assertEqual(assess_optic(self.reading(temperatura=86.0), self.limits)[0], 'warning')
        # La temperatura baja del módulo no alerta.
        self.assertEqual(assess_optic(self.reading(temperatura=-6.0), self.limits)[0], 'ok')

    def test_global_fallback_without_module_thresholds(self):
        level, reasons, _ = assess_optic(self.reading(umbrales={}, rx_dbm=-15.0, rx_base_dbm=-15.0), self.limits)
        self.assertEqual((level, reasons[0]['text']), ('warning', 'RX -15.0 dBm (≤ -14, umbral global)'))
        self.assertEqual(assess_optic(self.reading(umbrales={}, rx_dbm=-17.0, rx_base_dbm=-17.0), self.limits)[0], 'critical')
        self.assertEqual(assess_optic(self.reading(umbrales={}, temperatura=75.0), self.limits)[0], 'critical')
        self.assertEqual(effective_limits(self.reading(umbrales={}), self.limits)['temp'],
                         dict(alta_aviso=70.0, alta_alarma=75.0, origen='global'))

    def test_degradation_against_baseline(self):
        level, reasons, _ = assess_optic(self.reading(rx_dbm=-8.5, rx_base_dbm=-6.4), self.limits)
        self.assertEqual((level, reasons[0]['text']),
                         ('warning', 'RX cayó 2.1 dB frente a su línea base de 7 días (-6.4 dBm)'))
        self.assertEqual(assess_optic(self.reading(rx_dbm=-8.0, rx_base_dbm=-6.4), self.limits)[0], 'ok')

    def test_no_false_alerts_for_shutdown_or_unused_ports(self):
        dark = dict(rx_dbm=-40.0, sin_senal=True, rx_base_dbm=-6.4)
        self.assertEqual(assess_optic(self.reading(admin='down', **dark), self.limits)[0], 'ok')
        level, reasons, _ = assess_optic(self.reading(oper='down', **dark), self.limits)
        self.assertEqual((level, reasons[0]['level']), ('ok', 'ok'))
        # Sin luz con el enlace arriba: lectura incoherente, se marca en atención.
        self.assertEqual(assess_optic(self.reading(**dark), self.limits)[0], 'warning')

    def test_baseline_learns_slowly_and_ignores_dark_readings(self):
        now = timezone.now()
        self.assertEqual(update_baseline(None, dict(rx_dbm=-6.4), now), -6.4)
        previous = dict(rx_base_dbm=-6.4, time=(now - timedelta(minutes=1)).isoformat())
        self.assertTrue(-6.41 < update_baseline(previous, dict(rx_dbm=-9.4), now) <= -6.4)
        self.assertEqual(update_baseline(previous, dict(rx_dbm=-40.0, sin_senal=True), now), -6.4)
        self.assertEqual(update_baseline(previous, dict(rx_dbm=-9.4, admin='down'), now), -6.4)
        week = dict(rx_base_dbm=-6.4, time=(now - timedelta(days=7)).isoformat())
        self.assertAlmostEqual(update_baseline(week, dict(rx_dbm=-9.4), now), -6.4 - 3 * (1 - 0.3679), places=2)


class OpticPollTests(TestCase):
    def setUp(self):
        plantel = Plantel.objects.create(nombre='Apan', division=Division.objects.create(nombre='Escuelas'))
        self.switch = Switch.objects.create(nombre='SW_5_APAN', hostname='192.0.2.5', plantel=plantel, rol='access',
                                            lectura_correcta=True, ultima_consulta=timezone.now())

    def optic(self):
        return Puerto.objects.get(switch=self.switch, indice=10125).optica

    def health(self):
        self.switch.refresh_from_db()
        return assess(self.switch, port_stats([self.switch.pk])[self.switch.pk], thresholds_by_role()['access'])

    def test_poll_stores_reading_and_clears_removed_module(self):
        record_poll(self.switch.pk, self.switch.hostname, poll())
        optic = self.optic()
        self.assertEqual((optic['rx_dbm'], optic['temperatura'], optic['bias_ma'], optic['rx_base_dbm']),
                         (-6.4, 25.6, 4.6, -6.4))
        self.assertEqual(optic['umbrales']['rx']['baja_alarma'], -21.0)
        self.assertIsNone(Puerto.objects.get(switch=self.switch, indice=10101).optica)
        # La consulta DOM falló (None): se conserva la lectura anterior.
        record_poll(self.switch.pk, self.switch.hostname, dict(poll(), transceptores=None))
        self.assertEqual(self.optic()['rx_dbm'], -6.4)
        # Módulo retirado: ya no hay lectura.
        record_poll(self.switch.pk, self.switch.hostname, dict(poll(), transceptores=[]))
        self.assertIsNone(self.optic())

    def test_critical_optic_opens_alert(self):
        record_poll(self.switch.pk, self.switch.hostname, poll())
        self.assertEqual(self.health()[0], 'ok')
        record_poll(self.switch.pk, self.switch.hostname, poll(rx_dbm=-21.5))
        level, reasons = self.health()
        self.assertEqual(level, 'critical')
        optic = [r for r in reasons if r['tipo'] == 'optica']
        self.assertEqual(optic[0]['text'], 'Óptica SFP GigabitEthernet1/0/25: RX -21.5 dBm (≤ -21, umbral del módulo)')
        alerts.evaluate(self.switch.pk)
        self.assertEqual(Alerta.objects.get(switch=self.switch, fin__isnull=True).motivos[0]['tipo'], 'optica')

    def test_shutdown_port_does_not_alert(self):
        record_poll(self.switch.pk, self.switch.hostname,
                    poll(rx_dbm=-40.0, tx_dbm=-40.0, sin_senal=True, admin='down'))
        self.assertEqual(self.health()[0], 'ok')

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from planteles.models import Division, Plantel
from switches import alerts
from switches.health import assess, port_stats, thresholds_by_role
from switches.models import Alerta, Mantenimiento, Puerto, Switch, UmbralRol


class SmartAlertTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.plantel = Plantel.objects.create(nombre='Apan', division=Division.objects.create(nombre='Escuelas'))
        self.switch = Switch.objects.create(nombre='SW-CORE', hostname='192.0.2.1', plantel=self.plantel, rol='core',
                                            lectura_correcta=True, ultima_consulta=self.now)

    def ports_with_errors(self, count):
        for index in range(1, count + 1):
            Puerto.objects.create(switch=self.switch, nombre=f'GigabitEthernet1/0/{index}', indice=index,
                                  ultimo_error=self.now)

    def health(self):
        return assess(self.switch, port_stats([self.switch.pk], self.now)[self.switch.pk],
                      thresholds_by_role()[self.switch.rol], self.now)

    def test_several_ports_with_errors_escalate_to_critical(self):
        self.ports_with_errors(2)
        self.assertEqual(self.health()[0], 'warning')
        Puerto.objects.create(switch=self.switch, nombre='GigabitEthernet1/0/9', indice=9, ultimo_error=self.now)
        level, reasons = self.health()
        self.assertEqual(level, 'critical')
        composite = [r for r in reasons if r['tipo'] == 'compuesta']
        self.assertEqual(composite[0]['text'], 'Falla generalizada: 3 puertos con errores nuevos a la vez (≥ 3)')
        # Configurable por rol; 0 lo desactiva.
        UmbralRol.objects.filter(rol="core").update(puertos_riesgo=0)
        self.assertEqual(self.health()[0], 'warning')

    def test_role_defaults_escalate_core_sooner(self):
        thresholds = thresholds_by_role()
        self.assertEqual((thresholds['core']['escalar_minutos'], thresholds['access']['escalar_minutos']), (15, 60))

    def test_unacknowledged_alert_escalates_once(self):
        Switch.objects.filter(pk=self.switch.pk).update(lectura_correcta=False)
        first = alerts.evaluate(self.switch.pk, self.now)
        self.assertTrue(first.startswith('🔴') and not first.escalamiento)
        self.assertIsNone(alerts.evaluate(self.switch.pk, self.now + timedelta(minutes=10)))
        notice = alerts.evaluate(self.switch.pk, self.now + timedelta(minutes=16))
        self.assertTrue(notice.escalamiento)
        self.assertIn('sigue en riesgo desde hace 16 min', notice)
        self.assertIsNotNone(Alerta.objects.get().escalada_en)
        self.assertIsNone(alerts.evaluate(self.switch.pk, self.now + timedelta(minutes=30)))
        # Escalamiento con destinatarios propios además de los normales.
        with patch.dict('os.environ', ALERT_EMAIL_TO='noc@uaeh.test', ALERT_ESCALATION_EMAIL_TO='jefe@uaeh.test'), \
                patch.object(alerts, 'send_mail') as mail:
            alerts.send(notice)
            alerts.send(first)
        self.assertEqual(mail.call_args_list[0].args[3], ['noc@uaeh.test', 'jefe@uaeh.test'])
        self.assertEqual(mail.call_args_list[1].args[3], ['noc@uaeh.test'])

    def test_acknowledged_or_maintenance_alerts_do_not_escalate(self):
        Switch.objects.filter(pk=self.switch.pk).update(lectura_correcta=False)
        alerts.evaluate(self.switch.pk, self.now)
        Alerta.objects.update(reconocida_en=self.now)
        self.assertIsNone(alerts.evaluate(self.switch.pk, self.now + timedelta(hours=1)))
        Alerta.objects.update(reconocida_en=None)
        Mantenimiento.objects.create(switch=self.switch, inicio=self.now, fin=self.now + timedelta(hours=3), motivo='UPS')
        self.assertIsNone(alerts.evaluate(self.switch.pk, self.now + timedelta(hours=1)))
        self.assertIsNone(Alerta.objects.get().escalada_en)

    def test_open_alerts_are_never_duplicated(self):
        Switch.objects.filter(pk=self.switch.pk).update(lectura_correcta=False)
        alerts.evaluate(self.switch.pk, self.now)
        # nivel_alerta se perdió (restauración, edición manual): no se abre otro episodio ni se re-notifica.
        Switch.objects.filter(pk=self.switch.pk).update(nivel_alerta='ok', alerta_enviada=None)
        self.assertIsNone(alerts.evaluate(self.switch.pk, self.now + timedelta(minutes=1)))
        self.assertEqual(Alerta.objects.filter(fin__isnull=True).count(), 1)
        # Duplicados heredados: se conserva el más antiguo.
        extra = Alerta.objects.create(switch=self.switch, inicio=self.now + timedelta(minutes=2), motivos=[])
        alerts.evaluate(self.switch.pk, self.now + timedelta(minutes=3))
        self.assertEqual(Alerta.objects.filter(fin__isnull=True).count(), 1)
        self.assertIsNotNone(Alerta.objects.get(pk=extra.pk).fin)
        # Recuperación: se cierra y se avisa.
        Switch.objects.filter(pk=self.switch.pk).update(lectura_correcta=True)
        self.assertTrue(alerts.evaluate(self.switch.pk, self.now + timedelta(minutes=40)).startswith('🟢'))
        self.assertFalse(Alerta.objects.filter(fin__isnull=True).exists())

    def test_critical_without_episode_is_recorded_silently(self):
        Switch.objects.filter(pk=self.switch.pk).update(lectura_correcta=False, nivel_alerta='critical')
        self.assertIsNone(alerts.evaluate(self.switch.pk, self.now))
        alert = Alerta.objects.get()
        self.assertFalse(alert.notificada)
        self.assertIsNone(alert.fin)

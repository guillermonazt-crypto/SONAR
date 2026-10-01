"""Descubrimiento (parte Django) y respaldos de configuración con SSH simulado."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from planteles.models import Division, Plantel
from . import backups
from .discovery import cdp_candidates, pending, record_candidates
from .models import Descubierto, Puerto, Respaldo, Switch

CONFIG = """Building configuration...

Current configuration : 1234 bytes
!
! Last configuration change at 10:00:00 CST Mon Sep 28 2026 by admin
hostname SW-LAB
enable secret 9 $9$abcdefghijklmnop
username admin privilege 15 password 7 0822455D0A16
snmp-server community S3cr3t RO
interface GigabitEthernet1/0/1
 description Recepcion
!
end
SW-LAB#"""


class DiscoveryTests(TestCase):
    def setUp(self):
        plantel = Plantel.objects.create(nombre='Lab', division=Division.objects.create(nombre='Test'))
        self.switch = Switch.objects.create(nombre='SW-LAB', hostname='192.0.2.1', plantel=plantel)

    def test_cdp_candidates_and_review_flow(self):
        Puerto.objects.create(switch=self.switch, nombre='Gi1/0/48', indice=48, vecino_nombre='SW-NUEVO',
                              vecino_ip='192.0.2.9', vecino_plataforma='cisco C9200L')
        Puerto.objects.create(switch=self.switch, nombre='Gi1/0/47', indice=47, vecino_nombre='SW-LAB',
                              vecino_ip='192.0.2.1')
        # Los teléfonos IP no se proponen para el inventario.
        Puerto.objects.create(switch=self.switch, nombre='Gi1/0/5', indice=5, vecino_nombre='SEP001122334455',
                              vecino_ip='192.0.2.50', vecino_tipo='telefono')
        candidates = cdp_candidates()
        self.assertEqual([c['ip'] for c in candidates], ['192.0.2.9'])
        self.assertEqual(candidates[0]['visto_desde'], 'SW-LAB · Gi1/0/48')
        self.assertEqual(record_candidates(candidates + [dict(ip='192.0.2.1', origen='barrido')]), 1)
        self.assertEqual([c.ip for c in pending()], ['192.0.2.9'])
        # Ignorado: no vuelve a aparecer aunque se vea otra vez.
        Descubierto.objects.update(estado='ignorado')
        self.assertEqual(record_candidates(candidates), 0)
        self.assertFalse(pending().exists())
        # Dado de alta en el inventario: deja de ser candidato.
        Descubierto.objects.update(estado='pendiente')
        Switch.objects.create(nombre='SW-NUEVO', hostname='192.0.2.9', plantel=self.switch.plantel)
        self.assertFalse(pending().exists())

    def test_discovered_api_is_for_editors(self):
        record_candidates([dict(ip='192.0.2.30', nombre='AP-BIBLIOTECA', origen='barrido')])
        reader = get_user_model().objects.create_user(username='r', password='x', rol='lector')
        editor = get_user_model().objects.create_user(username='e', password='x', rol='editor')
        self.client.force_login(reader)
        self.assertEqual(self.client.get('/api/descubiertos/').status_code, 403)
        self.client.force_login(editor)
        items = self.client.get('/api/descubiertos/').json()
        self.assertEqual(items[0]['nombre'], 'AP-BIBLIOTECA')
        self.assertEqual(self.client.post(f"/api/descubiertos/{items[0]['id']}/ignorar/").json()['estado'], 'ignorado')
        self.assertEqual(self.client.get('/api/descubiertos/').json(), [])


class BackupTests(TestCase):
    def setUp(self):
        plantel = Plantel.objects.create(nombre='Lab', division=Division.objects.create(nombre='Test'))
        self.switch = Switch.objects.create(nombre='SW-LAB', hostname='192.0.2.1', plantel=plantel)
        self.config = dict(backups.settings(), user='respaldo', password='no-se-usa')
        self.t0 = timezone.now()

    def fetch(self, text):
        calls = []

        def fetch(host, config):
            calls.append((host, config['user']))
            return text
        fetch.calls = calls
        return fetch

    def test_clean_and_redact(self):
        cleaned = backups.clean(CONFIG)
        self.assertTrue(cleaned.startswith('!\nhostname SW-LAB'))
        self.assertNotIn('Last configuration change', cleaned)
        self.assertNotIn('SW-LAB#', cleaned)
        hidden = backups.redact(cleaned)
        self.assertIn('enable secret 9 <oculto>', hidden)
        self.assertIn('password 7 <oculto>', hidden)
        self.assertIn('snmp-server community <oculto> RO', hidden)
        self.assertNotIn('S3cr3t', hidden)

    def test_versions_only_when_config_changes(self):
        fetch = self.fetch(CONFIG)
        first = backups.backup_switch(self.switch, fetch, self.config, self.t0)
        self.assertEqual(fetch.calls, [('192.0.2.1', 'respaldo')])
        # Mismo contenido (sólo cambió la hora del último cambio): no hay versión nueva.
        same = backups.backup_switch(self.switch, self.fetch(CONFIG.replace('10:00:00', '11:30:00')), self.config,
                                     self.t0 + timedelta(days=1))
        self.assertEqual(same.pk, first.pk)
        self.assertEqual(Respaldo.objects.get().verificado, self.t0 + timedelta(days=1))
        changed = backups.backup_switch(self.switch, self.fetch(CONFIG.replace(' description Recepcion', ' description Caja 1\n shutdown')),
                                        self.config, self.t0 + timedelta(days=2))
        self.assertNotEqual(changed.pk, first.pk)
        self.assertEqual((changed.lineas_agregadas, changed.lineas_eliminadas), (2, 1))

    def test_ssh_errors_are_recorded(self):
        def broken(host, config):
            raise TimeoutError('timed out')
        result = backups.backup_switch(self.switch, broken, self.config, self.t0)
        self.assertEqual((result.exito, result.error), (False, 'timed out'))
        empty = backups.backup_switch(self.switch, self.fetch('SW-LAB#'), self.config, self.t0)
        self.assertFalse(empty.exito)
        self.assertIn('vacía', empty.error)

    def test_api_permissions_diff_and_redaction(self):
        backups.backup_switch(self.switch, self.fetch(CONFIG), self.config, self.t0)
        latest = backups.backup_switch(self.switch, self.fetch(CONFIG.replace('Recepcion', 'Caja 1')), self.config,
                                       self.t0 + timedelta(hours=1))
        users = get_user_model().objects
        reader = users.create_user(username='r', password='x', rol='lector')
        editor = users.create_user(username='e', password='x', rol='editor')
        admin = users.create_user(username='a', password='x', rol='admin')
        self.client.force_login(reader)
        self.assertEqual(self.client.get(f'/api/switches/{self.switch.pk}/respaldos/').status_code, 403)
        self.assertEqual(self.client.get(f'/api/respaldos/{latest.pk}/').status_code, 403)
        self.client.force_login(editor)
        versions = self.client.get(f'/api/switches/{self.switch.pk}/respaldos/').json()
        self.assertEqual(len(versions), 2)
        detail = self.client.get(f'/api/respaldos/{latest.pk}/').json()
        self.assertTrue(detail['secretos_ocultos'])
        self.assertNotIn('S3cr3t', detail['contenido'])
        self.assertIn('- description Recepcion', detail['diferencias'])
        self.assertIn('+ description Caja 1', detail['diferencias'])
        self.client.force_login(admin)
        self.assertIn('S3cr3t', self.client.get(f'/api/respaldos/{latest.pk}/').json()['contenido'])

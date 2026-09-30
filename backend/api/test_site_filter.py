"""?plantel=<id>: el selector global del frontend filtra todas las vistas por plantel."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from planteles.models import Division, Plantel
from switches.models import Alerta, Mantenimiento, Puerto, Switch
from api.reports import site_id


class SiteFilterTests(TestCase):
    def setUp(self):
        cache.clear()
        self.reader = get_user_model().objects.create_user(username='reader', password='test-password', rol='lector')
        division = Division.objects.create(nombre='Escuelas')
        self.apan = Plantel.objects.create(nombre='Apan', division=division)
        self.tula = Plantel.objects.create(nombre='Tula', division=division)
        self.sw_apan = Switch.objects.create(nombre='SW-APAN', hostname='192.0.2.1', plantel=self.apan,
                                             poe_presupuesto_w=370, poe_consumo_w=100,
                                             hardware=[dict(tipo='fuente', nombre='PS1', estado='ok', valor=None)])
        self.sw_tula = Switch.objects.create(nombre='SW-TULA', hostname='192.0.2.2', plantel=self.tula,
                                             poe_presupuesto_w=370, poe_consumo_w=100,
                                             hardware=[dict(tipo='fuente', nombre='PS1', estado='ok', valor=None)])
        for index, switch in enumerate((self.sw_apan, self.sw_tula), start=1):
            Puerto.objects.create(switch=switch, nombre='Gi1/0/1', indice=1, vecino_nombre=f'AP-{index}',
                                  vecino_tipo='ap', vecino_plataforma='cisco AIR-AP2802I', vecino_ip=f'192.0.2.{50 + index}',
                                  mac_equipo=f'aa:bb:cc:00:00:0{index}', vlan=30, poe_mw=15400, poe_estado='deliveringPower',
                                  estado_operativo='up', uso_pct=80.0, ip_equipo=f'192.0.2.{50 + index}')
            Puerto.objects.create(switch=switch, nombre='Gi1/0/2', indice=2, mac_telefono=f'00:11:22:33:44:0{index}',
                                  vlan=10, voice_vlan=110, poe_mw=6200, estado_operativo='up')
            Alerta.objects.create(switch=switch, inicio=timezone.now(),
                                  motivos=[dict(level='critical', tipo='snmp', text='No responde a SNMP')])
        now = timezone.now()
        Mantenimiento.objects.create(plantel=self.apan, inicio=now, fin=now + timezone.timedelta(hours=1), motivo='A')
        Mantenimiento.objects.create(switch=self.sw_tula, inicio=now, fin=now + timezone.timedelta(hours=1), motivo='T')
        self.client.force_login(self.reader)

    def names(self, rows, key='switch'):
        return {row[key] for row in rows}

    def test_site_id_parsing(self):
        self.assertEqual(site_id({'plantel': '7'}), 7)
        for value in ('', 'all', None, '-1', 'x'):
            self.assertIsNone(site_id({'plantel': value}))
        self.assertIsNone(site_id({}))

    def test_switch_list_and_search(self):
        self.assertEqual(self.names(self.client.get('/api/switches/').json(), 'nombre'), {'SW-APAN', 'SW-TULA'})
        listed = self.client.get('/api/switches/', {'plantel': self.apan.pk}).json()
        self.assertEqual(self.names(listed, 'nombre'), {'SW-APAN'})
        # El detalle no se restringe: se puede abrir un switch desde otra vista.
        self.assertEqual(self.client.get(f'/api/switches/{self.sw_tula.pk}/', {'plantel': self.apan.pk}).status_code, 200)
        found = self.client.get('/api/buscar/', {'q': '192.0.2', 'plantel': self.tula.pk}).json()
        self.assertEqual({port['switch']['nombre'] for port in found['puertos']}, {'SW-TULA'})
        self.assertEqual(self.names(found['switches'], 'nombre'), {'SW-TULA'})

    def test_summary_is_cached_per_site(self):
        everything = self.client.get('/api/resumen/').json()
        self.assertEqual(self.names(everything['switches'], 'nombre'), {'SW-APAN', 'SW-TULA'})
        apan = self.client.get('/api/resumen/', {'plantel': self.apan.pk}).json()
        self.assertEqual(self.names(apan['switches'], 'nombre'), {'SW-APAN'})
        self.assertEqual([site['nombre'] for site in apan['planteles']], ['Apan'])
        self.assertEqual(apan['planteles'][0]['alertas_abiertas'], 1)
        tula = self.client.get('/api/resumen/', {'plantel': self.tula.pk}).json()
        self.assertEqual(self.names(tula['switches'], 'nombre'), {'SW-TULA'})

    def test_alerts_summary_and_maintenance(self):
        self.assertEqual(self.client.get('/api/alertas/resumen/').json()['abiertas'], 2)
        self.assertEqual(self.client.get('/api/alertas/resumen/', {'plantel': self.apan.pk}).json(),
                         dict(abiertas=1, sin_reconocer=1))
        alerts = self.client.get('/api/alertas/', {'plantel': self.tula.pk}).json()
        self.assertEqual({alert['switch']['nombre'] for alert in alerts}, {'SW-TULA'})
        windows = lambda site: {w['motivo'] for w in self.client.get('/api/mantenimientos/', {'vigentes': 1, 'plantel': site}).json()}
        self.assertEqual(windows(self.apan.pk), {'A'})
        self.assertEqual(windows(self.tula.pk), {'T'})

    def test_optics_filter(self):
        for switch in (self.sw_apan, self.sw_tula):
            Puerto.objects.create(switch=switch, nombre='Te1/1/1', indice=9, optica=dict(rx_dbm=-5.0, tx_dbm=-2.0, temperatura=30.0))
        self.assertEqual(len(self.client.get('/api/opticas/').json()['transceptores']), 2)
        items = self.client.get('/api/opticas/', {'plantel': self.apan.pk}).json()['transceptores']
        self.assertEqual([item['device'] for item in items], ['SW-APAN'])
        report = self.client.get('/api/reportes/opticas/', {'plantel': self.tula.pk}).json()
        self.assertEqual(self.names(report['filas']), {'SW-TULA'})

    def test_every_report_accepts_site(self):
        for kind in ('inventario', 'disponibilidad', 'puertos-saturados', 'poe', 'hardware', 'topologia',
                     'aps-telefonos', 'tendencias'):
            everything = self.client.get(f'/api/reportes/{kind}/').json()['filas']
            self.assertEqual(self.names(everything), {'SW-APAN', 'SW-TULA'}, kind)
            only = self.client.get(f'/api/reportes/{kind}/', {'plantel': self.apan.pk}).json()['filas']
            self.assertEqual(self.names(only), {'SW-APAN'}, kind)
        csv = self.client.get('/api/reportes/inventario/', {'plantel': self.tula.pk, 'formato': 'csv'}).content.decode('utf-8-sig')
        self.assertIn('SW-TULA', csv)
        self.assertNotIn('SW-APAN', csv)

    def test_topology_includes_aps_and_phones_with_details(self):
        rows = self.client.get('/api/reportes/topologia/', {'plantel': self.apan.pk}).json()['filas']
        by_kind = {row['vecino_tipo']: row for row in rows}
        self.assertEqual(set(by_kind), {'ap', 'telefono'})
        ap, phone = by_kind['ap'], by_kind['telefono']
        self.assertEqual((ap['vecino'], ap['plataforma'], ap['mac'], ap['vecino_ip'], ap['vlan'], ap['poe_w'], ap['uso_pct']),
                         ('AP-1', 'cisco AIR-AP2802I', 'aa:bb:cc:00:00:01', '192.0.2.51', 30, 15.4, 80.0))
        # Teléfono reconocido sólo por su MAC: VLAN de voz y consumo PoE.
        self.assertEqual((phone['vecino'], phone['mac'], phone['vlan'], phone['poe_w'], phone['puerto']),
                         ('00:11:22:33:44:01', '00:11:22:33:44:01', 110, 6.2, 'Gi1/0/2'))

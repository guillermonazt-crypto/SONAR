from django.contrib.auth import get_user_model
from django.test import TestCase

from planteles.models import Division, Plantel
from switches.models import Puerto, Switch


class RangeReportTests(TestCase):
    """Reportes por excepción: sólo lo fuera de rango más el total evaluado para "✓ N sanos"."""

    def setUp(self):
        plantel = Plantel.objects.create(nombre='Lab', division=Division.objects.create(nombre='Test'))
        switch = Switch.objects.create(nombre='SW', hostname='192.0.2.1', plantel=plantel, hardware=[
            dict(tipo='ventilador', nombre='Fan 1', estado='critical'), dict(tipo='fuente', nombre='PS 1', estado='ok')])
        for index in range(1, 5):
            Puerto.objects.create(switch=switch, nombre=f'Gi1/0/{index}', indice=index)
        Puerto.objects.create(switch=switch, nombre='Vlan1', indice=100, es_fisico=False)
        self.client.force_login(get_user_model().objects.create_user('lector', password='x'))

    def get(self, kind):
        return self.client.get(f'/api/reportes/{kind}/').json()

    def test_port_reports_count_evaluated_ports(self):
        data = self.get('puertos-errores')
        self.assertEqual(data['filas'], [])
        self.assertEqual(data['rango'], dict(total=4, etiqueta='puertos sanos'))

    def test_hardware_total_is_every_component(self):
        self.assertEqual(self.get('hardware')['rango']['total'], 2)

    def test_listing_reports_have_no_range(self):
        self.assertNotIn('rango', self.get('inventario'))

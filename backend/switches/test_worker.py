import os
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from planteles.models import Division, Plantel
from switches.models import Switch
from sonar.utils.config import load_inventory

class WorkerIntegrationTests(TestCase):
    def test_inventory_filters_and_reloads(self):
        division = Division.objects.create(nombre="Lab")
        plantel = Plantel.objects.create(nombre="Lab", division=division)
        switch = Switch.objects.create(nombre="test", hostname="192.0.2.1", plantel=plantel)
        with patch.dict(os.environ, INVENTORY_SOURCE="django"), patch("django.db.connections.close_all"), patch("django.db.close_old_connections"):
            self.assertEqual(load_inventory()[0]["hostname"], "192.0.2.1")
            switch.activo = False
            switch.save()
            self.assertEqual(load_inventory(), [])
            switch.activo = True
            switch.save()
            plantel.activo = False
            plantel.save()
            self.assertEqual(load_inventory(), [])

    def test_role_does_not_grant_admin_permissions(self):
        user = get_user_model().objects.create_user(username="reader", rol="lector")
        self.assertFalse(user.has_perm("switches.change_switch"))
        self.client.force_login(user)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

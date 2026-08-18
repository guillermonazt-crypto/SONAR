# backend/usuarios/models.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Modelo de usuario con roles para SONAR.

from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    """
    Usuario de SONAR con tres roles posibles.
    Extiende el modelo de usuario de Django para agregar el rol.
    """
    ROLES = [
        ('admin',  'Administrador'),
        ('editor', 'Editor'),
        ('lector', 'Lector'),
    ]

    rol = models.CharField(
        max_length=20,
        choices=ROLES,
        default='lector'
    )

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        return f"{self.username} ({self.get_rol_display()})"

    @property
    def es_admin(self):
        return self.rol == 'admin'

    @property
    def es_editor(self):
        return self.rol in ['admin', 'editor']

    @property
    def es_lector(self):
        return True  # Todos pueden leer
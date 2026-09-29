# backend/usuarios/models.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Modelo de usuario con roles para SONAR.

# pyrefly: ignore [missing-import]
from django.contrib.auth.models import AbstractUser
# pyrefly: ignore [missing-import]
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

class Bitacora(models.Model):
    """Quién cambió qué y cuándo (inventario, alertas, mantenimientos, respaldos)."""
    usuario = models.ForeignKey(Usuario, null=True, blank=True, on_delete=models.SET_NULL, related_name='bitacora')
    usuario_nombre = models.CharField(max_length=150, blank=True, default='')
    accion = models.CharField(max_length=30)
    objeto = models.CharField(max_length=30)
    objeto_id = models.IntegerField(null=True, blank=True)
    descripcion = models.CharField(max_length=255)
    cambios = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    momento = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Registro de bitácora"
        verbose_name_plural = "Bitácora"
        ordering = ['-momento']

    def __str__(self):
        return f"{self.momento:%Y-%m-%d %H:%M} {self.usuario_nombre}: {self.descripcion}"

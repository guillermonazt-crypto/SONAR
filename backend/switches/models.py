# backend/switches/models.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Modelos para switches y puertos de red.

from django.db import models
from planteles.models import Plantel


class Switch(models.Model):
    """
    Representa un switch Cisco Catalyst en la red de la UAEH.
    """
    ROLES = [
        ('core',         'Core'),
        ('distribution', 'Distribución'),
        ('access',       'Acceso'),
    ]

    nombre   = models.CharField(max_length=100)
    hostname = models.GenericIPAddressField(unique=True)
    rol      = models.CharField(max_length=20, choices=ROLES, default='access')
    plantel  = models.ForeignKey(
        Plantel,
        on_delete=models.CASCADE,
        related_name='switches'
    )
    activo   = models.BooleanField(default=True)
    creado   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Switch"
        verbose_name_plural = "Switches"
        ordering = ['plantel', 'nombre']

    def __str__(self):
        return f"{self.nombre} ({self.hostname})"


class Puerto(models.Model):
    """
    Estado actual de un puerto del switch.
    Se actualiza cada ciclo de polling SNMP.
    """
    ESTADOS = [
        ('verde',    'Uso general'),
        ('rojo',     'Dañado'),
        ('naranja',  'Trunk'),
        ('amarillo', 'AP Native VLAN'),
        ('azul',     'Telefonía'),
        ('gris',     'Desconectado'),
    ]

    switch         = models.ForeignKey(
        Switch,
        on_delete=models.CASCADE,
        related_name='puertos'
    )
    nombre         = models.CharField(max_length=50)   # GigabitEthernet1/0/1
    indice         = models.IntegerField()              # ifIndex SNMP
    estado         = models.CharField(max_length=20, choices=ESTADOS, default='gris')
    vlan           = models.IntegerField(null=True, blank=True)
    voice_vlan     = models.IntegerField(null=True, blank=True)
    es_trunk       = models.BooleanField(default=False)
    errores_entrada = models.BigIntegerField(default=0)
    errores_salida  = models.BigIntegerField(default=0)
    actualizado    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Puerto"
        verbose_name_plural = "Puertos"
        ordering = ['indice']
        unique_together = ['switch', 'indice']

    def __str__(self):
        return f"{self.switch.nombre} — {self.nombre} [{self.estado}]"
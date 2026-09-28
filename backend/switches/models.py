# backend/switches/models.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Modelos para switches y puertos de red.

# pyrefly: ignore [missing-import]
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
    ultima_consulta = models.DateTimeField(null=True, blank=True)
    lectura_correcta = models.BooleanField(null=True, default=None)
    cpu_5s = models.IntegerField(null=True, blank=True)
    cpu_1m = models.IntegerField(null=True, blank=True)
    cpu_5m = models.IntegerField(null=True, blank=True)
    memoria_usada_pct = models.FloatField(null=True, blank=True)
    memoria_total_bytes = models.BigIntegerField(null=True, blank=True)
    memoria_usada_bytes = models.BigIntegerField(null=True, blank=True)
    uptime_segundos = models.BigIntegerField(null=True, blank=True)
    ultimo_reinicio = models.DateTimeField(null=True, blank=True)
    modelo = models.CharField(max_length=100, null=True, blank=True)
    firmware = models.CharField(max_length=100, null=True, blank=True)

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
    descripcion    = models.TextField(null=True, blank=True)
    indice         = models.IntegerField()              # ifIndex SNMP
    estado         = models.CharField(max_length=20, choices=ESTADOS, default='gris')
    vlan           = models.IntegerField(null=True, blank=True)
    voice_vlan     = models.IntegerField(null=True, blank=True)
    es_trunk       = models.BooleanField(default=False)
    estado_operativo = models.CharField(max_length=20, default="unknown")
    ip_equipo = models.TextField(null=True, blank=True)
    mac_equipo = models.TextField(null=True, blank=True)
    mac_telefono = models.TextField(null=True, blank=True)
    dhcp = models.BooleanField(null=True, blank=True)
    errores_crc = models.BigIntegerField(null=True, blank=True)
    errores_entrada = models.BigIntegerField(null=True, blank=True)
    errores_salida  = models.BigIntegerField(null=True, blank=True)
    octetos_entrada = models.BigIntegerField(null=True, blank=True)
    octetos_salida  = models.BigIntegerField(null=True, blank=True)
    actualizado    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Puerto"
        verbose_name_plural = "Puertos"
        ordering = ['indice']
        unique_together = ['switch', 'indice']

    def __str__(self):
        return f"{self.switch.nombre} — {self.nombre} [{self.estado}]"

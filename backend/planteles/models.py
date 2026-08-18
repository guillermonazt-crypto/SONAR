# backend/planteles/models.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Modelos para la jerarquia de planteles de la UAEH.
# Division → Plantel → Switches

from django.db import models


class Division(models.Model):
    """
    Las tres divisiones de la UAEH.
    Institutos, Escuelas Superiores y Preparatorias.
    """
    nombre = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "División"
        verbose_name_plural = "Divisiones"
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Plantel(models.Model):
    """
    Cada uno de los 25 planteles de la UAEH.
    Pertenece a una Division.
    """
    nombre    = models.CharField(max_length=200)
    division  = models.ForeignKey(
        Division,
        on_delete=models.CASCADE,
        related_name='planteles'
    )
    ubicacion = models.CharField(max_length=200, blank=True)
    activo    = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Plantel"
        verbose_name_plural = "Planteles"
        ordering = ['division', 'nombre']

    def __str__(self):
        return f"{self.division} — {self.nombre}"
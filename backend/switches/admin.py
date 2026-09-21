# backend/switches/admin.py
# pyrefly: ignore [missing-import]
from django.contrib import admin
# pyrefly: ignore [missing-import]
from .models import Switch, Puerto

@admin.register(Switch)
class SwitchAdmin(admin.ModelAdmin):
    list_display  = ['nombre', 'hostname', 'rol', 'plantel', 'activo']
    list_filter   = ['rol', 'activo', 'plantel']
    search_fields = ['nombre', 'hostname']

@admin.register(Puerto)
class PuertoAdmin(admin.ModelAdmin):
    list_display  = ['nombre', 'switch', 'estado', 'vlan', 'es_trunk']
    list_filter   = ['estado', 'es_trunk']
    search_fields = ['nombre', 'switch__nombre']
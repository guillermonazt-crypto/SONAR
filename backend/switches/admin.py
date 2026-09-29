# backend/switches/admin.py
# pyrefly: ignore [missing-import]
from django.contrib import admin
# pyrefly: ignore [missing-import]
from .models import Switch, Puerto, UmbralOptico, UmbralRol

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

@admin.register(UmbralRol)
class UmbralRolAdmin(admin.ModelAdmin):
    list_display = ['rol', 'cpu_atencion', 'cpu_riesgo', 'memoria_atencion', 'memoria_riesgo']

@admin.register(UmbralOptico)
class UmbralOpticoAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'rx_atencion', 'rx_riesgo', 'tx_minimo', 'temp_atencion', 'temp_riesgo']

    def has_add_permission(self, request):
        # Una sola fila de umbrales.
        return not UmbralOptico.objects.exists()

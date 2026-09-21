# backend/planteles/admin.py
# pyrefly: ignore [missing-import]
from django.contrib import admin
# pyrefly: ignore [missing-import]
from .models import Division, Plantel

@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = ['nombre']

@admin.register(Plantel)
class PlantelAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'division', 'activo']
    list_filter  = ['division', 'activo']
    search_fields = ['nombre']
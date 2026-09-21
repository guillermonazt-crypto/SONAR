# backend/usuarios/admin.py
# pyrefly: ignore [missing-import]
from django.contrib import admin
# pyrefly: ignore [missing-import]
from django.contrib.auth.admin import UserAdmin
# pyrefly: ignore [missing-import]
from .models import Usuario

@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display  = ['username', 'email', 'rol', 'is_active']
    list_filter   = ['rol', 'is_active']
    fieldsets     = UserAdmin.fieldsets + (
        ('Rol SONAR', {'fields': ('rol',)}),
    )
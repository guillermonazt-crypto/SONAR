"""Registro en la bitácora de cambios (usuarios.Bitacora)."""
from django.forms.models import model_to_dict

from .models import Bitacora


def client_ip(request):
    if request is None:
        return None
    return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR') or None


def snapshot(instance, fields=None):
    """Valores simples de un modelo para comparar antes y después de editarlo."""
    data = model_to_dict(instance, fields=fields)
    return {key: value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
            for key, value in data.items()}


def differences(before, after):
    return {key: [before.get(key), value] for key, value in after.items() if before.get(key) != value}


def registrar(request, accion, objeto, descripcion, objeto_id=None, cambios=None, usuario=None):
    user = usuario or (request.user if request is not None and request.user.is_authenticated else None)
    return Bitacora.objects.create(
        usuario=user, usuario_nombre=getattr(user, 'username', '') or 'sistema',
        accion=accion, objeto=objeto, objeto_id=objeto_id, descripcion=descripcion[:255],
        cambios=cambios or {}, ip=client_ip(request),
    )

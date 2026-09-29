"""Refresco eficiente: la interfaz consulta cada pocos segundos, pero el worker
sólo escribe una vez por ciclo. Con ETag el navegador revalida y, si nada
cambió, Django responde 304 sin volver a enviar el cuerpo.
"""
from django.utils.cache import patch_cache_control


class ApiRevalidateMiddleware:
    """Las respuestas GET del API se revalidan siempre (no-cache) y son privadas."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method == 'GET' and request.path.startswith('/api/') and not response.has_header('Cache-Control'):
            patch_cache_control(response, private=True, no_cache=True)
        return response

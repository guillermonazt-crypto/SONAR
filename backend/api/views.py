from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.db.models import Max
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from planteles.models import Division, Plantel
from switches.health import STALE_MINUTES, assess, port_stats, thresholds_by_role
from switches.models import Puerto, Switch
from . import history
from .history import flux_string  # noqa: F401 (usado por pruebas)
from .permissions import InventoryPermission
from .serializers import DivisionSerializer, PlantelSerializer, SwitchSerializer, PuertoSerializer
from .zabbix import status as zabbix_status

LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 15 * 60
SUMMARY_CACHE_SECONDS = 60


def requires_session(view):
    """Las vistas JSON fuera de DRF también exigen sesión iniciada."""
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_authenticated and request.user.is_active):
            return JsonResponse({'detail': 'Inicia sesión para continuar.'}, status=403)
        return view(request, *args, **kwargs)
    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def user_data(user):
    if not user.is_authenticated:
        return None
    return dict(id=user.pk, username=user.username, rol=user.rol,
                can_edit=user.is_superuser or user.rol in ('admin', 'editor'),
                is_staff=user.is_staff)


def client_ip(request):
    # Detrás de Nginx, REMOTE_ADDR es el proxy; éste envía la IP real en
    # X-Real-IP (frontend/nginx.conf). Sin proxy no se confía en el encabezado.
    if settings.SECURE_PROXY_SSL_HEADER and request.META.get('HTTP_X_REAL_IP'):
        return request.META['HTTP_X_REAL_IP']
    return request.META.get('REMOTE_ADDR', '')


@require_GET
def session(request):
    return JsonResponse(dict(user=user_data(request.user), csrfToken=get_token(request)))


@require_POST
@csrf_protect
def sign_in(request):
    username = request.POST.get('username', '')
    key = f'login-failures:{client_ip(request)}:{username.lower()}'
    if cache.get(key, 0) >= LOGIN_MAX_FAILURES:
        return JsonResponse({'detail': 'Demasiados intentos fallidos. Espera 15 minutos.'}, status=429)
    user = authenticate(request, username=username, password=request.POST.get('password', ''))
    if user is None:
        cache.set(key, cache.get(key, 0) + 1, LOGIN_LOCK_SECONDS)
        return JsonResponse({'detail': 'Usuario o contraseña incorrectos.'}, status=401)
    cache.delete(key)
    login(request, user)
    return JsonResponse(dict(user=user_data(user), csrfToken=get_token(request)))


@require_POST
@csrf_protect
def sign_out(request):
    logout(request)
    return JsonResponse(dict(user=None, csrfToken=get_token(request)))


@require_GET
@requires_session
def zabbix(request):
    return JsonResponse(zabbix_status())


@require_GET
@requires_session
def port_history(request, pk=None):
    """Devuelve la serie histórica de tráfico de un puerto desde InfluxDB."""
    port = Puerto.objects.select_related('switch').filter(pk=pk).first()
    if port is None:
        return JsonResponse({'points': []}, status=404)
    try:
        return JsonResponse({'points': history.port_history(port.switch.nombre, port.nombre)})
    except Exception as error:
        return JsonResponse({'points': [], 'detail': f'Histórico no disponible: {error}'})


@require_GET
@requires_session
def switch_history(request, pk=None):
    """Serie de CPU, memoria y tráfico de un switch para las gráficas nativas."""
    switch = Switch.objects.filter(pk=pk).first()
    if switch is None:
        return JsonResponse({'points': []}, status=404)
    try:
        return JsonResponse({'points': history.switch_histories([switch.nombre]).get(switch.nombre, [])})
    except Exception as error:
        return JsonResponse({'points': [], 'detail': f'Histórico no disponible: {error}'})


def build_summary(now=None):
    """Estado, motivos, conteos de puertos e histórico de todos los switches."""
    now = now or timezone.now()
    switches = list(Switch.objects.select_related('plantel__division').all())
    stats = port_stats([s.pk for s in switches], now)
    thresholds = thresholds_by_role()
    detail = None
    try:
        histories = history.switch_histories([s.nombre for s in switches if s.activo])
    except Exception as error:
        histories, detail = {}, f'Histórico no disponible: {error}'
    items = []
    for switch in switches:
        level, reasons = assess(switch, stats[switch.pk], thresholds[switch.rol], now)
        items.append(dict(SwitchSerializer(switch).data,
                          division_nombre=switch.plantel.division.nombre,
                          estado=level, motivos=reasons, puertos=stats[switch.pk],
                          historial=histories.get(switch.nombre, [])))
    last = Switch.objects.filter(activo=True).aggregate(last=Max('ultima_consulta'))['last']
    return dict(
        generado=now.isoformat(),
        ultima_lectura=last.isoformat() if last else None,
        worker_atrasado=bool(items) and (last is None or (now - last).total_seconds() > STALE_MINUTES * 60),
        umbrales=thresholds,
        historial_detalle=detail,
        switches=items,
    )


@require_GET
@requires_session
def summary(request):
    """Un solo request para la vista Resumen, cacheado un ciclo del worker."""
    data = cache.get('sonar-summary')
    if data is None or request.GET.get('refresh') == '1':
        data = build_summary()
        cache.set('sonar-summary', data, SUMMARY_CACHE_SECONDS)
    return JsonResponse(data)


class InventoryViewSet(viewsets.ModelViewSet):
    permission_classes = [InventoryPermission]
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']

class DivisionViewSet(InventoryViewSet):
    queryset = Division.objects.all()
    serializer_class = DivisionSerializer

class PlantelViewSet(InventoryViewSet):
    queryset = Plantel.objects.select_related('division').all()
    serializer_class = PlantelSerializer

class SwitchViewSet(InventoryViewSet):
    queryset = Switch.objects.select_related('plantel').all()
    serializer_class = SwitchSerializer

    @action(detail=True, methods=['get'])
    def puertos(self, request, pk=None):
        # El panel físico sólo expone conectores reales del chasis; el worker
        # marca es_fisico al guardar cada interfaz.
        ports = self.get_object().puertos.filter(es_fisico=True)
        return Response(PuertoSerializer(ports, many=True).data)

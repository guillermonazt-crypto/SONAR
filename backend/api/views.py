from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
import re
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from planteles.models import Division, Plantel
from switches.models import Switch
from .permissions import InventoryPermission
from .serializers import DivisionSerializer, PlantelSerializer, SwitchSerializer, PuertoSerializer
from .zabbix import status as zabbix_status

PHYSICAL_INTERFACE_RE = re.compile(
    r'^(?:FastEthernet0/\d+|GigabitEthernet0/[1-9]\d*|'
    r'GigabitEthernet\d+/\d+/\d+|TenGigabitEthernet\d+/\d+/\d+|'
    r'TwentyFiveGigE\d+/\d+/\d+|FortyGigabitEthernet\d+/\d+/\d+)$'
)
GENERIC_PHYSICAL_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_.-]*\d+/\d+(?:/\d+)?$')


def is_physical_interface(name):
    name = (name or '').strip()
    if any(token.lower() in name.lower() for token in ('vlan', 'loopback', 'tunnel', 'null', 'stack', 'bluetooth', 'port-channel', 'portchannel', 'unrouted')):
        return False
    if name.endswith('/0/0') or name.endswith('0/0'):
        return False
    return bool(PHYSICAL_INTERFACE_RE.fullmatch(name) or GENERIC_PHYSICAL_NAME_RE.fullmatch(name))


def user_data(user):
    if not user.is_authenticated:
        return None
    return dict(id=user.pk, username=user.username, rol=user.rol,
                can_edit=user.is_superuser or user.rol in ('admin', 'editor'),
                is_staff=user.is_staff)

@require_GET
def session(request):
    return JsonResponse(dict(user=user_data(request.user), csrfToken=get_token(request)))

@require_POST
@csrf_protect
def sign_in(request):
    user = authenticate(request, username=request.POST.get('username', ''), password=request.POST.get('password', ''))
    if user is None:
        return JsonResponse({'detail': 'Usuario o contraseña incorrectos.'}, status=401)
    login(request, user)
    return JsonResponse(dict(user=user_data(user), csrfToken=get_token(request)))

@require_POST
@csrf_protect
def sign_out(request):
    logout(request)
    return JsonResponse(dict(user=None, csrfToken=get_token(request)))

@require_GET
def zabbix(request):
    return JsonResponse(zabbix_status())

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
        # El inventario SNMP puede contener interfaces lógicas históricas. El
        # panel físico sólo expone conectores reales del chasis.
        ports = [
            port for port in self.get_object().puertos.all()
            if is_physical_interface(port.nombre)
        ]
        return Response(PuertoSerializer(ports, many=True).data)

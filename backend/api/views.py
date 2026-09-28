from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
import re
import os
from datetime import timedelta
from django.utils import timezone
from influxdb_client import InfluxDBClient
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

@require_GET
def port_history(request, pk=None):
    """Devuelve la serie histórica de tráfico de un puerto desde InfluxDB."""
    port = Puerto.objects.select_related('switch').filter(pk=pk).first()
    if port is None:
        return JsonResponse({'points': []}, status=404)
    url = os.getenv('INFLUX_URL', 'http://localhost:8086')
    token = os.getenv('INFLUX_TOKEN', '')
    org = os.getenv('INFLUX_ORG', 'universidad')
    bucket = os.getenv('INFLUX_BUCKET', 'red_universitaria')
    flux = f'''from(bucket: "{bucket}")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "interfaces")
  |> filter(fn: (r) => r.device == "{port.switch.nombre}" and r.interface == "{port.nombre}")
  |> filter(fn: (r) => r._field == "octetos_entrada" or r._field == "octetos_salida")
  |> aggregateWindow(every: 3m, fn: last, createEmpty: false)
  |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")'''
    try:
        with InfluxDBClient(url=url, token=token, org=org) as client:
            rows = client.query_api().query(flux, org=org)
        points = []
        for table in rows:
            for record in table.records:
                values = record.values
                points.append({'time': record.get_time().isoformat(),
                               'entrada': values.get('octetos_entrada'),
                               'salida': values.get('octetos_salida')})
        return JsonResponse({'points': points})
    except Exception as error:
        return JsonResponse({'points': [], 'detail': f'Histórico no disponible: {error}'})


@require_GET
def switch_history(request, pk=None):
    """Serie de CPU y memoria para las gráficas nativas de SONAR."""
    switch = Switch.objects.filter(pk=pk).first()
    if switch is None:
        return JsonResponse({'points': []}, status=404)
    url = os.getenv('INFLUX_URL', 'http://localhost:8086')
    token = os.getenv('INFLUX_TOKEN', '')
    org = os.getenv('INFLUX_ORG', 'universidad')
    bucket = os.getenv('INFLUX_BUCKET', 'red_universitaria')
    flux = f'''from(bucket: "{bucket}")
  |> range(start: -24h)
  |> filter(fn: (r) => r.device == "{switch.nombre}")
  |> filter(fn: (r) => r._measurement == "cpu" or r._measurement == "sistema")
  |> aggregateWindow(every: 15m, fn: last, createEmpty: false)
  |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")'''
    try:
        with InfluxDBClient(url=url, token=token, org=org) as client:
            rows = client.query_api().query(flux, org=org)
        points = []
        for table in rows:
            for record in table.records:
                values = record.values
                points.append({'time': record.get_time().isoformat(),
                               'cpu': values.get('cpu_5m'),
                               'memoria': values.get('memoria_usada_pct'),
                               'uptime': values.get('uptime_segundos')})
        return JsonResponse({'points': points})
    except Exception as error:
        return JsonResponse({'points': [], 'detail': f'Histórico no disponible: {error}'})

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

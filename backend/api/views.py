from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.db.models import Max, Q
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from planteles.models import Division, Plantel
from switches.health import (STALE_MINUTES, assess, connection_state, in_grace, port_stats, reason_type,
                             summarize_sites, thresholds_by_role)
from switches import backups, discovery
from switches.models import (Alerta, Descubierto, EstadoMonitoreo, Mantenimiento, Puerto, Respaldo, Switch,
                             UmbralOptico)
from usuarios.audit import differences, registrar, snapshot
from usuarios.models import Bitacora
from switches.optics import assess_optic, effective_limits, sort_key as optic_sort_key
from . import history, reports
from .reports import site_id
from .search import search as search_devices
from .history import flux_string  # noqa: F401 (usado por pruebas)
from .permissions import EditorOnlyPermission, InventoryPermission, can_edit
from .serializers import (AlertaSerializer, BitacoraSerializer, DescubiertoSerializer, DivisionSerializer,
                          MantenimientoSerializer, PlantelSerializer, PuertoSerializer, RespaldoSerializer,
                          SwitchSerializer)
from .zabbix import status as zabbix_status

LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 15 * 60
SUMMARY_CACHE_SECONDS = 60
# El worker escribe cada ciclo (60 s); la vista puede refrescar cada 3 s sin ir a InfluxDB.
OPTICS_CACHE_SECONDS = 30
OPTIC_LIMIT_FIELDS = ('rx_atencion', 'rx_riesgo', 'rx_saturacion', 'tx_minimo', 'temp_atencion', 'temp_riesgo', 'caida_rx')


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
    registrar(request, 'sesion', 'usuario', 'Inició sesión', user.pk, usuario=user)
    return JsonResponse(dict(user=user_data(user), csrfToken=get_token(request)))


@require_POST
@csrf_protect
def sign_out(request):
    """Cierra la sesión sin cuerpo: ningún dato de la sesión anterior viaja en la respuesta."""
    logout(request)
    response = HttpResponse(status=204)
    response['Cache-Control'] = 'no-store'
    return response


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


@require_GET
@requires_session
def search(request):
    """Buscador global por MAC, IP, descripción de puerto o switch."""
    return JsonResponse(search_devices(request.GET.get('q', ''), site_id(request.GET)))


def build_summary(now=None, plantel=None):
    """Estado, motivos, conteos de puertos e histórico de los switches y planteles (todos o uno)."""
    now = now or timezone.now()
    switches = Switch.objects.select_related('plantel__division').all()
    if plantel is not None:
        switches = switches.filter(plantel_id=plantel)
    switches = list(switches)
    stats = port_stats([s.pk for s in switches], now)
    thresholds = thresholds_by_role()
    detail = None
    try:
        histories = history.switch_histories([s.nombre for s in switches if s.activo])
    except Exception as error:
        histories, detail = {}, f'Histórico no disponible: {error}'
    alerts = {}
    for alert in Alerta.objects.filter(fin__isnull=True, switch__in=switches).order_by('inicio'):
        # Sólo debería haber una abierta por switch; si hubiera más, cuenta la primera.
        alerts.setdefault(alert.switch_id, alert)
    worker = EstadoMonitoreo.actual()
    items = []
    for switch in switches:
        level, reasons = assess(switch, stats[switch.pk], thresholds[switch.rol], now, started=worker.iniciado)
        alert = alerts.get(switch.pk)
        items.append(dict(SwitchSerializer(switch).data,
                          division_nombre=switch.plantel.division.nombre,
                          estado=level, motivos=reasons, puertos=stats[switch.pk],
                          conexion=connection_state(switch, worker.iniciado, now)[0] if switch.activo else None,
                          alerta=alert and dict(id=alert.pk, desde=alert.inicio.isoformat(),
                                                reconocida=alert.reconocida_en is not None),
                          historial=histories.get(switch.nombre, [])))
    last = Switch.objects.filter(activo=True, pk__in=[s.pk for s in switches]).aggregate(last=Max('ultima_consulta'))['last']
    return dict(
        generado=now.isoformat(),
        ultima_lectura=last.isoformat() if last else None,
        worker_atrasado=bool(items) and not in_grace(worker.iniciado, now) and (
            last is None or (now - last).total_seconds() > STALE_MINUTES * 60),
        monitoreo=dict(iniciado=worker.iniciado and worker.iniciado.isoformat(),
                       latido=worker.latido and worker.latido.isoformat(),
                       iniciando=in_grace(worker.iniciado, now)),
        umbrales=thresholds,
        historial_detalle=detail,
        planteles=site_summary(switches, items, alerts.values(), now, plantel),
        switches=items,
    )


def site_summary(switches, items, open_alerts, now, plantel=None):
    """Tablero por plantel: todos los planteles activos y los que tienen equipos (o sólo el elegido)."""
    used = {s.plantel_id for s in switches}
    places = Plantel.objects.select_related('division').filter(Q(activo=True) | Q(pk__in=used))
    if plantel is not None:
        places = places.filter(pk=plantel)
    site_of = {s.pk: s.plantel_id for s in switches}
    by_site = {}
    for alert in open_alerts:
        site = site_of[alert.switch_id]
        total, pending = by_site.get(site, (0, 0))
        by_site[site] = (total + 1, pending + (alert.reconocida_en is None))
    maintenance = {pk for pk in Mantenimiento.activas(now).values_list('plantel', flat=True) if pk}
    return summarize_sites(places, items, by_site, maintenance)


@require_GET
@requires_session
def summary(request):
    """Un solo request para la vista Resumen (?plantel=<id> opcional), cacheado un ciclo del worker."""
    plantel = site_id(request.GET)
    # Un arranque del worker invalida el resumen guardado (los estados cambian a "iniciando").
    started = EstadoMonitoreo.actual().iniciado
    key = f'sonar-summary:{plantel or "all"}:{started.timestamp() if started else 0}'
    data = cache.get(key)
    if data is None or request.GET.get('refresh') == '1':
        data = build_summary(plantel=plantel)
        cache.set(key, data, SUMMARY_CACHE_SECONDS)
    return JsonResponse(data)


@require_GET
@requires_session
def report(request, kind):
    """Reporte en JSON (tabla en pantalla) o CSV (?formato=csv) para Excel."""
    if kind not in reports.REPORTS:
        return JsonResponse({'detail': 'Reporte desconocido.'}, status=404)
    data = reports.build(kind, request.GET)
    if request.GET.get('formato') != 'csv':
        return JsonResponse(data)
    import csv
    from django.http import HttpResponse
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="sonar-{kind}-{timezone.now():%Y%m%d-%H%M}.csv"'
    response.write('\ufeff')  # BOM: Excel reconoce los acentos.
    writer = csv.writer(response)
    writer.writerow([column['titulo'] for column in data['columnas']])
    for row in data['filas']:
        writer.writerow([csv_cell(row.get(column['clave'])) for column in data['columnas']])
    return response


def csv_cell(value):
    """Texto que Excel no interprete como fórmula (las descripciones vienen de los equipos)."""
    if value is None:
        return ''
    if isinstance(value, str) and value[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value


def build_optics(plantel=None):
    """Transceptores SFP con su última lectura DOM, umbrales efectivos, nivel y motivos."""
    limits = UmbralOptico.actual()
    ports = Puerto.objects.filter(optica__isnull=False, switch__activo=True)
    if plantel is not None:
        ports = ports.filter(switch__plantel_id=plantel)
    ports = (ports
             .select_related('switch__plantel').only(
                 'pk', 'nombre', 'estado_operativo', 'optica', 'switch__nombre', 'switch__hostname',
                 'switch__plantel_id', 'switch__plantel__nombre'))
    items = []
    for port in ports:
        switch = port.switch
        reading = dict(port.optica, oper=port.estado_operativo)
        level, reasons, per_metric = assess_optic(reading, limits)
        rx, tx = reading.get('rx_dbm'), reading.get('tx_dbm')
        items.append(dict(
            reading, device=switch.nombre, interfaz=port.nombre,
            atenuacion=round(abs(tx - rx), 2) if None not in (rx, tx) and not reading.get('sin_senal') else None,
            umbrales=effective_limits(reading, limits), niveles=per_metric, nivel=level, motivos=reasons,
            switch=dict(id=switch.pk, nombre=switch.nombre, hostname=switch.hostname,
                        plantel=switch.plantel_id, plantel_nombre=switch.plantel.nombre),
            puerto_id=port.pk,
        ))
    items.sort(key=optic_sort_key)
    return dict(generado=timezone.now().isoformat(), detalle=None,
                umbrales={field: getattr(limits, field) for field in OPTIC_LIMIT_FIELDS},
                transceptores=items)


@require_GET
@requires_session
def optics(request):
    data = cache.get('sonar-optics')
    if data is None or request.GET.get('refresh') == '1':
        data = build_optics()
        cache.set('sonar-optics', data, OPTICS_CACHE_SECONDS)
    plantel = site_id(request.GET)
    if plantel is not None:
        # Se filtra la copia cacheada de toda la red: un solo caché para todos los planteles.
        data = dict(data, transceptores=[item for item in data['transceptores'] if item['switch']['plantel'] == plantel])
    return JsonResponse(data)


class AuditedMixin:
    """Cada alta, edición o baja queda en la bitácora con los campos que cambiaron."""
    audit_object = ''

    def perform_create(self, serializer):
        instance = serializer.save()
        registrar(self.request, 'crear', self.audit_object, f'Creó {self.audit_object} {instance}',
                  instance.pk, snapshot(instance))

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        instance = serializer.save()
        changes = differences(before, snapshot(instance))
        if changes:
            registrar(self.request, 'editar', self.audit_object, f'Editó {self.audit_object} {instance}',
                      instance.pk, changes)

    def perform_destroy(self, instance):
        registrar(self.request, 'eliminar', self.audit_object, f'Eliminó {self.audit_object} {instance}',
                  instance.pk, snapshot(instance))
        instance.delete()


class InventoryViewSet(AuditedMixin, viewsets.ModelViewSet):
    permission_classes = [InventoryPermission]
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']

class DivisionViewSet(InventoryViewSet):
    audit_object = 'división'
    queryset = Division.objects.all()
    serializer_class = DivisionSerializer

class PlantelViewSet(InventoryViewSet):
    audit_object = 'plantel'
    queryset = Plantel.objects.select_related('division').all()
    serializer_class = PlantelSerializer

class SwitchViewSet(InventoryViewSet):
    audit_object = 'switch'
    queryset = Switch.objects.select_related('plantel').all()
    serializer_class = SwitchSerializer

    def get_queryset(self):
        """?plantel=<id> filtra el listado; el detalle y la edición no se restringen."""
        switches = super().get_queryset()
        plantel = site_id(self.request.query_params)
        if self.action == 'list' and plantel is not None:
            switches = switches.filter(plantel_id=plantel)
        return switches

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action in ('list', 'retrieve'):
            switches = list(self.get_queryset())
            now = timezone.now()
            context['health'] = dict(stats=port_stats([s.pk for s in switches], now), thresholds=thresholds_by_role(),
                                     now=now, maintenance=Mantenimiento.por_switch(switches, now))
        return context

    @action(detail=True, methods=['get', 'post'])
    def respaldos(self, request, pk=None):
        """Historial de configuraciones (GET) o respaldo inmediato (POST). Sólo editores."""
        if not can_edit(request.user):
            return Response({'detail': 'Sólo editores y administradores ven las configuraciones.'}, status=403)
        switch = self.get_object()
        if request.method == 'POST':
            result = backups.backup_switch(switch)
            registrar(request, 'respaldar', 'switch', f'Respaldó la configuración de {switch.nombre}', switch.pk,
                      dict(exito=result.exito, error=result.error))
        versions = Respaldo.objects.filter(switch=switch)[:100]
        return Response(RespaldoSerializer(versions, many=True).data)

    @action(detail=True, methods=['get'])
    def puertos(self, request, pk=None):
        # El panel físico sólo expone conectores reales del chasis; el worker
        # marca es_fisico al guardar cada interfaz.
        ports = self.get_object().puertos.filter(es_fisico=True)
        return Response(PuertoSerializer(ports, many=True).data)


class LimitedListMixin:
    """?limit=N en el listado (sin recortar el queryset que usa el detalle)."""
    default_limit = 200

    def list(self, request, *args, **kwargs):
        try:
            limit = max(1, min(int(request.query_params.get('limit', self.default_limit)), 2000))
        except ValueError:
            limit = self.default_limit
        items = self.filter_queryset(self.get_queryset())[:limit]
        return Response(self.get_serializer(items, many=True).data)


class AlertaViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    """Centro de alertas: episodios en riesgo, abiertos y cerrados."""
    permission_classes = [InventoryPermission]
    serializer_class = AlertaSerializer

    def get_queryset(self):
        """Filtros: ?estado=abiertas|cerradas, ?plantel=<id>, ?sin_reconocer=1 (y ?tipo= en el listado)."""
        alerts = Alerta.objects.select_related('switch__plantel', 'reconocida_por')
        params = self.request.query_params
        if params.get('estado') == 'abiertas':
            alerts = alerts.filter(fin__isnull=True)
        elif params.get('estado') == 'cerradas':
            alerts = alerts.filter(fin__isnull=False)
        if params.get('plantel', '').isdigit():
            alerts = alerts.filter(switch__plantel_id=int(params['plantel']))
        if params.get('sin_reconocer') == '1':
            alerts = alerts.filter(reconocida_en__isnull=True)
        return alerts

    def filter_queryset(self, queryset):
        # El tipo vive dentro de 'motivos' (JSON): se filtra en Python, antes del límite.
        kind = self.request.query_params.get('tipo')
        if not kind or self.action != 'list':
            return queryset
        return [alert for alert in queryset.iterator()
                if any(reason_type(reason) == kind for reason in alert.motivos or [])]

    @action(detail=False, methods=['get'])
    def resumen(self, request):
        open_alerts = Alerta.objects.filter(fin__isnull=True)
        plantel = site_id(request.query_params)
        if plantel is not None:
            open_alerts = open_alerts.filter(switch__plantel_id=plantel)
        return Response(dict(abiertas=open_alerts.count(),
                             sin_reconocer=open_alerts.filter(reconocida_en__isnull=True).count()))

    @action(detail=True, methods=['post'])
    def reconocer(self, request, pk=None):
        alert = Alerta.objects.select_related('switch').filter(pk=pk).first()
        if alert is None:
            return Response({'detail': 'La alerta no existe.'}, status=404)
        alert.reconocida_por, alert.reconocida_en = request.user, timezone.now()
        alert.nota = str(request.data.get('nota', ''))[:2000]
        alert.save(update_fields=['reconocida_por', 'reconocida_en', 'nota'])
        registrar(request, 'reconocer', 'alerta', f'Reconoció la alerta de {alert.switch.nombre}', alert.pk,
                  dict(nota=alert.nota))
        return Response(AlertaSerializer(alert).data)


class MantenimientoViewSet(AuditedMixin, viewsets.ModelViewSet):
    """Ventanas de mantenimiento por switch o por plantel."""
    audit_object = 'mantenimiento'
    permission_classes = [InventoryPermission]
    serializer_class = MantenimientoSerializer
    queryset = Mantenimiento.objects.select_related('switch', 'plantel', 'creado_por')

    def get_queryset(self):
        windows = super().get_queryset()
        if self.request.query_params.get('vigentes') == '1':
            windows = windows.filter(fin__gt=timezone.now())
        plantel = site_id(self.request.query_params)
        if plantel is not None:
            windows = windows.filter(Q(plantel_id=plantel) | Q(switch__plantel_id=plantel))
        return windows

    def perform_create(self, serializer):
        serializer.save(creado_por=self.request.user)
        instance = serializer.instance
        registrar(self.request, 'crear', 'mantenimiento', f'Programó mantenimiento: {instance}', instance.pk,
                  snapshot(instance))


class BitacoraViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    """Bitácora de cambios; sólo editores y administradores (incluye IPs)."""
    permission_classes = [EditorOnlyPermission]
    serializer_class = BitacoraSerializer
    default_limit = 300

    def get_queryset(self):
        entries = Bitacora.objects.all()
        if self.request.query_params.get('objeto'):
            entries = entries.filter(objeto=self.request.query_params['objeto'])
        return entries


class DescubiertoViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    """Equipos vistos por CDP o barrido SNMP que no están en el inventario."""
    permission_classes = [EditorOnlyPermission]
    serializer_class = DescubiertoSerializer

    def get_queryset(self):
        return discovery.pending()

    @action(detail=True, methods=['post'])
    def ignorar(self, request, pk=None):
        candidate = Descubierto.objects.filter(pk=pk).first()
        if candidate is None:
            return Response({'detail': 'El equipo no existe.'}, status=404)
        candidate.estado = 'ignorado'
        candidate.save(update_fields=['estado'])
        registrar(request, 'ignorar', 'descubierto', f'Ignoró el equipo descubierto {candidate}', candidate.pk)
        return Response(DescubiertoSerializer(candidate).data)


@require_GET
@requires_session
def backup_detail(request, pk):
    """Contenido de una versión y diferencias con la anterior; secretos ocultos salvo para administradores."""
    if not can_edit(request.user):
        return JsonResponse({'detail': 'Sólo editores y administradores ven las configuraciones.'}, status=403)
    version = Respaldo.objects.select_related('switch').filter(pk=pk, exito=True).first()
    if version is None:
        return JsonResponse({'detail': 'El respaldo no existe.'}, status=404)
    previous = (Respaldo.objects.filter(switch=version.switch, exito=True, momento__lt=version.momento)
                .order_by('-momento').first())
    full = request.user.is_superuser or request.user.rol == 'admin'
    show = (lambda text: text) if full else backups.redact
    return JsonResponse(dict(RespaldoSerializer(version).data, switch_nombre=version.switch.nombre,
                             contenido=show(version.contenido), secretos_ocultos=not full,
                             diferencias=show(backups.diff(previous.contenido if previous else '', version.contenido))))

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from .interfaces import is_physical_interface
from .models import EventoPuerto, Switch, Puerto

ERROR_FIELDS = ('errores_entrada', 'errores_salida', 'errores_crc')
OPTIONAL_FIELDS = ('es_trunk', 'ip_equipo', 'mac_equipo', 'mac_telefono', 'dhcp', 'vlan', 'voice_vlan',
                   'octetos_entrada', 'octetos_salida', 'vecino_nombre', 'vecino_puerto',
                   'vecino_plataforma', 'vecino_ip', 'velocidad_mbps', 'poe_estado', 'poe_mw')
UPDATE_FIELDS = ['nombre', 'descripcion', 'estado_operativo', *ERROR_FIELDS, 'errores_nuevos',
                 'ultimo_error', 'es_fisico', 'actualizado', *OPTIONAL_FIELDS,
                 'bps_entrada', 'bps_salida', 'uso_pct', 'ultimo_cambio', 'ultimo_activo']
SWITCH_EXTRA_FIELDS = ('temperatura_c', 'hardware', 'poe_presupuesto_w', 'poe_consumo_w')
EVENT_RETENTION = timedelta(days=7)
LINK_STATES = ('up', 'down')


def traffic(port, previous, now):
    """bps y % de uso entre dos sondeos; None si no hay base o el contador se reinició."""
    octets_in, octets_out, at = previous
    port.bps_entrada = port.bps_salida = port.uso_pct = None
    if None in (octets_in, octets_out, at, port.octetos_entrada, port.octetos_salida) or now <= at:
        return
    delta_in, delta_out = port.octetos_entrada - octets_in, port.octetos_salida - octets_out
    if delta_in < 0 or delta_out < 0:
        return
    seconds = (now - at).total_seconds()
    port.bps_entrada = int(delta_in * 8 / seconds)
    port.bps_salida = int(delta_out * 8 / seconds)
    if port.velocidad_mbps:
        port.uso_pct = round(max(port.bps_entrada, port.bps_salida) * 100 / (port.velocidad_mbps * 1_000_000), 2)


def link_history(port, previous_state, item, now, events):
    """Registra cambios up/down, la última vez con enlace y desde cuándo está como está."""
    state = port.estado_operativo
    if state == 'up':
        port.ultimo_activo = now
    if previous_state in LINK_STATES and state in LINK_STATES and previous_state != state:
        port.ultimo_cambio = now
        events.append(EventoPuerto(puerto=port, estado=state, momento=now))
    elif port.ultimo_cambio is None and item.get('ultimo_cambio_hace_s') is not None:
        # Primer sondeo: ifLastChange dice desde cuándo el puerto está así.
        port.ultimo_cambio = now - timedelta(seconds=item['ultimo_cambio_hace_s'])
    if state == 'down' and port.ultimo_activo is None and port.ultimo_cambio:
        port.ultimo_activo = port.ultimo_cambio


def new_errors(previous, current):
    """Suma de errores nuevos entre dos lecturas; None si no hay base previa."""
    total, known = 0, False
    for before, after in zip(previous, current):
        if before is None or after is None:
            continue
        known = True
        # Si el contador bajó, el equipo reinició: todo lo actual es nuevo.
        total += after - before if after >= before else after
    return total if known else None


@transaction.atomic
def record_poll(switch_id, hostname, datos):
    # Revalidar inventario: pudo cambiar mientras la consulta estaba en vuelo.
    switch = Switch.objects.filter(pk=switch_id, hostname=hostname, activo=True, plantel__activo=True).first()
    if switch is None:
        return
    now = timezone.now()
    previous_uptime = switch.uptime_segundos
    current_uptime = datos.get('uptime_segundos') if datos else None
    reboot_detected = (
        previous_uptime is not None and current_uptime is not None
        and current_uptime < previous_uptime
        # Versiones anteriores guardaban centésimas de segundo: el primer
        # sondeo con segundos no es un reinicio.
        and not abs(current_uptime * 100 - previous_uptime) <= previous_uptime * 0.01 + 100_000
    )
    Switch.objects.filter(pk=switch.pk).update(
        ultima_consulta=now, lectura_correcta=datos is not None,
        **{field: datos.get(field) if datos else None for field in (
            'cpu_5s','cpu_1m','cpu_5m','memoria_usada_pct','memoria_total_bytes',
            'memoria_usada_bytes','uptime_segundos')})
    if datos:
        Switch.objects.filter(pk=switch.pk).update(
            **{field: datos[field] for field in ('modelo', 'firmware') if field in datos},
            # Sin la MIB correspondiente quedan vacíos: no se muestran lecturas antiguas.
            **{field: datos.get(field) for field in SWITCH_EXTRA_FIELDS})
        if reboot_detected:
            Switch.objects.filter(pk=switch.pk).update(ultimo_reinicio=now)
    if datos is None:
        # Puertos no observados dejan de mostrar métricas antiguas como actuales.
        switch.puertos.update(estado_operativo='unknown', errores_entrada=None, errores_salida=None,
                              errores_crc=None, errores_nuevos=None)
        return

    existing = {port.indice: port for port in switch.puertos.all()}
    seen, to_create, to_update, events = set(), [], [], []
    for item in datos.get('interfaces', []):
        indice = item.get('indice')
        if not isinstance(indice, int) or indice <= 0:
            raise ValueError('La interfaz requiere un ifIndex válido')
        if indice in seen:
            continue
        seen.add(indice)
        port = existing.get(indice)
        previous = tuple(getattr(port, field) for field in ERROR_FIELDS) if port else (None,) * 3
        previous_traffic = (port.octetos_entrada, port.octetos_salida, port.actualizado) if port else (None,) * 3
        previous_state = port.estado_operativo if port else None
        if port is None:
            port = Puerto(switch=switch, indice=indice)
            to_create.append(port)
        else:
            to_update.append(port)
        port.nombre = item['nombre']
        port.descripcion = item.get('descripcion')
        port.estado_operativo = item.get('estado', 'unknown')
        for field in ERROR_FIELDS:
            setattr(port, field, item.get(field))
        port.errores_nuevos = new_errors(previous, tuple(item.get(field) for field in ERROR_FIELDS))
        if port.errores_nuevos:
            port.ultimo_error = now
        port.es_fisico = is_physical_interface(port.nombre)
        port.actualizado = now
        # Los metadatos de red son opcionales; una fuente antigua o una prueba
        # sin ellos no debe borrar la clasificación manual del puerto. Se
        # conservan octetos anteriores para calcular el delta de tráfico.
        for field in OPTIONAL_FIELDS:
            if field in item:
                setattr(port, field, item[field])
        traffic(port, previous_traffic, now)
        link_history(port, previous_state, item, now, events)

    for indice, port in existing.items():
        if indice not in seen:
            port.estado_operativo = 'unknown'
            port.errores_entrada = port.errores_salida = port.errores_crc = port.errores_nuevos = None
            to_update.append(port)

    Puerto.objects.bulk_create(to_create)
    Puerto.objects.bulk_update(to_update, UPDATE_FIELDS)
    EventoPuerto.objects.bulk_create(events)
    EventoPuerto.objects.filter(puerto__switch=switch, momento__lt=now - EVENT_RETENTION).delete()

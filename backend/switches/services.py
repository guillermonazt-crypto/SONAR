from django.db import transaction
from django.utils import timezone
from .interfaces import is_physical_interface
from .models import Switch, Puerto

ERROR_FIELDS = ('errores_entrada', 'errores_salida', 'errores_crc')
OPTIONAL_FIELDS = ('es_trunk', 'ip_equipo', 'mac_equipo', 'mac_telefono', 'dhcp', 'vlan', 'voice_vlan',
                   'octetos_entrada', 'octetos_salida')
UPDATE_FIELDS = ['nombre', 'descripcion', 'estado_operativo', *ERROR_FIELDS, 'errores_nuevos',
                 'ultimo_error', 'es_fisico', 'actualizado', *OPTIONAL_FIELDS]


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
    )
    Switch.objects.filter(pk=switch.pk).update(
        ultima_consulta=now, lectura_correcta=datos is not None,
        **{field: datos.get(field) if datos else None for field in (
            'cpu_5s','cpu_1m','cpu_5m','memoria_usada_pct','memoria_total_bytes',
            'memoria_usada_bytes','uptime_segundos')})
    if datos:
        Switch.objects.filter(pk=switch.pk).update(
            **{field: datos[field] for field in ('modelo', 'firmware') if field in datos})
        if reboot_detected:
            Switch.objects.filter(pk=switch.pk).update(ultimo_reinicio=now)
    if datos is None:
        # Puertos no observados dejan de mostrar métricas antiguas como actuales.
        switch.puertos.update(estado_operativo='unknown', errores_entrada=None, errores_salida=None,
                              errores_crc=None, errores_nuevos=None)
        return

    existing = {port.indice: port for port in switch.puertos.all()}
    seen, to_create, to_update = set(), [], []
    for item in datos.get('interfaces', []):
        indice = item.get('indice')
        if not isinstance(indice, int) or indice <= 0:
            raise ValueError('La interfaz requiere un ifIndex válido')
        if indice in seen:
            continue
        seen.add(indice)
        port = existing.get(indice)
        previous = tuple(getattr(port, field) for field in ERROR_FIELDS) if port else (None,) * 3
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

    for indice, port in existing.items():
        if indice not in seen:
            port.estado_operativo = 'unknown'
            port.errores_entrada = port.errores_salida = port.errores_crc = port.errores_nuevos = None
            to_update.append(port)

    Puerto.objects.bulk_create(to_create)
    Puerto.objects.bulk_update(to_update, UPDATE_FIELDS)

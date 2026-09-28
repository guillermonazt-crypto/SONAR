from django.db import transaction
from django.utils import timezone
from .models import Switch, Puerto

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
    # Puertos no observados dejan de mostrar métricas antiguas como actuales.
    # Sólo invalidamos el estado operativo y los errores mientras llega la
    # nueva lectura. Conservamos octetos y velocidad anterior para calcular
    # el delta de tráfico entre dos sondeos consecutivos.
    switch.puertos.update(estado_operativo='unknown', errores_entrada=None, errores_salida=None,
                          errores_crc=None)
    if datos is None:
        return
    for item in datos.get('interfaces', []):
        indice = item.get('indice')
        if not isinstance(indice, int) or indice <= 0:
            raise ValueError('La interfaz requiere un ifIndex válido')
        defaults = dict(
            nombre=item['nombre'], descripcion=item.get('descripcion'),
            es_trunk=item.get('es_trunk', False), estado_operativo=item.get('estado', 'unknown'),
            errores_entrada=item.get('errores_entrada'), errores_salida=item.get('errores_salida'),
            errores_crc=item.get('errores_crc'))
        # Los metadatos de red son opcionales; una fuente antigua o una prueba
        # sin ellos no debe borrar la clasificación manual del puerto.
        for field in ('ip_equipo', 'mac_equipo', 'mac_telefono', 'dhcp', 'vlan', 'voice_vlan'):
            if field in item:
                defaults[field] = item[field]
        for field in ('octetos_entrada', 'octetos_salida'):
            if field in item:
                defaults[field] = item[field]
        Puerto.objects.update_or_create(switch=switch, indice=indice, defaults=defaults)

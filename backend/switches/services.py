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
    Switch.objects.filter(pk=switch.pk).update(
        ultima_consulta=now, lectura_correcta=datos is not None,
        **{field: datos.get(field) if datos else None for field in ('cpu_5s','cpu_1m','cpu_5m')})
    # Puertos no observados dejan de mostrar métricas antiguas como actuales.
    switch.puertos.update(estado_operativo='unknown', errores_entrada=None, errores_salida=None, errores_crc=None)
    if datos is None:
        return
    for item in datos.get('interfaces', []):
        indice = item.get('indice')
        if not isinstance(indice, int) or indice <= 0:
            raise ValueError('La interfaz requiere un ifIndex válido')
        Puerto.objects.update_or_create(switch=switch, indice=indice, defaults=dict(
            nombre=item['nombre'], estado_operativo=item.get('estado', 'unknown'),
            errores_entrada=item.get('errores_entrada'), errores_salida=item.get('errores_salida'),
            errores_crc=item.get('errores_crc')))

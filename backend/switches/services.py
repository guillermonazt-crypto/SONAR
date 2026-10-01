from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from .interfaces import is_physical_interface
from .optics import update_baseline
from .models import EstadoMonitoreo, EventoPuerto, Switch, Puerto

ERROR_FIELDS = ('errores_entrada', 'errores_salida', 'errores_crc')
OPTIONAL_FIELDS = ('es_trunk', 'ip_equipo', 'mac_equipo', 'mac_telefono', 'dhcp', 'vlan', 'voice_vlan',
                   'octetos_entrada', 'octetos_salida', 'vecino_nombre', 'vecino_puerto',
                   'vecino_plataforma', 'vecino_ip', 'vecino_tipo', 'velocidad_mbps', 'poe_estado', 'poe_mw')
UPDATE_FIELDS = ['nombre', 'descripcion', 'estado_operativo', *ERROR_FIELDS, 'errores_nuevos',
                 'ultimo_error', 'es_fisico', 'actualizado', *OPTIONAL_FIELDS,
                 'bps_entrada', 'bps_salida', 'uso_pct', 'ultimo_cambio', 'ultimo_activo', 'optica']
SWITCH_EXTRA_FIELDS = ('temperatura_c', 'hardware', 'poe_presupuesto_w', 'poe_consumo_w')
EVENT_RETENTION = timedelta(days=7)
# Más tiempo que esto entre dos lecturas exitosas (SONAR apagado o el switch sin
# responder): los contadores acumulados no se atribuyen al sondeo actual.
MAX_POLL_GAP = timedelta(minutes=10)
# sysUpTime es TimeTicks de 32 bits: vuelve a cero cada 2^32 centésimas (~497 días).
UPTIME_WRAP_SECONDS = 2 ** 32 // 100
# Holgura para comparar uptime con el tiempo transcurrido entre sondeos.
UPTIME_SLACK_SECONDS = 120
LINK_STATES = ('up', 'down')


def detect_reboot(previous_uptime, current_uptime, elapsed):
    """True si el equipo arrancó después de la lectura exitosa anterior.

    `elapsed` son los segundos desde esa lectura (None si se desconoce). Se
    compara el uptime esperado (anterior + transcurrido) con el leído, así que
    también se detecta un reinicio ocurrido con SONAR apagado aunque el uptime
    nuevo ya supere al anterior. No cuentan la vuelta a cero de sysUpTime
    (~497 días) ni el cambio de unidades de versiones anteriores.
    """
    if previous_uptime is None or current_uptime is None:
        return False
    if elapsed is None:
        # Versiones anteriores guardaban centésimas de segundo: el primer sondeo con segundos no es un reinicio.
        legacy = abs(current_uptime * 100 - previous_uptime) <= previous_uptime * 0.01 + 100_000
        return current_uptime < previous_uptime and not legacy
    # El reloj del equipo y el del servidor derivan un poco en pausas largas.
    slack = UPTIME_SLACK_SECONDS + elapsed * 0.001
    if abs(current_uptime - (previous_uptime / 100 + elapsed)) <= slack:
        return False  # El valor anterior estaba en centésimas.
    expected = previous_uptime + elapsed
    if expected >= UPTIME_WRAP_SECONDS and abs((expected - UPTIME_WRAP_SECONDS) - current_uptime) <= slack:
        return False
    return current_uptime < expected - slack


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
    known_change = item.get('ultimo_cambio_hace_s')
    if previous_state in LINK_STATES and state in LINK_STATES and previous_state != state:
        # ifLastChange da el momento real del cambio si ocurrió con SONAR apagado.
        port.ultimo_cambio = now - timedelta(seconds=known_change) if known_change is not None else now
        events.append(EventoPuerto(puerto=port, estado=state, momento=now))
    elif known_change is not None and (port.ultimo_cambio is None or previous_state not in LINK_STATES):
        # Primer sondeo, o el anterior no respondió: ifLastChange dice desde cuándo el puerto está así.
        port.ultimo_cambio = now - timedelta(seconds=known_change)
    if state == 'down' and port.ultimo_activo is None and port.ultimo_cambio:
        port.ultimo_activo = port.ultimo_cambio


OPTIC_FIELDS = (('rx_dbm', 'rx_dbm'), ('tx_dbm', 'tx_dbm'), ('temperatura', 'temp_c'), ('voltaje_v', 'voltaje_v'),
                ('bias_ma', 'bias_ma'), ('estado', 'estado'), ('sin_senal', 'sin_senal'), ('admin', 'admin'),
                ('umbrales', 'umbrales'))


def optic_reading(previous, item, now):
    """Lectura DOM a guardar en Puerto.optica, con la línea base de RX al día."""
    reading = {field: item.get(source) for field, source in OPTIC_FIELDS}
    reading['umbrales'] = reading['umbrales'] or {}
    reading['rx_base_dbm'] = update_baseline(previous, reading, now)
    reading['time'] = now.isoformat()
    return reading


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


def mark_worker_started(now=None):
    """El worker arrancó: abre el periodo de gracia (health.GRACE_MINUTES)."""
    now = now or timezone.now()
    EstadoMonitoreo.objects.update_or_create(pk=1, defaults=dict(iniciado=now, latido=now))


def worker_heartbeat(now=None):
    """Ciclo de sondeo terminado."""
    now = now or timezone.now()
    EstadoMonitoreo.objects.update_or_create(pk=1, defaults=dict(latido=now))


@transaction.atomic
def record_poll(switch_id, hostname, datos):
    # Revalidar inventario: pudo cambiar mientras la consulta estaba en vuelo.
    switch = Switch.objects.filter(pk=switch_id, hostname=hostname, activo=True, plantel__activo=True).first()
    if switch is None:
        return
    now = timezone.now()
    previous_ok = switch.ultima_lectura_exitosa or (switch.ultima_consulta if switch.lectura_correcta else None)
    elapsed = (now - previous_ok).total_seconds() if previous_ok else None
    # Tras una pausa (o la primera vez) la lectura es sólo la nueva base de los contadores.
    resumed = elapsed is None or elapsed > MAX_POLL_GAP.total_seconds()
    current_uptime = datos.get('uptime_segundos') if datos else None
    reboot_detected = detect_reboot(switch.uptime_segundos, current_uptime, elapsed)
    Switch.objects.filter(pk=switch.pk).update(
        ultima_consulta=now, lectura_correcta=datos is not None,
        **({'ultima_lectura_exitosa': now} if datos else {}),
        **{field: datos.get(field) if datos else None for field in (
            'cpu_5s','cpu_1m','cpu_5m','memoria_usada_pct','memoria_total_bytes',
            'memoria_usada_bytes','uptime_segundos')})
    if datos:
        Switch.objects.filter(pk=switch.pk).update(
            **{field: datos[field] for field in ('modelo', 'firmware') if field in datos},
            # Sin la MIB correspondiente quedan vacíos: no se muestran lecturas antiguas.
            **{field: datos.get(field) for field in SWITCH_EXTRA_FIELDS})
        if reboot_detected:
            # El arranque real, no el momento en que SONAR lo notó (pudo estar apagado).
            Switch.objects.filter(pk=switch.pk).update(ultimo_reinicio=now - timedelta(seconds=current_uptime))
    if datos is None:
        # Puertos no observados dejan de mostrar métricas antiguas como actuales.
        switch.puertos.update(estado_operativo='unknown', errores_entrada=None, errores_salida=None,
                              errores_crc=None, errores_nuevos=None)
        return

    # None: la consulta DOM falló y se conservan las lecturas anteriores.
    optics = datos.get('transceptores')
    optics_by_port = None if optics is None else {
        (item.get('indice') or item.get('interfaz')): item for item in optics}
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
        port.errores_nuevos = None if resumed else new_errors(previous, tuple(item.get(field) for field in ERROR_FIELDS))
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
        # Un promedio de horas no es el tráfico actual: tras una pausa se espera al siguiente sondeo.
        traffic(port, (None,) * 3 if resumed else previous_traffic, now)
        link_history(port, previous_state, item, now, events)
        if optics_by_port is not None:
            optic = optics_by_port.get(indice) or optics_by_port.get(port.nombre)
            port.optica = optic_reading(port.optica, optic, now) if optic else None

    for indice, port in existing.items():
        if indice not in seen:
            port.estado_operativo = 'unknown'
            port.errores_entrada = port.errores_salida = port.errores_crc = port.errores_nuevos = None
            to_update.append(port)

    Puerto.objects.bulk_create(to_create)
    Puerto.objects.bulk_update(to_update, UPDATE_FIELDS)
    EventoPuerto.objects.bulk_create(events)
    EventoPuerto.objects.filter(puerto__switch=switch, momento__lt=now - EVENT_RETENTION).delete()

# sonar/collector/dom.py
#
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Digital Optical Monitoring (DOM) de transceptores SFP/SFP+ leído de
# CISCO-ENTITY-SENSOR-MIB (o ENTITY-SENSOR-MIB estándar) y ENTITY-MIB.
# Aquí sólo hay conversiones puras: la consulta SNMP vive en snmp_collector.

import math

from sonar.collector.extras import mentions_interface

# Columnas de entSensorValueTable (CISCO-ENTITY-SENSOR-MIB). Ojo: la entrada es
# ...91.1.1.1.1 y las columnas cuelgan de ella (...91.1.1.1.1.N).
OID_CISCO_SENSOR = {
    'type': '1.3.6.1.4.1.9.9.91.1.1.1.1.1',
    'scale': '1.3.6.1.4.1.9.9.91.1.1.1.1.2',
    'precision': '1.3.6.1.4.1.9.9.91.1.1.1.1.3',
    'value': '1.3.6.1.4.1.9.9.91.1.1.1.1.4',
    'status': '1.3.6.1.4.1.9.9.91.1.1.1.1.5',
}
# entPhySensorTable (ENTITY-SENSOR-MIB, RFC 3433): equipos no Cisco.
OID_STD_SENSOR = {
    'type': '1.3.6.1.2.1.99.1.1.1.1',
    'scale': '1.3.6.1.2.1.99.1.1.1.2',
    'precision': '1.3.6.1.2.1.99.1.1.1.3',
    'value': '1.3.6.1.2.1.99.1.1.1.4',
    'status': '1.3.6.1.2.1.99.1.1.1.5',
}
# entSensorThresholdTable, índice entPhysicalIndex.entSensorThresholdIndex.
OID_THRESHOLD = {
    'severity': '1.3.6.1.4.1.9.9.91.1.2.1.1.2',
    'relation': '1.3.6.1.4.1.9.9.91.1.2.1.1.3',
    'value': '1.3.6.1.4.1.9.9.91.1.2.1.1.4',
}
OID_ENTITY = {
    'name': '1.3.6.1.2.1.47.1.1.1.1.7',
    'contained_in': '1.3.6.1.2.1.47.1.1.1.1.4',
    # entAliasMappingIdentifier.<entPhysicalIndex>.0 = ifIndex OID de IF-MIB.
    'alias': '1.3.6.1.2.1.47.1.3.2.1.2',
}
OID_IF_ADMIN = '1.3.6.1.2.1.2.2.1.7'

# SensorDataType (idéntico en ambas MIB).
TYPE_VOLTS_DC, TYPE_AMPERES, TYPE_WATTS, TYPE_CELSIUS, TYPE_DBM = 4, 5, 6, 8, 14
POWER_TYPES = (TYPE_DBM, TYPE_WATTS)
# SensorDataScale -> exponente de 10 (yocto(1) ... units(9) ... yotta(17)).
SCALE_EXPONENT = {index: (index - 9) * 3 for index in range(1, 18)}
# entSensorStatus / entPhySensorOperStatus.
STATUS_OK, STATUS_UNAVAILABLE, STATUS_NONOPERATIONAL = 1, 2, 3
# CatalystSensorThresholdSeverity: minor(10) es aviso; major(20)/critical(30), alarma.
SEVERITY_ALARM = 20
RELATION_LOW, RELATION_HIGH = (1, 2), (3, 4)
# Los módulos Cisco informan -40 dBm (0 mW) cuando no reciben luz.
NO_SIGNAL_DBM = -40.0


def sensor_value(raw, scale, precision):
    """Valor real de un sensor: raw × 10^escala / 10^precisión.

    La escala es el enum SensorDataScale (9 = unidades, 8 = mili), no un exponente.
    """
    if raw is None:
        return None
    exponent = SCALE_EXPONENT.get(scale, 0) - (precision or 0)
    return raw * (10.0 ** exponent)


def watts_to_dbm(watts):
    """Algunas plataformas informan la potencia óptica en W/mW en lugar de dBm."""
    if watts is None:
        return None
    if watts <= 0:
        return NO_SIGNAL_DBM
    return max(NO_SIGNAL_DBM, 10 * math.log10(watts * 1000))


def if_index_from_alias(value):
    """entAliasMappingIdentifier ('1.3.6.1.2.1.2.2.1.1.10125') -> 10125."""
    text = str(value or '').strip()
    prefix = '1.3.6.1.2.1.2.2.1.1.'
    if text.startswith(prefix):
        tail = text[len(prefix):]
        return int(tail) if tail.isdigit() else None
    return None


def _kind(sensor_type, name):
    """Qué mide el sensor dentro del transceptor: rx, tx, temp, voltaje o bias."""
    label = f' {(name or "").lower()} '
    if sensor_type in POWER_TYPES:
        if any(word in label for word in ('receive', ' rx ', 'rx power', 'optical rx')):
            return 'rx'
        if any(word in label for word in ('transmit', ' tx ', 'tx power', 'optical tx')):
            return 'tx'
        return None
    if sensor_type == TYPE_CELSIUS:
        return 'temp'
    if sensor_type == TYPE_VOLTS_DC:
        return 'voltaje'
    if sensor_type == TYPE_AMPERES:
        return 'bias'
    return None


def optic_sensor_indexes(types, names):
    """Índices de sensores de potencia óptica (RX/TX); sin ellos no hay DOM."""
    return [index for index, sensor_type in types.items()
            if sensor_type in POWER_TYPES and _kind(sensor_type, names.get(index)) in ('rx', 'tx')]


def _in_units(kind, sensor_type, value):
    """Unidades de SONAR: dBm, °C, V y mA."""
    if value is None:
        return None
    if kind in ('rx', 'tx'):
        return round(watts_to_dbm(value) if sensor_type == TYPE_WATTS else value, 2)
    if kind == 'bias':
        return round(value * 1000, 2)
    return round(value, 2)


def sensor_thresholds(rows, sensor):
    """Umbrales publicados por el switch para un sensor, en unidades de SONAR.

    rows: [(severity, relation, raw_value)]. Devuelve {alta_alarma, alta_aviso,
    baja_aviso, baja_alarma} con las claves disponibles.
    """
    result = {}
    kind = _kind(sensor['type'], sensor.get('name'))
    for severity, relation, raw in rows:
        if raw is None or relation not in RELATION_LOW + RELATION_HIGH:
            continue
        value = sensor_value(raw, sensor.get('scale'), sensor.get('precision'))
        if sensor['type'] == TYPE_WATTS and value is not None and value <= 0:
            continue
        value = _in_units(kind, sensor['type'], value)
        side = 'alta' if relation in RELATION_HIGH else 'baja'
        level = 'alarma' if (severity or 0) >= SEVERITY_ALARM else 'aviso'
        key = f'{side}_{level}'
        # Varias filas del mismo tipo: la más estricta de alarma, la más temprana de aviso.
        previous = result.get(key)
        if previous is None:
            result[key] = value
        elif side == 'alta':
            result[key] = min(previous, value)
        else:
            result[key] = max(previous, value)
    return result


def build_transceivers(sensors, thresholds, parents, parent_names, parent_ifindex, interfaces, admin_status=None):
    """Agrupa los sensores DOM por puerto.

    sensors: {índice: {type, scale, precision, value, status, name}} (value crudo).
    thresholds: {índice: [(severity, relation, raw)]}.
    parents: {índice sensor: índice del transceptor (entPhysicalContainedIn)}.
    parent_names / parent_ifindex: {índice del transceptor: nombre / ifIndex}.
    interfaces: lista del colector [{indice, nombre, estado}].
    admin_status: {ifIndex: 1 up | 2 down}.
    """
    admin_status = admin_status or {}
    by_index = {item['indice']: item for item in interfaces}
    by_name = {item['nombre']: item for item in interfaces}
    optic_parents = {parents.get(index) for index in optic_sensor_indexes(
        {i: s['type'] for i, s in sensors.items()}, {i: s.get('name') for i, s in sensors.items()})}
    optic_parents.discard(None)
    result = {}
    for index, sensor in sorted(sensors.items()):
        parent = parents.get(index)
        kind = _kind(sensor['type'], sensor.get('name'))
        if kind is None or parent not in optic_parents:
            continue  # Sensores del chasis (entrada de aire, fuentes) no son DOM.
        port = (by_index.get(parent_ifindex.get(parent)) or by_name.get(parent_names.get(parent, ''))
                or next((item for item in interfaces
                         if mentions_interface(sensor.get('name') or '', item['nombre'])), None))
        if port is None:
            continue
        slot = result.setdefault(port['nombre'], dict(
            interfaz=port['nombre'], indice=port['indice'], rx_dbm=None, tx_dbm=None, temp_c=None,
            voltaje_v=None, bias_ma=None, estado='ok', sin_senal=False, oper=port.get('estado'),
            admin={1: 'up', 2: 'down', 3: 'testing'}.get(admin_status.get(port['indice'])), umbrales={}))
        status = sensor.get('status')
        if status == STATUS_NONOPERATIONAL:
            slot['estado'] = 'alerta'
        if status == STATUS_UNAVAILABLE:
            continue  # El switch no tiene lectura válida (p. ej. láser apagado).
        value = _in_units(kind, sensor['type'],
                          sensor_value(sensor.get('value'), sensor.get('scale'), sensor.get('precision')))
        if value is None:
            continue
        field = {'rx': 'rx_dbm', 'tx': 'tx_dbm', 'temp': 'temp_c', 'voltaje': 'voltaje_v', 'bias': 'bias_ma'}[kind]
        # Ópticas multicanal (QSFP): se conserva el carril más débil.
        if kind in ('rx', 'tx') and slot[field] is not None:
            value = min(value, slot[field])
        slot[field] = value
        limits = sensor_thresholds(thresholds.get(index, []), sensor)
        if limits and kind in ('rx', 'tx', 'temp'):
            slot['umbrales'][kind] = limits
    for slot in result.values():
        if slot['rx_dbm'] is not None and slot['rx_dbm'] <= NO_SIGNAL_DBM + 0.05:
            slot['sin_senal'] = True
    return [slot for slot in result.values()
            if any(slot[key] is not None for key in ('rx_dbm', 'tx_dbm', 'temp_c'))]

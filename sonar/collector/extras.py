# sonar/collector/extras.py
#
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Datos adicionales por SNMP: vecinos CDP/LLDP (y su tipo), velocidad y último cambio de cada
# puerto, PoE y salud física (temperatura, ventiladores, fuentes).
#
# Cada función recibe `walk(oid) -> [(sufijo, valor)]` para poder probarse sin
# equipos reales. Si un agente no publica una MIB, la función devuelve vacío y
# no inventa valores.
import re

from sonar.utils.logger import get_logger

log = get_logger(__name__)

OID_CDP = {
    'address': '1.3.6.1.4.1.9.9.23.1.2.1.1.4',
    'device': '1.3.6.1.4.1.9.9.23.1.2.1.1.6',
    'port': '1.3.6.1.4.1.9.9.23.1.2.1.1.7',
    'platform': '1.3.6.1.4.1.9.9.23.1.2.1.1.8',
    'capabilities': '1.3.6.1.4.1.9.9.23.1.2.1.1.9',
}
# LLDP-MIB (IEEE 802.1AB): lldpRemTable se indexa por timeMark.localPortNum.remIndex.
OID_LLDP = {
    'name': '1.0.8802.1.1.2.1.4.1.1.9',          # lldpRemSysName
    'port': '1.0.8802.1.1.2.1.4.1.1.7',          # lldpRemPortId
    'port_descr': '1.0.8802.1.1.2.1.4.1.1.8',    # lldpRemPortDesc
    'descr': '1.0.8802.1.1.2.1.4.1.1.10',        # lldpRemSysDesc
    'capabilities': '1.0.8802.1.1.2.1.4.1.1.12', # lldpRemSysCapEnabled (BITS)
}
OID_LLDP_LOCAL_PORT = {
    'id': '1.0.8802.1.1.2.1.3.7.1.3',            # lldpLocPortId (suele ser el nombre corto)
    'descr': '1.0.8802.1.1.2.1.3.7.1.4',         # lldpLocPortDesc
}
OID_LLDP_MAN_ADDR = '1.0.8802.1.1.2.1.4.2.1.3'   # lldpRemManAddrIfSubtype; la IP va en el índice

# cdpCacheCapabilities: máscara de 32 bits.
CDP_ROUTER, CDP_SWITCH, CDP_PHONE = 0x01, 0x08, 0x80
# LLDP SystemCapabilitiesMap (BITS: el bit 0 es el más significativo del primer byte).
LLDP_BRIDGE, LLDP_WLAN_AP, LLDP_ROUTER, LLDP_TELEPHONE = 2, 3, 4, 5
PHONE_PATTERN = re.compile(r'phone|\bCP-\d|telefon|\bSEP[0-9A-F]{12}\b', re.I)
AP_PATTERN = re.compile(r'\bAIR-|aironet|access point|\bC91\d\dAX|\bCW91\d\d|\bAP\d{3,4}\b|\bMR\d\d\b|\bUAP\b', re.I)
NEIGHBOR_TYPES = ('telefono', 'ap', 'switch', 'router', 'otro')
OID_IF_EXTRA = {
    'high_speed': '1.3.6.1.2.1.31.1.1.1.15',   # Mbps
    'last_change': '1.3.6.1.2.1.2.2.1.9',      # TimeTicks (centésimas) desde el arranque
}
OID_POE_PORT = {
    'status': '1.3.6.1.2.1.105.1.1.1.6',       # pethPsePortDetectionStatus
    'consumption': '1.3.6.1.4.1.9.9.402.1.2.1.10',  # cpeExtPsePortPwrConsumption (mW)
}
OID_POE_MAIN = {
    'power': '1.3.6.1.2.1.105.1.3.1.1.2',      # pethMainPsePower (W)
    'consumption': '1.3.6.1.2.1.105.1.3.1.1.4',  # pethMainPseConsumptionPower (W)
}
OID_ENVMON = {
    'temp_descr': '1.3.6.1.4.1.9.9.13.1.3.1.2',
    'temp_value': '1.3.6.1.4.1.9.9.13.1.3.1.3',
    'temp_state': '1.3.6.1.4.1.9.9.13.1.3.1.6',
    'fan_descr': '1.3.6.1.4.1.9.9.13.1.4.1.2',
    'fan_state': '1.3.6.1.4.1.9.9.13.1.4.1.3',
    'supply_descr': '1.3.6.1.4.1.9.9.13.1.5.1.2',
    'supply_state': '1.3.6.1.4.1.9.9.13.1.5.1.3',
}

POE_STATUS = {1: 'disabled', 2: 'searching', 3: 'deliveringPower', 4: 'fault', 5: 'test', 6: 'otherFault'}
# CiscoEnvMonState: normal, warning, critical, shutdown, notPresent, notFunctioning.
ENV_STATE = {1: 'ok', 2: 'warning', 3: 'critical', 4: 'critical', 6: 'critical'}
SHORT_NAMES = (
    ('HundredGigE', 'Hu'), ('FortyGigabitEthernet', 'Fo'), ('TwentyFiveGigE', 'Twe'),
    ('TenGigabitEthernet', 'Te'), ('GigabitEthernet', 'Gi'), ('FastEthernet', 'Fa'),
)


def _int(value):
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _text(value):
    if hasattr(value, 'asOctets'):
        return bytes(value.asOctets()).decode('utf-8', errors='replace').strip()
    return str(value).strip()


def short_name(name):
    """'TenGigabitEthernet1/1/1' → 'Te1/1/1' (Cisco usa la forma corta en sensores)."""
    for long, short in SHORT_NAMES:
        if name.startswith(long):
            return short + name[len(long):]
    return name


def mentions_interface(label, name):
    """¿La etiqueta de un sensor habla de esta interfaz? Gi1/0/1 no debe coincidir con Gi1/0/10."""
    label = label.lower()
    for candidate in {name.lower(), short_name(name).lower()}:
        if re.search(rf'(?<![\w/]){re.escape(candidate)}(?![\d/])', label):
            return True
    return False


def _cdp_caps(value):
    if value is None:
        return None
    if hasattr(value, 'asOctets'):
        raw = bytes(value.asOctets())
        return int.from_bytes(raw, 'big') if raw else None
    return _int(value)


def _lldp_bits(value):
    """BITS de SNMP → conjunto de posiciones activas (0 = bit más alto del primer byte)."""
    if value is None or not hasattr(value, 'asOctets'):
        return None
    raw = bytes(value.asOctets())
    return {byte * 8 + bit for byte, octet in enumerate(raw) for bit in range(8) if octet & (0x80 >> bit)}


def clasificar_vecino(nombre=None, plataforma=None, cdp_caps=None, lldp_caps=None):
    """Tipo del equipo vecino: 'telefono', 'ap', 'switch', 'router' u 'otro'.

    Las capacidades anunciadas mandan (bit Phone de CDP; telephone y
    wlanAccessPoint de LLDP). CDP no tiene bit de AP, así que el modelo
    (AIR-..., C9120AXI, "Cisco IP Phone 8841") decide cuando falta.
    """
    text = ' '.join(filter(None, (nombre, plataforma)))
    lldp_caps = lldp_caps or set()
    if (cdp_caps or 0) & CDP_PHONE or LLDP_TELEPHONE in lldp_caps or PHONE_PATTERN.search(text):
        return 'telefono'
    if LLDP_WLAN_AP in lldp_caps or AP_PATTERN.search(text):
        return 'ap'
    if (cdp_caps or 0) & CDP_SWITCH or LLDP_BRIDGE in lldp_caps:
        return 'switch'
    if (cdp_caps or 0) & CDP_ROUTER or LLDP_ROUTER in lldp_caps:
        return 'router'
    return 'otro'


async def vecinos_cdp(walk):
    """{ifIndex: {vecino_nombre, vecino_puerto, vecino_plataforma, vecino_ip, vecino_tipo}}.

    None si la consulta falló (no se sabe nada); {} si no hay vecinos.
    """
    try:
        rows = {key: await walk(oid) for key, oid in OID_CDP.items()}
    except Exception as error:
        log.debug(f"CDP no disponible: {error}")
        return None
    by_key = {key: {tuple(suffix): value for suffix, value in values if len(suffix) >= 2}
              for key, values in rows.items()}
    result = {}
    for index, device in by_key['device'].items():
        name = _text(device)
        if not name:
            continue
        address = by_key['address'].get(index)
        raw = bytes(address.asOctets()) if hasattr(address, 'asOctets') else b''
        platform = _text(by_key['platform'].get(index, '')) or None
        kind = clasificar_vecino(name, platform, _cdp_caps(by_key['capabilities'].get(index)))
        # Un puerto con teléfono y PC detrás puede ver varios vecinos: el que no es teléfono gana.
        if index[0] in result and kind == 'telefono':
            continue
        result[index[0]] = {
            'vecino_nombre': name,
            'vecino_puerto': _text(by_key['port'].get(index, '')) or None,
            'vecino_plataforma': platform,
            'vecino_ip': '.'.join(str(byte) for byte in raw) if len(raw) == 4 else None,
            'vecino_tipo': kind,
        }
    return result


def _lldp_local_ports(local, interfaces):
    """lldpLocPortNum → ifIndex, por nombre de interfaz (Gi1/0/1 o GigabitEthernet1/0/1).

    Si el agente no publica la tabla local, se asume que el número es el ifIndex
    (así lo hace IOS/IOS-XE).
    """
    by_name = {}
    for item in interfaces:
        by_name[item['nombre'].lower()] = item['indice']
        by_name[short_name(item['nombre']).lower()] = item['indice']
    mapping = {}
    for key in ('id', 'descr'):
        for suffix, value in local.get(key, []):
            if suffix and suffix[-1] not in mapping:
                index = by_name.get(_text(value).lower())
                if index is not None:
                    mapping[suffix[-1]] = index
    known = {item['indice'] for item in interfaces}
    return lambda port: mapping.get(port, port if port in known else None)


async def vecinos_lldp(walk, interfaces):
    """Vecinos LLDP con el mismo formato que vecinos_cdp (equipos no Cisco, teléfonos y APs de otras marcas)."""
    try:
        names = await walk(OID_LLDP['name'])
        if not names:
            return {}
        rows = {key: await walk(oid) for key, oid in OID_LLDP.items() if key != 'name'}
        rows['name'] = names
        local = {key: await walk(oid) for key, oid in OID_LLDP_LOCAL_PORT.items()}
        addresses = await walk(OID_LLDP_MAN_ADDR)
    except Exception as error:
        log.debug(f"LLDP no disponible: {error}")
        return None
    by_key = {key: {tuple(suffix[-3:]): value for suffix, value in values if len(suffix) >= 3}
              for key, values in rows.items()}
    ip_by_remote = {}
    for suffix, _value in addresses:
        # timeMark.localPort.remIndex.subtipo(1 = IPv4).largo(4).a.b.c.d
        if len(suffix) >= 9 and suffix[3] == 1 and suffix[4] == 4:
            ip_by_remote.setdefault(tuple(suffix[:3]), '.'.join(str(part) for part in suffix[5:9]))
    to_if_index = _lldp_local_ports(local, interfaces)
    result = {}
    for index, value in by_key['name'].items():
        if_index = to_if_index(index[1])
        name = _text(value)
        if if_index is None or not name:
            continue
        platform = _text(by_key['descr'].get(index, '')).splitlines()[0:1]
        platform = platform[0][:255] if platform else None
        kind = clasificar_vecino(name, platform, lldp_caps=_lldp_bits(by_key['capabilities'].get(index)))
        if if_index in result and kind == 'telefono':
            continue
        port = _text(by_key['port_descr'].get(index, '')) or _text(by_key['port'].get(index, ''))
        result[if_index] = {
            'vecino_nombre': name,
            'vecino_puerto': port or None,
            'vecino_plataforma': platform or None,
            'vecino_ip': ip_by_remote.get(index),
            'vecino_tipo': kind,
        }
    return result


async def datos_puertos(walk, uptime_ticks=None):
    """{ifIndex: {velocidad_mbps, ultimo_cambio_hace_s}}.

    ifLastChange es el sysUpTime del último cambio; con el uptime actual se
    obtiene hace cuántos segundos ocurrió.
    """
    try:
        speeds = await walk(OID_IF_EXTRA['high_speed'])
        changes = await walk(OID_IF_EXTRA['last_change'])
    except Exception as error:
        log.debug(f"ifHighSpeed/ifLastChange no disponibles: {error}")
        return {}
    result = {}
    for suffix, value in speeds:
        speed = _int(value)
        if suffix and speed:
            result.setdefault(suffix[-1], {})['velocidad_mbps'] = speed
    if uptime_ticks:
        for suffix, value in changes:
            ticks = _int(value)
            if suffix and ticks is not None and 0 <= ticks <= uptime_ticks:
                result.setdefault(suffix[-1], {})['ultimo_cambio_hace_s'] = (uptime_ticks - ticks) // 100
    return result


def _poe_interface(group, port, interfaces):
    """Relaciona (grupo PSE, puerto) con la interfaz: Gi<g>/0/<p> o, en equipos sin stack, Gi0/<p>."""
    for item in interfaces:
        match = re.search(r'(\d+)/(\d+)/(\d+)$', item['nombre'])
        if match and (int(match[1]), int(match[2]), int(match[3])) == (group, 0, port):
            return item['indice']
    for item in interfaces:
        match = re.search(r'(?<!/)(\d+)/(\d+)$', item['nombre'])
        if match and int(match[1]) == group - 1 and int(match[2]) == port:
            return item['indice']
    return None


async def poe(walk, interfaces):
    """({ifIndex: {poe_estado, poe_mw}}, {poe_presupuesto_w, poe_consumo_w})."""
    try:
        status, consumption = (await walk(OID_POE_PORT['status']), await walk(OID_POE_PORT['consumption']))
        power, used = (await walk(OID_POE_MAIN['power']), await walk(OID_POE_MAIN['consumption']))
    except Exception as error:
        log.debug(f"PoE no disponible: {error}")
        return {}, {}
    consumption_by_port = {tuple(suffix[-2:]): _int(value) for suffix, value in consumption if len(suffix) >= 2}
    ports = {}
    for suffix, value in status:
        if len(suffix) < 2:
            continue
        group, port = suffix[-2:]
        index = _poe_interface(group, port, interfaces)
        if index is None:
            continue
        ports[index] = {
            'poe_estado': POE_STATUS.get(_int(value), 'unknown'),
            'poe_mw': consumption_by_port.get((group, port)),
        }
    budget = sum(_int(value) or 0 for _suffix, value in power)
    total = sum(_int(value) or 0 for _suffix, value in used)
    switch = {'poe_presupuesto_w': float(budget), 'poe_consumo_w': float(total)} if budget else {}
    return ports, switch


async def hardware(walk):
    """{'temperatura_c': máx °C, 'hardware': [{tipo, nombre, estado, valor}]} desde CISCO-ENVMON-MIB."""
    try:
        rows = {key: await walk(oid) for key, oid in OID_ENVMON.items()}
    except Exception as error:
        log.debug(f"CISCO-ENVMON-MIB no disponible: {error}")
        return {}
    table = {key: {suffix[-1]: value for suffix, value in values if suffix} for key, values in rows.items()}
    components = []
    for prefix, kind in (('temp', 'temperatura'), ('fan', 'ventilador'), ('supply', 'fuente')):
        for index, state in table[f'{prefix}_state'].items():
            code = _int(state)
            if code == 5:  # notPresent: bahía vacía
                continue
            value = _int(table['temp_value'].get(index)) if kind == 'temperatura' else None
            components.append({
                'tipo': kind,
                'nombre': _text(table[f'{prefix}_descr'].get(index, '')) or f'{kind} {index}',
                'estado': ENV_STATE.get(code, 'warning'),
                'valor': value,
            })
    if not components:
        return {}
    temperatures = [item['valor'] for item in components if item['tipo'] == 'temperatura' and item['valor'] is not None]
    return {'temperatura_c': float(max(temperatures)) if temperatures else None, 'hardware': components}


# BRIDGE-MIB. En Cisco la tabla MAC es por VLAN: fuera de la VLAN 1 sólo se ve
# consultando el contexto de cada VLAN (comunidad@vlan en v2c, vlan-N en v3).
OID_FDB_PORT = '1.3.6.1.2.1.17.4.3.1.2'      # dot1dTpFdbPort: MAC -> bridge port
OID_BRIDGE_IF = '1.3.6.1.2.1.17.1.4.1.2'     # dot1dBasePortIfIndex: bridge port -> ifIndex
OID_VTP_VLAN_STATE = '1.3.6.1.4.1.9.9.46.1.3.1.1.2'  # vtpVlanState: 1 = operativa
RESERVED_VLANS = {1, 1002, 1003, 1004, 1005}


def macs_por_interfaz(fdb_port, bridge_if):
    """[(mac, ifIndex)] a partir de las filas FDB y la relación bridge port → ifIndex."""
    bridge_to_if = {suffix[0]: _int(value) for suffix, value in bridge_if if suffix}
    entries = []
    for suffix, value in fdb_port:
        if len(suffix) < 6:
            continue
        if_index = bridge_to_if.get(_int(value))
        if if_index:
            entries.append((tuple(suffix[-6:]), if_index))
    return entries


def asignar_macs(entries):
    """{mac: ifIndex}: cada MAC en un solo puerto.

    Una MAC aparece también en el troncal o uplink por el que se aprende en otras
    VLAN; se queda en el puerto con menos MAC aprendidas (el de acceso).
    """
    load = {}
    for mac, if_index in set(entries):
        load[if_index] = load.get(if_index, 0) + 1
    best = {}
    for mac, if_index in sorted(set(entries)):
        current = best.get(mac)
        if current is None or load[if_index] < load[current]:
            best[mac] = if_index
    return best


async def vlans_con_equipos(walk, port_vlans, limit):
    """VLAN a consultar por contexto: las asignadas a puertos (datos y voz).

    Si el agente no publica la VLAN por puerto se usan las operativas de VTP.
    Nunca más de `limit`, para no alargar el ciclo en dominios VTP grandes.
    """
    vlans = {vlan for vlan in port_vlans if vlan and vlan not in RESERVED_VLANS and 1 < vlan < 4095}
    if not vlans:
        try:
            rows = await walk(OID_VTP_VLAN_STATE)
        except Exception as error:
            log.debug(f"vtpVlanState no disponible: {error}")
            rows = []
        vlans = {suffix[-1] for suffix, value in rows
                 if suffix and _int(value) == 1 and suffix[-1] not in RESERVED_VLANS}
    return sorted(vlans)[:limit]


async def tabla_mac(walk_vlan, port_vlans=(), limit=32):
    """{mac(tuple de 6 bytes): ifIndex} de la VLAN por defecto y de cada VLAN con equipos.

    `walk_vlan(oid, vlan=None)`: None es el contexto por defecto. Una VLAN que no
    responde se omite sin perder las demás.
    """
    entries = macs_por_interfaz(await walk_vlan(OID_FDB_PORT), await walk_vlan(OID_BRIDGE_IF))
    for vlan in await vlans_con_equipos(walk_vlan, port_vlans, limit):
        try:
            entries += macs_por_interfaz(await walk_vlan(OID_FDB_PORT, vlan), await walk_vlan(OID_BRIDGE_IF, vlan))
        except Exception as error:
            log.debug(f"Tabla MAC de la VLAN {vlan} no disponible: {error}")
    return asignar_macs(entries)


NO_NEIGHBOR = dict(vecino_nombre=None, vecino_puerto=None, vecino_plataforma=None, vecino_ip=None, vecino_tipo=None)
NO_POE = dict(poe_estado=None, poe_mw=None)


async def obtener_extras(walk, interfaces, uptime_ticks=None):
    """Junta todo lo anterior: datos por ifIndex para fusionar en interfaces y datos del switch.

    Cuando una MIB respondió, los puertos sin dato quedan en None: así un vecino
    desconectado o un equipo PoE retirado no se quedan guardados para siempre.
    """
    per_port = {item['indice']: {} for item in interfaces}
    cdp = await vecinos_cdp(walk)
    lldp = await vecinos_lldp(walk, interfaces)
    # CDP trae más detalle en equipo Cisco; LLDP cubre los puertos que CDP no ve.
    # Si CDP falló, sólo se actualizan los puertos que LLDP sí vio.
    neighbors = {**(lldp or {}), **(cdp or {})}
    clear_missing = cdp is not None
    poe_ports, poe_switch = await poe(walk, interfaces)
    for index, values in per_port.items():
        if clear_missing or index in neighbors:
            values.update(neighbors.get(index, NO_NEIGHBOR))
        if poe_switch:
            values.update(poe_ports.get(index, NO_POE))
    for index, values in (await datos_puertos(walk, uptime_ticks)).items():
        per_port.setdefault(index, {}).update(values)
    return per_port, {**poe_switch, **(await hardware(walk))}

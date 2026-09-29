# sonar/collector/snmp_collector.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Colector SNMP real para switches Cisco IOS-XE.
# Reemplaza al simulador cuando hay acceso real a los switches.

# pyrefly: ignore [missing-import]
from pysnmp.hlapi.asyncio import (
    SnmpEngine,
    CommunityData,
    UsmUserData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    get_cmd,
    walk_cmd,
)
import asyncio
import re

from sonar.utils.logger import get_logger
from sonar.utils import config

log = get_logger(__name__)


def _auth(community: str):
    """Credenciales SNMP según SNMP_VERSION: v3 (USM) o v2c (comunidad)."""
    if config.SNMP_VERSION == '3':
        return UsmUserData(config.SNMP_V3_USER, **config.snmp_v3_keys())
    return CommunityData(community, mpModel=1)

# ---------------------------------------------------------------------------
# OIDs de Cisco IOS-XE
# ---------------------------------------------------------------------------
OIDS_CPU = {
    'cpu_5m': '1.3.6.1.4.1.9.2.1.57.0',
    'cpu_1m': '1.3.6.1.4.1.9.2.1.56.0',
    'cpu_5s': '1.3.6.1.4.1.9.2.1.58.0',
}

OID_IF_TABLE = {
    'ifDescr':      '1.3.6.1.2.1.2.2.1.2',
    'ifType':       '1.3.6.1.2.1.2.2.1.3',
    'ifOperStatus': '1.3.6.1.2.1.2.2.1.8',
    'ifInErrors':   '1.3.6.1.2.1.2.2.1.14',
    'ifOutErrors':  '1.3.6.1.2.1.2.2.1.20',
    'ifInCRCErrs':  '1.3.6.1.2.1.16.1.1.1.8',
    'ifAlias':      '1.3.6.1.2.1.31.1.1.1.18',
    'ifHCInOctets': '1.3.6.1.2.1.31.1.1.1.6',
    'ifHCOutOctets': '1.3.6.1.2.1.31.1.1.1.10',
}

OID_NETWORK = {
    # ARP: ifIndex + IPv4 -> MAC and IPv4 address.
    'arp_mac': '1.3.6.1.2.1.4.22.1.2',
    'arp_ip': '1.3.6.1.2.1.4.22.1.3',
    # Bridge FDB MAC -> bridge port; bridge port -> ifIndex.
    'fdb_mac': '1.3.6.1.2.1.17.4.3.1.1',
    'fdb_port': '1.3.6.1.2.1.17.4.3.1.2',
    'bridge_if': '1.3.6.1.2.1.17.1.4.1.2',
    # Cisco access VLAN and CDP neighbor identity.
    'access_vlan': '1.3.6.1.4.1.9.9.68.1.2.2.1.2',
    'voice_vlan': '1.3.6.1.4.1.9.9.68.1.5.1.1.1',
    'cdp_device': '1.3.6.1.4.1.9.9.23.1.2.1.1.6',
}

OID_DEVICE = {
    'sys_descr': '1.3.6.1.2.1.1.1.0',
    'sys_uptime': '1.3.6.1.2.1.1.3.0',
    'model': '1.3.6.1.2.1.47.1.1.1.1.13',
}

OID_MEMORY = {
    'type': '1.3.6.1.2.1.25.2.3.1.2',
    'descr': '1.3.6.1.2.1.25.2.3.1.3',
    'units': '1.3.6.1.2.1.25.2.3.1.4',
    'size': '1.3.6.1.2.1.25.2.3.1.5',
    'used': '1.3.6.1.2.1.25.2.3.1.6',
}

OID_SENSOR = {
    'name': '1.3.6.1.2.1.47.1.1.1.1.7',
    'type': '1.3.6.1.2.1.99.1.1.1.1',
    'scale': '1.3.6.1.2.1.99.1.1.1.2',
    'precision': '1.3.6.1.2.1.99.1.1.1.3',
    'value': '1.3.6.1.2.1.99.1.1.1.4',
    'status': '1.3.6.1.2.1.99.1.1.1.5',
}
OID_CISCO_SENSOR = {
    'type': '1.3.6.1.4.1.9.9.91.1.1.1.1',
    'scale': '1.3.6.1.4.1.9.9.91.1.1.1.2',
    'precision': '1.3.6.1.4.1.9.9.91.1.1.1.3',
    'value': '1.3.6.1.4.1.9.9.91.1.1.1.4',
    'status': '1.3.6.1.4.1.9.9.91.1.1.1.5',
}

# Interfaces que corresponden a conectores del panel frontal.  Las interfaces
# de gestión, VLAN, stack y AppGigabit también aparecen en IF-MIB, pero no son
# puertos físicos que deban dibujarse en el inventario.
PHYSICAL_INTERFACE_RE = re.compile(
    r'^(?:FastEthernet0/\d+|GigabitEthernet0/[1-9]\d*|'
    r'GigabitEthernet\d+/\d+/\d+|TenGigabitEthernet\d+/\d+/\d+|'
    r'TwentyFiveGigE\d+/\d+/\d+|FortyGigabitEthernet\d+/\d+/\d+)$'
)
GENERIC_PHYSICAL_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_.-]*\d+/\d+(?:/\d+)?$')


def es_interfaz_fisica(nombre: str) -> bool:
    nombre = (nombre or '').strip()
    if any(token in nombre.lower() for token in ('management', 'appgigabit', 'bluetooth', 'stack', 'port-channel', 'portchannel', 'vlan', 'loopback', 'tunnel', 'null', 'unrouted')):
        return False
    if nombre.endswith('/0/0') or nombre.endswith('0/0'):
        return False
    if PHYSICAL_INTERFACE_RE.fullmatch(nombre):
        return True
    return bool(GENERIC_PHYSICAL_NAME_RE.fullmatch(nombre))


def _safe_int(value: str, default: int | None = None) -> int | None:
    """Convierte de forma segura un string a int."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


async def _get_oid(ip: str, community: str, oid: str) -> str | None:
    """
    Consulta un OID especifico y retorna su valor como string.
    """
    errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
        SnmpEngine(),
        _auth(community),
        await UdpTransportTarget.create((ip, config.SNMP_PORT),
                                       timeout=config.SNMP_TIMEOUT,
                                       retries=config.SNMP_RETRIES),
        ContextData(),
        ObjectType(ObjectIdentity(oid))
    )

    if errorIndication or errorStatus:
        return None

    for varBind in varBinds:
        return str(varBind[1])

    return None


async def _walk_oid(ip: str, community: str, oid: str) -> dict:
    """
    Hace un SNMP walk en una tabla y retorna un diccionario
    con el indice como clave y el valor como valor.
    """
    resultados = {}

    async for errorIndication, errorStatus, errorIndex, varBinds in walk_cmd(
        SnmpEngine(),
        _auth(community),
        await UdpTransportTarget.create((ip, config.SNMP_PORT),
                                       timeout=config.SNMP_TIMEOUT,
                                       retries=config.SNMP_RETRIES),
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
        lexicographicMode=False
    ):
        if errorIndication or errorStatus:
            break

        for varBind in varBinds:
            oid_str = str(varBind[0])
            indice  = oid_str.split('.')[-1]
            valor   = str(varBind[1])
            resultados[indice] = valor

    return resultados


async def _walk_oid_rows(ip: str, community: str, oid: str) -> list[tuple[list[int], object]]:
    """Conserva todo el índice de una tabla SNMP para correlacionar ARP/FDB/CDP."""
    rows = []
    async for error_indication, error_status, _error_index, var_binds in walk_cmd(
        SnmpEngine(), _auth(community),
        await UdpTransportTarget.create((ip, config.SNMP_PORT),
                                        timeout=config.SNMP_TIMEOUT,
                                        retries=config.SNMP_RETRIES),
        ContextData(), ObjectType(ObjectIdentity(oid)), lexicographicMode=False
    ):
        if error_indication or error_status:
            break
        for var_bind in var_binds:
            suffix = [int(part) for part in str(var_bind[0]).split('.')[len(oid.split('.')):]]
            rows.append((suffix, var_bind[1]))
    return rows


def _octets(value: object) -> bytes:
    if hasattr(value, 'asOctets'):
        return bytes(value.asOctets())
    if isinstance(value, bytes):
        return value
    return str(value).encode('latin1', errors='ignore')


def _format_mac(value: object) -> str | None:
    raw = _octets(value)
    if len(raw) != 6:
        return None
    return ':'.join(f'{byte:02x}' for byte in raw)


def _format_mac_text(value: str) -> str | None:
    compact = ''.join(ch for ch in value.upper() if ch in '0123456789ABCDEF')
    if len(compact) != 12:
        return None
    return ':'.join(compact[index:index + 2] for index in range(0, 12, 2)).lower()


async def obtener_red_interfaces(dispositivo: dict) -> dict[int, dict]:
    """Correlaciona VLAN, ARP, MAC aprendida y teléfonos CDP por ifIndex.

    DHCP snooping y voice VLAN no se rellenan con una suposición: quedan None
    cuando el agente SNMP no los publica.
    """
    ip = dispositivo['hostname']
    community = config.SNMP_COMMUNITY
    try:
        arp_mac, arp_ip, fdb_mac, fdb_port, bridge_if, access_vlan, voice_vlan, cdp_device = await asyncio.gather(
            *(_walk_oid_rows(ip, community, oid) for oid in OID_NETWORK.values())
        )
    except Exception as error:
        log.warning(f"[{dispositivo.get('name', ip)}] Metadatos de red no disponibles: {error}")
        return {}

    bridge_to_if = {suffix[0]: _safe_int(str(value)) for suffix, value in bridge_if if suffix}
    mac_to_bridge = {}
    for suffix, value in fdb_port:
        if len(suffix) >= 6:
            mac_to_bridge[tuple(suffix[-6:])] = _safe_int(str(value))
    mac_to_if = {
        mac: bridge_to_if.get(bridge)
        for mac, bridge in mac_to_bridge.items()
        if bridge is not None
    }
    ip_by_mac = {}
    for suffix, value in arp_mac:
        if len(suffix) >= 5:
            ip_by_mac[_octets(value)] = '.'.join(str(part) for part in suffix[-4:])
    # Prefer the address from the ARP index, which is robust on IOS-XE.
    for suffix, value in arp_ip:
        if len(suffix) >= 5:
            ip_by_mac.setdefault(_octets(value), '.'.join(str(part) for part in suffix[-4:]))

    result = {}
    for mac_bytes, if_index in mac_to_if.items():
        if if_index is None:
            continue
        mac = ':'.join(f'{part:02x}' for part in mac_bytes)
        item = result.setdefault(if_index, {'ips': [], 'macs': [], 'phones': []})
        if mac.startswith(('01:', '33:33:')):
            continue
        if mac not in item['macs']:
            item['macs'].append(mac)
        mac_bytes_value = bytes(mac_bytes)
        if mac_bytes_value in ip_by_mac and ip_by_mac[mac_bytes_value] not in item['ips']:
            item['ips'].append(ip_by_mac[mac_bytes_value])

    for suffix, value in cdp_device:
        if len(suffix) < 2:
            continue
        candidate = str(value)
        if not candidate.upper().startswith('SEP'):
            continue
        phone_mac = _format_mac_text(candidate[3:])
        if phone_mac:
            result.setdefault(suffix[0], {'ips': [], 'macs': [], 'phones': []})['phones'].append(phone_mac)

    vlan_by_if = {suffix[-1]: _safe_int(str(value)) for suffix, value in access_vlan if suffix}
    voice_vlan_by_if = {
        suffix[-1]: (None if _safe_int(str(value)) in (None, 0, 4096) else _safe_int(str(value)))
        for suffix, value in voice_vlan if suffix
    }
    return {
        if_index: {
            'ip_equipo': ', '.join(values['ips']) or None,
            'mac_equipo': ', '.join(values['macs']) or None,
            'mac_telefono': ', '.join(values['phones']) or None,
            'vlan': vlan_by_if.get(if_index),
            'voice_vlan': voice_vlan_by_if.get(if_index),
            'dhcp': None,
        }
        for if_index, values in result.items()
    } | {
        if_index: {'vlan': vlan, 'voice_vlan': voice_vlan_by_if.get(if_index), 'dhcp': None,
                   'ip_equipo': None, 'mac_equipo': None, 'mac_telefono': None}
        for if_index, vlan in vlan_by_if.items() if if_index not in result
    }


async def obtener_cpu(dispositivo: dict) -> dict | None:
    """
    Consulta el CPU del switch via SNMP en paralelo.
    """
    ip        = dispositivo['hostname']
    community = config.SNMP_COMMUNITY
    nombre    = dispositivo.get('name', ip)

    async def get_cpu_field(campo, oid):
        valor = await _get_oid(ip, community, oid)
        return campo, valor

    tareas = [get_cpu_field(campo, oid) for campo, oid in OIDS_CPU.items()]
    resultados = await asyncio.gather(*tareas)

    cpu = {}
    for campo, valor in resultados:
        cpu[campo] = _safe_int(valor)

    log.debug(f"[{nombre}] CPU → "
              f"5s={cpu['cpu_5s']}% "
              f"1m={cpu['cpu_1m']}% "
              f"5m={cpu['cpu_5m']}%")
    return cpu


async def obtener_sistema(dispositivo: dict) -> dict:
    """Obtiene uptime y memoria usando HOST-RESOURCES-MIB cuando existe."""
    ip = dispositivo['hostname']
    community = config.SNMP_COMMUNITY
    try:
        uptime_raw, descr, units, sizes, used = await asyncio.gather(
            _get_oid(ip, community, OID_DEVICE['sys_uptime']),
            _walk_oid(ip, community, OID_MEMORY['descr']),
            _walk_oid(ip, community, OID_MEMORY['units']),
            _walk_oid(ip, community, OID_MEMORY['size']),
            _walk_oid(ip, community, OID_MEMORY['used']),
        )
    except Exception as error:
        log.debug(f"[{dispositivo.get('name', ip)}] Memoria no disponible: {error}")
        return {'uptime_segundos': None, 'memoria_total_bytes': None,
                'memoria_usada_bytes': None, 'memoria_usada_pct': None}
    candidates = []
    for index, description in descr.items():
        label = str(description).lower()
        if any(word in label for word in ('memory', 'memoria', 'ram', 'physical')) and not any(word in label for word in ('flash', 'disk', 'storage')):
            total = (_safe_int(units.get(index), 1) or 1) * (_safe_int(sizes.get(index), 0) or 0)
            occupied = (_safe_int(units.get(index), 1) or 1) * (_safe_int(used.get(index), 0) or 0)
            if total > 0:
                candidates.append((total, occupied))
    total_bytes, used_bytes = max(candidates, default=(None, None))
    return {
        'uptime_segundos': _safe_int(uptime_raw),
        'memoria_total_bytes': total_bytes,
        'memoria_usada_bytes': used_bytes,
        'memoria_usada_pct': round(used_bytes * 100 / total_bytes, 2) if total_bytes and used_bytes is not None else None,
    }


async def obtener_optica(dispositivo: dict, interfaces: list[dict]) -> list[dict]:
    """Lee sensores DOM ópticos publicados por ENTITY-SENSOR-MIB.

    Muchos equipos no exponen DOM por SNMP; en ese caso devuelve una lista
    vacía y no inventa valores.
    """
    ip = dispositivo['hostname']
    community = config.SNMP_COMMUNITY
    try:
        names, types, scales, precisions, values, statuses = await asyncio.gather(
            *(_walk_oid_rows(ip, community, oid) for oid in OID_SENSOR.values())
        )
        # IOS-XE commonly exposes DOM through the Cisco enterprise MIB when
        # the standard ENTITY-SENSOR-MIB is empty.
        if not values:
            types, scales, precisions, values, statuses = await asyncio.gather(
                *(_walk_oid_rows(ip, community, oid) for oid in OID_CISCO_SENSOR.values())
            )
    except Exception as error:
        log.debug(f"[{dispositivo.get('name', ip)}] Sensores ópticos no disponibles: {error}")
        return []
    name_by_index = {suffix[-1]: str(value) for suffix, value in names if suffix}
    scale_by_index = {suffix[-1]: _safe_int(str(value), 0) or 0 for suffix, value in scales if suffix}
    precision_by_index = {suffix[-1]: _safe_int(str(value), 0) or 0 for suffix, value in precisions if suffix}
    status_by_index = {suffix[-1]: _safe_int(str(value)) for suffix, value in statuses if suffix}
    sensor_values = {}
    for suffix, value in values:
        if not suffix:
            continue
        index = suffix[-1]
        raw = _safe_int(str(value))
        if raw is None:
            continue
        sensor_values[index] = raw * (10 ** scale_by_index.get(index, 0)) / (10 ** precision_by_index.get(index, 0))
    result = {}
    for index, value in sensor_values.items():
        label = name_by_index.get(index, '').lower()
        match = next((item for item in interfaces if item['nombre'].lower() in label or label in item['nombre'].lower()), None)
        if not match:
            continue
        slot = result.setdefault(match['nombre'], {'interfaz': match['nombre'], 'rx_dbm': None, 'tx_dbm': None, 'temp_c': None, 'estado': 'ok'})
        if any(word in label for word in ('receive', ' rx', 'rx power', 'optical rx')):
            slot['rx_dbm'] = round(value, 3)
        elif any(word in label for word in ('transmit', ' tx', 'tx power', 'optical tx')):
            slot['tx_dbm'] = round(value, 3)
        elif any(word in label for word in ('temperature', 'temp')):
            slot['temp_c'] = round(value, 2)
        if status_by_index.get(index) not in (None, 1):
            slot['estado'] = 'alerta'
    return [item for item in result.values() if item['rx_dbm'] is not None or item['tx_dbm'] is not None or item['temp_c'] is not None]


async def obtener_identidad(dispositivo: dict) -> dict:
    """Obtiene el modelo físico y la versión IOS-XE del equipo."""
    ip = dispositivo['hostname']
    community = config.SNMP_COMMUNITY
    descr, model_rows = await asyncio.gather(
        _get_oid(ip, community, OID_DEVICE['sys_descr']),
        _walk_oid_rows(ip, community, OID_DEVICE['model']),
    )
    model = next((str(value) for _suffix, value in model_rows if str(value).strip()), None)
    version = None
    if descr:
        match = re.search(r'Version\s+([^,\s]+)', descr)
        version = match.group(1) if match else None
    return {'modelo': model or None, 'firmware': version}


async def obtener_interfaces(dispositivo: dict) -> list | None:
    """
    Consulta el estado y errores de todas las interfaces via SNMP walk en paralelo.
    """
    ip        = dispositivo['hostname']
    community = config.SNMP_COMMUNITY
    nombre    = dispositivo.get('name', ip)

    nombres = await _walk_oid(ip, community, OID_IF_TABLE['ifDescr'])
    if not nombres:
        return None

    tipos, estados, in_err, out_err, crc_err, aliases, in_octets, out_octets = await asyncio.gather(
        _walk_oid(ip, community, OID_IF_TABLE['ifType']),
        _walk_oid(ip, community, OID_IF_TABLE['ifOperStatus']),
        _walk_oid(ip, community, OID_IF_TABLE['ifInErrors']),
        _walk_oid(ip, community, OID_IF_TABLE['ifOutErrors']),
        _walk_oid(ip, community, OID_IF_TABLE['ifInCRCErrs']),
        _walk_oid(ip, community, OID_IF_TABLE['ifAlias']),
        _walk_oid(ip, community, OID_IF_TABLE['ifHCInOctets']),
        _walk_oid(ip, community, OID_IF_TABLE['ifHCOutOctets'])
    )

    interfaces = []
    for idx, nombre_if in nombres.items():
        # IF-MIB incluye VLAN, gestión, stack y otras interfaces internas.
        # ifType 6 = ethernetCsmacd, definido por IF-MIB y común a fabricantes.
        if _safe_int(tipos.get(idx)) != 6 or not es_interfaz_fisica(nombre_if):
            continue

        estado_raw = estados.get(idx)
        estado = {'1': 'up', '2': 'down', '3': 'testing', '4': 'unknown',
                  '5': 'dormant', '6': 'notPresent', '7': 'lowerLayerDown'}.get(estado_raw, 'unknown')

        interfaces.append({
            'indice':          int(idx),
            'nombre':          nombre_if,
            'estado':          estado,
            'errores_entrada': _safe_int(in_err.get(idx)),
            'errores_crc':     _safe_int(crc_err.get(idx)),
            'errores_salida':  _safe_int(out_err.get(idx)),
            'descripcion':     (aliases.get(idx) or '').strip() or None,
            'es_trunk':        bool(re.search(r'(?:GigabitEthernet0/[12]|(?:GigabitEthernet|TenGigabitEthernet|TwentyFiveGigE|FortyGigabitEthernet)\d+/1/\d+)$', nombre_if)),
            'octetos_entrada': _safe_int(in_octets.get(idx)),
            'octetos_salida':  _safe_int(out_octets.get(idx)),
        })

    log.debug(f"[{nombre}] {len(interfaces)} interfaces consultadas")
    return interfaces


async def obtener_datos_reales(dispositivo: dict) -> dict | None:
    """
    Consulta completa de un switch real via SNMP.
    Retorna el mismo formato que el simulador para
    que el resto del codigo no necesite cambios.

    Args:
        dispositivo: Diccionario del inventario con hostname, name, role, site

    Returns:
        Diccionario con cpu, interfaces y transceptores
    """
    nombre = dispositivo.get('name', dispositivo['hostname'])
    log.info(f"[{nombre}] Consultando via SNMP real...")

    try:
        cpu = await obtener_cpu(dispositivo)
        if cpu is None:
            return None

        interfaces = await obtener_interfaces(dispositivo)
        if interfaces is None:
            return None

        red = await obtener_red_interfaces(dispositivo)
        identidad = await obtener_identidad(dispositivo)
        sistema = await obtener_sistema(dispositivo)
        transceptores = await obtener_optica(dispositivo, interfaces)
        for interface in interfaces:
            interface.update(red.get(interface['indice'], {}))

        return {
            'nombre':        nombre,
            'descripcion':   'Cisco IOS-XE',
            'ip':            dispositivo['hostname'],
            'rol':           dispositivo.get('role', 'unknown'),
            'sitio':         dispositivo.get('site', 'unknown'),
            'cpu_5s':        cpu['cpu_5s'],
            'cpu_1m':        cpu['cpu_1m'],
            'cpu_5m':        cpu['cpu_5m'],
            'interfaces':    interfaces,
            'transceptores': transceptores,
            **sistema,
            **identidad,
        }

    except Exception as e:
        log.error(f"[{nombre}] Error SNMP: {e}")
        return None

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
import time

from sonar.utils.logger import get_logger
from sonar.utils import config
from sonar.collector.extras import obtener_extras, tabla_mac
from sonar.collector import dom

log = get_logger(__name__)


def _auth(community: str, vlan: int | None = None):
    """Credenciales SNMP según SNMP_VERSION: v3 (USM) o v2c (comunidad).

    Con `vlan`, v2c usa la comunidad indexada de Cisco (comunidad@vlan) para
    leer la tabla MAC de esa VLAN; en v3 la VLAN va en el contexto (_context).
    """
    if config.SNMP_VERSION == '3':
        return UsmUserData(config.SNMP_V3_USER, **config.snmp_v3_keys())
    return CommunityData(f'{community}@{vlan}' if vlan else community, mpModel=1)


def _context(vlan: int | None = None):
    if vlan and config.SNMP_VERSION == '3':
        return ContextData(contextName=f'vlan-{vlan}'.encode())
    return ContextData()

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


async def _get_many(ip: str, community: str, oids: list[str], chunk: int = 20) -> dict[str, object]:
    """GET de varios OID en pocas PDU; omite los que el equipo no tiene."""
    result = {}
    for start in range(0, len(oids), chunk):
        error_indication, error_status, _error_index, var_binds = await get_cmd(
            SnmpEngine(), _auth(community),
            await UdpTransportTarget.create((ip, config.SNMP_PORT),
                                            timeout=config.SNMP_TIMEOUT,
                                            retries=config.SNMP_RETRIES),
            ContextData(), *(ObjectType(ObjectIdentity(oid)) for oid in oids[start:start + chunk]))
        if error_indication or error_status:
            continue
        for oid, value in var_binds:
            # noSuchObject / noSuchInstance / endOfMibView no son lecturas.
            if value.__class__.__name__ in ('NoSuchObject', 'NoSuchInstance', 'EndOfMibView'):
                continue
            result[str(oid)] = value
    return result


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


async def _walk_oid_rows(ip: str, community: str, oid: str, vlan: int | None = None) -> list[tuple[list[int], object]]:
    """Conserva todo el índice de una tabla SNMP para correlacionar ARP/FDB/CDP."""
    rows = []
    async for error_indication, error_status, _error_index, var_binds in walk_cmd(
        SnmpEngine(), _auth(community, vlan),
        await UdpTransportTarget.create((ip, config.SNMP_PORT),
                                        timeout=config.SNMP_TIMEOUT,
                                        retries=config.SNMP_RETRIES),
        _context(vlan), ObjectType(ObjectIdentity(oid)), lexicographicMode=False
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
        arp_mac, arp_ip, access_vlan, voice_vlan, cdp_device = await asyncio.gather(
            *(_walk_oid_rows(ip, community, oid) for oid in OID_NETWORK.values())
        )
        # MAC de todas las VLAN con equipos (no sólo la VLAN 1), una MAC por puerto.
        mac_to_if = await tabla_mac(
            lambda oid, vlan=None: _walk_oid_rows(ip, community, oid, vlan),
            [_safe_int(str(value)) for _suffix, value in access_vlan + voice_vlan],
            config.SNMP_MAX_VLANS)
    except Exception as error:
        log.warning(f"[{dispositivo.get('name', ip)}] Metadatos de red no disponibles: {error}")
        return {}

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
    ticks = _safe_int(uptime_raw)
    return {
        # sysUpTime viene en TimeTicks (centésimas de segundo).
        'uptime_segundos': ticks // 100 if ticks is not None else None,
        'memoria_total_bytes': total_bytes,
        'memoria_usada_bytes': used_bytes,
        'memoria_usada_pct': round(used_bytes * 100 / total_bytes, 2) if total_bytes and used_bytes is not None else None,
    }


# Estructura DOM por switch (nombres, contenedores, puertos y umbrales): sólo
# cambia al insertar o retirar un transceptor, que también cambia los índices.
_DOM_CACHE: dict[str, tuple[float, tuple, dict]] = {}
DOM_CACHE_SECONDS = 6 * 3600


async def _dom_structure(ip: str, community: str, types: dict[int, int]) -> dict:
    """Nombres, jerarquía, ifIndex y umbrales de los sensores; cacheado por firma."""
    signature = tuple(sorted(types.items()))
    cached = _DOM_CACHE.get(ip)
    if cached and cached[1] == signature and time.monotonic() - cached[0] < DOM_CACHE_SECONDS:
        return cached[2]
    indexes = list(types)
    values = await _get_many(ip, community, [f"{dom.OID_ENTITY['name']}.{i}" for i in indexes])
    names = {i: str(values.get(f"{dom.OID_ENTITY['name']}.{i}", '')) for i in indexes}
    optic = dom.optic_sensor_indexes(types, names)
    structure = dict(names=names, parents={}, parent_names={}, parent_ifindex={}, thresholds={})
    if optic:
        values = await _get_many(ip, community, [f"{dom.OID_ENTITY['contained_in']}.{i}" for i in indexes])
        parents = {i: _safe_int(str(values.get(f"{dom.OID_ENTITY['contained_in']}.{i}"))) for i in indexes}
        optic_parents = sorted({parents[i] for i in optic if parents.get(i)})
        values = await _get_many(ip, community, [
            *(f"{dom.OID_ENTITY['name']}.{p}" for p in optic_parents),
            *(f"{dom.OID_ENTITY['alias']}.{p}.0" for p in optic_parents)])
        rows = {key: await _walk_oid_rows(ip, community, oid) for key, oid in dom.OID_THRESHOLD.items()}
        by_key = {key: {tuple(suffix): value for suffix, value in items if len(suffix) == 2}
                  for key, items in rows.items()}
        thresholds = {}
        for (sensor, row), raw in by_key['value'].items():
            thresholds.setdefault(sensor, []).append((
                _safe_int(str(by_key['severity'].get((sensor, row)))),
                _safe_int(str(by_key['relation'].get((sensor, row)))), _safe_int(str(raw))))
        structure.update(
            parents=parents, thresholds=thresholds,
            parent_names={p: str(values.get(f"{dom.OID_ENTITY['name']}.{p}", '')) for p in optic_parents},
            parent_ifindex={p: dom.if_index_from_alias(values.get(f"{dom.OID_ENTITY['alias']}.{p}.0"))
                            for p in optic_parents})
    _DOM_CACHE[ip] = (time.monotonic(), signature, structure)
    return structure


async def obtener_optica(dispositivo: dict, interfaces: list[dict]) -> list[dict] | None:
    """Lee el DOM de los transceptores (potencia RX/TX, temperatura, voltaje, bias).

    Usa CISCO-ENTITY-SENSOR-MIB y, si está vacía, ENTITY-SENSOR-MIB. Los equipos
    sin ópticas con DOM (cobre, módulos sin DOM) devuelven [] tras un solo walk.
    None indica que la consulta falló y no se sabe nada.
    """
    ip = dispositivo['hostname']
    community = config.SNMP_COMMUNITY
    try:
        oids = dom.OID_CISCO_SENSOR
        types = {suffix[-1]: _safe_int(str(value)) for suffix, value in await _walk_oid_rows(ip, community, oids['type']) if suffix}
        if not types:
            oids = dom.OID_STD_SENSOR
            types = {suffix[-1]: _safe_int(str(value)) for suffix, value in await _walk_oid_rows(ip, community, oids['type']) if suffix}
        if not any(t in dom.POWER_TYPES for t in types.values()):
            return []
        structure = await _dom_structure(ip, community, types)
        optic_parents = {structure['parents'].get(i) for i in dom.optic_sensor_indexes(types, structure['names'])}
        sensors = [i for i, parent in structure['parents'].items() if parent in optic_parents and parent]
        if not sensors:
            return []
        if_indexes = sorted({i for i in structure['parent_ifindex'].values() if i})
        values = await _get_many(ip, community, [
            *(f"{oids[column]}.{i}" for i in sensors for column in ('scale', 'precision', 'value', 'status')),
            *(f"{dom.OID_IF_ADMIN}.{i}" for i in if_indexes)])
    except Exception as error:
        log.debug(f"[{dispositivo.get('name', ip)}] Sensores ópticos no disponibles: {error}")
        return None
    read = lambda column, i: _safe_int(str(values[f"{oids[column]}.{i}"])) if f"{oids[column]}.{i}" in values else None
    readings = {i: dict(type=types[i], name=structure['names'].get(i), scale=read('scale', i),
                        precision=read('precision', i), value=read('value', i), status=read('status', i))
                for i in sensors}
    admin = {i: _safe_int(str(values[f"{dom.OID_IF_ADMIN}.{i}"])) for i in if_indexes
             if f"{dom.OID_IF_ADMIN}.{i}" in values}
    return dom.build_transceivers(readings, structure['thresholds'], structure['parents'],
                                  structure['parent_names'], structure['parent_ifindex'], interfaces, admin)


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
        uptime = sistema.get('uptime_segundos')
        extras_puerto, extras_switch = await obtener_extras(
            lambda oid: _walk_oid_rows(dispositivo['hostname'], config.SNMP_COMMUNITY, oid),
            interfaces, uptime * 100 if uptime is not None else None)
        for interface in interfaces:
            interface.update(red.get(interface['indice'], {}))
            interface.update(extras_puerto.get(interface['indice'], {}))

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
            **extras_switch,
        }

    except Exception as e:
        log.error(f"[{nombre}] Error SNMP: {e}")
        return None

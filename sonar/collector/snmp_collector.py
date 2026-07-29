# sonar/collector/snmp_collector.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Colector SNMP real para switches Cisco IOS-XE.
# Reemplaza al simulador cuando hay acceso real a los switches.

from pysnmp.hlapi.asyncio import *
import asyncio

from sonar.utils.logger import get_logger
from sonar.utils import config

log = get_logger(__name__)

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
    'ifOperStatus': '1.3.6.1.2.1.2.2.1.8',
    'ifInErrors':   '1.3.6.1.2.1.2.2.1.14',
    'ifOutErrors':  '1.3.6.1.2.1.2.2.1.20',
    'ifInCRCErrs':  '1.3.6.1.2.1.16.1.1.1.8',
}


async def _get_oid(ip: str, community: str, oid: str) -> str | None:
    """
    Consulta un OID especifico y retorna su valor como string.
    """
    errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
        SnmpEngine(),
        CommunityData(community, mpModel=1),
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
        CommunityData(community, mpModel=1),
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


async def obtener_cpu(dispositivo: dict) -> dict | None:
    """
    Consulta el CPU del switch via SNMP.
    """
    ip        = dispositivo['hostname']
    community = config.SNMP_COMMUNITY
    nombre    = dispositivo.get('name', ip)

    cpu = {}
    for campo, oid in OIDS_CPU.items():
        valor = await _get_oid(ip, community, oid)
        if valor is None:
            return None
        cpu[campo] = int(valor) if valor.isdigit() else 0

    log.debug(f"[{nombre}] CPU → "
              f"5s={cpu['cpu_5s']}% "
              f"1m={cpu['cpu_1m']}% "
              f"5m={cpu['cpu_5m']}%")
    return cpu


async def obtener_interfaces(dispositivo: dict) -> list | None:
    """
    Consulta el estado y errores de todas las interfaces via SNMP walk.
    """
    ip        = dispositivo['hostname']
    community = config.SNMP_COMMUNITY
    nombre    = dispositivo.get('name', ip)

    nombres  = await _walk_oid(ip, community, OID_IF_TABLE['ifDescr'])
    if not nombres:
        return None

    estados  = await _walk_oid(ip, community, OID_IF_TABLE['ifOperStatus'])
    in_err   = await _walk_oid(ip, community, OID_IF_TABLE['ifInErrors'])
    out_err  = await _walk_oid(ip, community, OID_IF_TABLE['ifOutErrors'])

    interfaces = []
    for idx, nombre_if in nombres.items():
        # Ignorar interfaces virtuales
        if any(x in nombre_if for x in ['Vlan', 'Loopback', 'Tunnel', 'Null']):
            continue

        estado_raw = estados.get(idx, '2')
        estado     = 'up' if estado_raw == '1' else 'down'

        interfaces.append({
            'nombre':          nombre_if,
            'estado':          estado,
            'errores_entrada': int(in_err.get(idx, 0)),
            'errores_crc':     0,
            'errores_salida':  int(out_err.get(idx, 0)),
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
            'transceptores': [],  # Fase siguiente
        }

    except Exception as e:
        log.error(f"[{nombre}] Error SNMP: {e}")
        return None
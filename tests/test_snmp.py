# test_snmp.py
# Archivo temporal de prueba - No es parte de SONAR
# Verifica que podemos consultar SNMP al switch simulado

from pysnmp.hlapi.v3arch.asyncio import *
import asyncio

async def consultar_snmp():
    """
    Consulta el OID de nombre del sistema (sysDescr) al switch.
    Si esto funciona, SNMP está bien configurado en ambos lados.
    """
    # OID sysDescr: descripcion del sistema
    # Es el OID mas basico que existe, todos los dispositivos lo tienen
    oid = '1.3.6.1.2.1.1.1.0'
    ip_switch = '192.168.1.1'
    community = 'public'

    print(f"Consultando {ip_switch} via SNMP...")

    errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
        SnmpEngine(),
        CommunityData(community, mpModel=1),  # mpModel=1 es SNMPv2c
        await UdpTransportTarget.create((ip_switch, 161), timeout=2, retries=1),
        ContextData(),
        ObjectType(ObjectIdentity(oid))
    )

    if errorIndication:
        print(f"ERROR: {errorIndication}")
        return

    if errorStatus:
        print(f"ERROR SNMP: {errorStatus}")
        return

    for varBind in varBinds:
        print(f"Respuesta: {varBind.prettyPrint()}")

asyncio.run(consultar_snmp())
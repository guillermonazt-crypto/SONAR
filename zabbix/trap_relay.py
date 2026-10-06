"""Receptor de traps SNMP para Zabbix en Windows (Docker Desktop).

Docker Desktop reescribe la IP de origen de lo que entra por un puerto publicado: el
contenedor zabbix-snmptraps ve todos los traps como 172.x (el gateway de Docker) y
Zabbix no puede asociarlos a ningún switch. Este receptor corre en Windows, escucha
UDP 162, ve la IP real del switch y escribe cada trap en el formato de Zabbix
("<fecha> ZBXTRAP <ip>") en zabbix/snmptraps/snmptraps.log, carpeta que el servidor
monta como /var/lib/zabbix/snmptraps (SNMPTrapperFile).

    python zabbix/trap_relay.py                 escucha 0.0.0.0:162 (Ctrl+C para salir)
    python zabbix/trap_relay.py --prueba        envía un trap linkDown de prueba a sí mismo

Sólo acepta la comunidad de los switches (ZBX_SNMP_COMMUNITY o SNMP_COMMUNITY de SONAR).
En Linux no hace falta: ahí el contenedor zabbix-snmptraps (profile "traps") ve la IP real.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pyasn1.codec.ber import decoder
from pysnmp.proto import api

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from init_zabbix import read_env  # noqa: E402

TRAP_FILE = HERE / 'snmptraps' / 'snmptraps.log'
MAX_BYTES = 50 * 1024 * 1024
SNMP_TRAP_OID = '1.3.6.1.6.3.1.1.4.1.0'
# Traps genéricos de SNMPv1 → OID de SNMPv2 (coldStart … egpNeighborLoss).
GENERIC_V1 = {0: 'coldStart', 1: 'warmStart', 2: 'linkDown', 3: 'linkUp', 4: 'authenticationFailure',
              5: 'egpNeighborLoss'}
NAMES = {'1.3.6.1.6.3.1.1.5.3': 'linkDown', '1.3.6.1.6.3.1.1.5.4': 'linkUp',
         '1.3.6.1.6.3.1.1.5.1': 'coldStart', '1.3.6.1.6.3.1.1.5.2': 'warmStart'}


def decode(data, communities):
    """(lineas, comunidad) del trap o None si no es un trap válido de la comunidad aceptada."""
    try:
        version = int(api.decodeMessageVersion(data))
        module = api.PROTOCOL_MODULES[version]
        message, _ = decoder.decode(data, asn1Spec=module.Message())
    except Exception:
        return None
    community = str(module.apiMessage.get_community(message))
    if communities and community not in communities:
        return None
    pdu = module.apiMessage.get_pdu(message)
    lines = []
    if version == api.SNMP_VERSION_1:
        if not pdu.isSameTypeWith(module.TrapPDU()):
            return None
        generic = int(module.apiTrapPDU.get_generic_trap(pdu))
        if generic == 6:
            oid = f'{module.apiTrapPDU.get_enterprise(pdu).prettyPrint()}.0.{int(module.apiTrapPDU.get_specific_trap(pdu))}'
        else:
            oid = f'1.3.6.1.6.3.1.1.5.{generic + 1}'
        lines.append(f'SNMPv2-MIB::snmpTrapOID.0 = {oid} ({NAMES.get(oid, GENERIC_V1.get(generic, "enterprise"))})')
        varbinds = module.apiTrapPDU.get_varbinds(pdu)
    else:
        if not (pdu.isSameTypeWith(module.SNMPv2TrapPDU()) or pdu.isSameTypeWith(module.InformRequestPDU())):
            return None
        varbinds = module.apiPDU.get_varbinds(pdu)
    for oid, value in varbinds:
        oid, text = oid.prettyPrint(), value.prettyPrint()
        if oid == SNMP_TRAP_OID:
            lines.append(f'SNMPv2-MIB::snmpTrapOID.0 = {text} ({NAMES.get(text, "trap")})')
        else:
            lines.append(f'{oid} = {text}')
    return lines


def record(ip, port, lines, now=None):
    """Texto en el formato que lee el SNMP trapper de Zabbix."""
    stamp = (now or datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%S%z')
    return '\n'.join([f'{stamp} ZBXTRAP {ip}', f'UDP: [{ip}]:{port}->[relay]:162', *lines]) + '\n'


class Relay(asyncio.DatagramProtocol):
    def __init__(self, path, communities):
        self.path = Path(path)
        self.communities = communities
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def datagram_received(self, data, addr):
        lines = decode(data, self.communities)
        if lines is None:
            return
        if self.path.exists() and self.path.stat().st_size > MAX_BYTES:
            self.path.write_text('', encoding='utf-8')  # Zabbix detecta el archivo truncado y vuelve a empezar
        with self.path.open('a', encoding='utf-8', newline='\n') as handle:
            handle.write(record(addr[0], addr[1], lines))
        print(f'{datetime.now():%H:%M:%S} trap de {addr[0]}: {lines[0] if lines else ""}', flush=True)


def communities(sonar_root):
    env = {**read_env(HERE / '.env'), **read_env(Path(sonar_root) / '.env'), **os.environ}
    return {value for value in (env.get('ZBX_SNMP_COMMUNITY'), env.get('SNMP_COMMUNITY')) if value}


async def serve(host, port, path, accepted):
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: Relay(path, accepted), local_addr=(host, port))
    print(f'Receptor de traps en {host}:{port} -> {path} ({len(accepted)} comunidad(es) aceptada(s)).', flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        transport.close()


async def send_test(port, community):
    from pysnmp.hlapi.v3arch.asyncio import (CommunityData, ContextData, Integer32, NotificationType, ObjectIdentity,
                                             OctetString, SnmpEngine, UdpTransportTarget, send_notification)
    error = (await send_notification(
        SnmpEngine(), CommunityData(community), await UdpTransportTarget.create(('127.0.0.1', port)), ContextData(),
        'trap', NotificationType(ObjectIdentity('1.3.6.1.6.3.1.1.5.3')).add_varbinds(
            ('1.3.6.1.2.1.2.2.1.1.0', Integer32(0)), ('1.3.6.1.2.1.2.2.1.2.0', OctetString('prueba SONAR')))))[0]
    print(f'Trap de prueba: {error or "enviado"}')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Receptor de traps SNMP para Zabbix (Windows).')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=162)
    parser.add_argument('--archivo', default=str(TRAP_FILE))
    parser.add_argument('--sonar-root', default=str(HERE.parent))
    parser.add_argument('--prueba', action='store_true', help='envía un trap linkDown de prueba al receptor local')
    args = parser.parse_args(argv)
    accepted = communities(args.sonar_root)
    try:
        if args.prueba:
            asyncio.run(send_test(args.port, next(iter(accepted), 'public')))
        else:
            asyncio.run(serve(args.host, args.port, args.archivo, accepted))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())

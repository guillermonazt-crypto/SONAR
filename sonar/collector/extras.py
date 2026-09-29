# sonar/collector/extras.py
#
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Datos adicionales por SNMP: vecinos CDP, velocidad y último cambio de cada
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
}
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


async def vecinos_cdp(walk):
    """{ifIndex: {vecino_nombre, vecino_puerto, vecino_plataforma, vecino_ip}} sin teléfonos.

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
        # Los teléfonos IP (SEPxxxx) ya se muestran como MAC del teléfono.
        if not name or name.upper().startswith('SEP'):
            continue
        address = by_key['address'].get(index)
        raw = bytes(address.asOctets()) if hasattr(address, 'asOctets') else b''
        result[index[0]] = {
            'vecino_nombre': name,
            'vecino_puerto': _text(by_key['port'].get(index, '')) or None,
            'vecino_plataforma': _text(by_key['platform'].get(index, '')) or None,
            'vecino_ip': '.'.join(str(byte) for byte in raw) if len(raw) == 4 else None,
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


NO_NEIGHBOR = dict(vecino_nombre=None, vecino_puerto=None, vecino_plataforma=None, vecino_ip=None)
NO_POE = dict(poe_estado=None, poe_mw=None)


async def obtener_extras(walk, interfaces, uptime_ticks=None):
    """Junta todo lo anterior: datos por ifIndex para fusionar en interfaces y datos del switch.

    Cuando una MIB respondió, los puertos sin dato quedan en None: así un vecino
    desconectado o un equipo PoE retirado no se quedan guardados para siempre.
    """
    per_port = {item['indice']: {} for item in interfaces}
    neighbors = await vecinos_cdp(walk)
    poe_ports, poe_switch = await poe(walk, interfaces)
    for index, values in per_port.items():
        if neighbors is not None:
            values.update(neighbors.get(index, NO_NEIGHBOR))
        if poe_switch:
            values.update(poe_ports.get(index, NO_POE))
    for index, values in (await datos_puertos(walk, uptime_ticks)).items():
        per_port.setdefault(index, {}).update(values)
    return per_port, {**poe_switch, **(await hardware(walk))}

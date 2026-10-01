# sonar/discovery.py
#
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Descubrimiento de equipos que aún no están en el inventario.
#
# Apagado por defecto (DISCOVERY_ENABLED=false). Dos fuentes:
#   - CDP: vecinos que el worker ya ve en cada sondeo (no genera tráfico extra).
#   - Barrido: consulta sysName/sysDescr por SNMP en DISCOVERY_SUBNETS.
# Los candidatos quedan en "Equipos descubiertos" para que un editor decida;
# nunca se agregan solos al inventario.
import asyncio
import ipaddress
import os
import time

from sonar.utils.logger import get_logger

log = get_logger(__name__)

OID_SYS_DESCR = '1.3.6.1.2.1.1.1.0'
OID_SYS_NAME = '1.3.6.1.2.1.1.5.0'


def settings():
    return dict(
        enabled=os.getenv('DISCOVERY_ENABLED', 'false').strip().lower() in ('1', 'true', 'si', 'sí', 'yes'),
        subnets=[item.strip() for item in os.getenv('DISCOVERY_SUBNETS', '').split(',') if item.strip()],
        interval_hours=float(os.getenv('DISCOVERY_INTERVAL_HOURS', '24')),
        max_hosts=int(os.getenv('DISCOVERY_MAX_HOSTS', '1024')),
        concurrency=int(os.getenv('DISCOVERY_CONCURRENCY', '32')),
    )


def hosts(subnets, max_hosts):
    """IPs a sondear; se detiene en max_hosts para no barrer una /8 por error."""
    result = []
    for subnet in subnets:
        network = ipaddress.ip_network(subnet, strict=False)
        for address in network.hosts():
            if len(result) >= max_hosts:
                log.warning(f"Descubrimiento limitado a {max_hosts} hosts (DISCOVERY_MAX_HOSTS)")
                return result
            result.append(str(address))
    return result


async def snmp_probe(ip):
    """sysName y sysDescr por SNMP con un solo intento corto; None si no responde."""
    from sonar.collector import snmp_collector as snmp
    from sonar.utils import config
    name = await snmp._get_oid(ip, config.SNMP_COMMUNITY, OID_SYS_NAME)
    if not name:
        return None
    descr = await snmp._get_oid(ip, config.SNMP_COMMUNITY, OID_SYS_DESCR)
    return dict(nombre=name, descripcion=descr or '')


async def sweep(subnets, probe, max_hosts=1024, concurrency=32, known=()):
    """Sondea las subredes y devuelve [{ip, nombre, descripcion}] de quienes respondieron."""
    limit = asyncio.Semaphore(max(1, concurrency))
    known = set(known)

    async def one(ip):
        async with limit:
            try:
                answer = await probe(ip)
            except Exception as error:
                log.debug(f"[{ip}] sin respuesta: {error}")
                return None
            return answer and dict(ip=ip, **answer)

    targets = [ip for ip in hosts(subnets, max_hosts) if ip not in known]
    found = await asyncio.gather(*(one(ip) for ip in targets))
    return [item for item in found if item]


async def run(probe=snmp_probe, now=None, force=False):
    """Una pasada de descubrimiento; devuelve cuántos candidatos nuevos o actualizados hubo."""
    config = settings()
    if not (config['enabled'] or force):
        return 0
    from sonar.utils.config import load_django_inventory
    load_django_inventory()  # inicializa Django si hace falta
    from django.db import connections, close_old_connections
    from sonar.database.django_store import _lock
    from switches.discovery import known_addresses, record_candidates, cdp_candidates

    def save(found):
        # SQLite admite un escritor a la vez: mismo candado que los sondeos.
        with _lock:
            return record_candidates(found)

    close_old_connections()
    try:
        known = await asyncio.to_thread(known_addresses)
        found = await asyncio.to_thread(cdp_candidates)
        if config['subnets']:
            found += [dict(item, origen='barrido') for item in
                      await sweep(config['subnets'], probe, config['max_hosts'], config['concurrency'], known)]
        count = await asyncio.to_thread(save, found)
    finally:
        connections.close_all()
    log.info(f"Descubrimiento: {count} equipo(s) candidato(s) fuera del inventario")
    return count


class Scheduler:
    """Ejecuta el descubrimiento cada DISCOVERY_INTERVAL_HOURS desde el ciclo del worker."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last = None

    def due(self):
        config = settings()
        if not config['enabled']:
            return False
        return self.last is None or self.clock() - self.last >= config['interval_hours'] * 3600

    async def maybe_run(self, probe=snmp_probe):
        if not self.due():
            return None
        self.last = self.clock()
        try:
            return await run(probe)
        except Exception:
            log.exception("El descubrimiento falló; se reintentará en el siguiente intervalo")
            return None

# sonar/synthetic.py
#
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Monitoreo sintético: pruebas activas de conectividad (ping) cada
# SYNTHETIC_INTERVAL_MINUTES a los equipos de los roles en SYNTHETIC_ROLES.
# Mide latencia (mín/prom/máx), jitter y pérdida de paquetes; el resultado va a
# InfluxDB (measurement "sintetico") para tendencias y a Django para el
# semáforo del plantel. Corre aparte del ciclo SNMP para no alargarlo.
import asyncio
import os
import re
import time

from sonar.collector.icmp import PING_TIMEOUT_MS, ping_command
from sonar.utils.logger import get_logger

log = get_logger(__name__)

# "tiempo=2ms", "tiempo<1m" (Windows en español), "time=0.045 ms" (Linux) o "time<1ms".
TIME_PATTERN = re.compile(r'(?:time|tiempo)\s*([=<])\s*([\d.,]+)\s*m', re.IGNORECASE)


def _enabled(value):
    return value.strip().lower() in ('1', 'true', 'si', 'sí', 'yes')


def settings():
    return dict(
        enabled=_enabled(os.getenv('SYNTHETIC_ENABLED', 'true')),
        interval_minutes=float(os.getenv('SYNTHETIC_INTERVAL_MINUTES', '5')),
        roles=[r.strip() for r in os.getenv('SYNTHETIC_ROLES', 'core,distribution,access').split(',') if r.strip()],
        count=max(1, int(os.getenv('SYNTHETIC_PING_COUNT', '5'))),
        concurrency=max(1, int(os.getenv('SYNTHETIC_CONCURRENCY', '20'))),
    )


def parse_ping(output: str, sent: int) -> dict:
    """Latencias y pérdida a partir de la salida de ping, sin depender del idioma.

    Sólo cuentan las líneas con TTL: en Windows "Host de destino inaccesible"
    también trae "Respuesta desde" pero no es una respuesta del equipo.
    """
    times = []
    for line in output.splitlines():
        if 'ttl=' not in line.lower():
            continue
        match = TIME_PATTERN.search(line)
        if match:
            value = float(match.group(2).replace(',', '.'))
            # "<1ms": por debajo de la resolución de Windows; se toma la mitad.
            times.append(value / 2 if match.group(1) == '<' else value)
    received = min(len(times), sent)
    result = dict(enviados=sent, recibidos=received, alcanzable=received > 0,
                  perdida_pct=round((sent - received) * 100 / sent, 1) if sent else None,
                  rtt_min_ms=None, rtt_avg_ms=None, rtt_max_ms=None, jitter_ms=None)
    if times:
        # Jitter como la variación media entre respuestas consecutivas (RFC 3550, simplificado).
        deltas = [abs(b - a) for a, b in zip(times, times[1:])]
        result.update(rtt_min_ms=round(min(times), 2), rtt_avg_ms=round(sum(times) / len(times), 2),
                      rtt_max_ms=round(max(times), 2),
                      jitter_ms=round(sum(deltas) / len(deltas), 2) if deltas else 0.0)
    return result


async def probe(host: str, count: int) -> dict | None:
    """Un ping de `count` paquetes; None si el comando no se pudo ejecutar."""
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *ping_command(host, count=count), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        limit = count * (PING_TIMEOUT_MS / 1000 + 1) + 2
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=limit)
    except (OSError, asyncio.TimeoutError) as error:
        log.warning(f"[{host}] Prueba sintética sin ejecutar: {error}")
        if process is not None and process.returncode is None:
            process.kill()
        return None
    return parse_ping(stdout.decode(errors='ignore'), count)


async def run(inventory, prober=probe, config=None) -> list[dict]:
    """Prueba los equipos de los roles configurados; devuelve [{dispositivo, resultado}]."""
    config = config or settings()
    roles = set(config['roles'])
    targets = [d for d in inventory if d.get('role', 'access') in roles]
    limit = asyncio.Semaphore(config['concurrency'])

    async def one(device):
        async with limit:
            try:
                result = await prober(device['hostname'], config['count'])
            except Exception as error:
                log.warning(f"[{device.get('name', device['hostname'])}] Prueba sintética falló: {error}")
                return None
            return result and dict(dispositivo=device, resultado=result)

    found = await asyncio.gather(*(one(d) for d in targets))
    results = [item for item in found if item]
    lost = sum(1 for item in results if not item['resultado']['alcanzable'])
    log.info(f"Monitoreo sintético: {len(results)} equipos probados, {lost} sin respuesta")
    return results


class Scheduler:
    """Ejecuta `run` cada SYNTHETIC_INTERVAL_MINUTES si SYNTHETIC_ENABLED (activo por defecto)."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last = None

    def due(self, config):
        if not config['enabled']:
            return False
        return self.last is None or self.clock() - self.last >= config['interval_minutes'] * 60

    async def maybe_run(self, inventory, writer, store, prober=probe, config=None):
        """Prueba, escribe en InfluxDB (`writer.escribir_sintetico`) y en Django (`store`)."""
        config = config or settings()
        if not self.due(config):
            return None
        self.last = self.clock()
        results = await run(inventory, prober, config)
        if not results:
            return results
        try:
            await asyncio.to_thread(writer.escribir_sintetico, results)
        except Exception as error:
            log.warning(f"No se pudo guardar el monitoreo sintético en InfluxDB: {error}")
        try:
            await asyncio.to_thread(store, results)
        except Exception:
            log.exception("No se pudo guardar el monitoreo sintético en Django")
        return results

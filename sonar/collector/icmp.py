# sonar/collector/icmp.py
#
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Segundo método de verificación: un ping ICMP cuando SNMP no responde.
# Distingue un switch apagado (sin SNMP ni ping) de uno encendido con SNMP
# caído o mal configurado, antes de marcarlo en rojo.

import asyncio
import os
import sys

from sonar.utils.logger import get_logger

log = get_logger(__name__)

PING_ENABLED = os.getenv("PING_ENABLED", "true").strip().lower() in ("1", "true", "si", "sí", "yes")
PING_TIMEOUT_MS = int(os.getenv("PING_TIMEOUT_MS", "1000"))
PING_COUNT = int(os.getenv("PING_COUNT", "2"))


def ping_command(host: str, windows: bool | None = None, count: int | None = None) -> list[str]:
    """Comando ping del sistema con `count` (PING_COUNT) intentos y PING_TIMEOUT_MS por respuesta."""
    windows = sys.platform.startswith("win") if windows is None else windows
    count = PING_COUNT if count is None else count
    if windows:
        return ["ping", "-n", str(count), "-w", str(PING_TIMEOUT_MS), host]
    return ["ping", "-c", str(count), "-W", str(max(1, PING_TIMEOUT_MS // 1000)), host]


def ping_succeeded(returncode: int, output: str) -> bool:
    """En Windows ping devuelve 0 con "Host de destino inaccesible": sólo cuenta una respuesta con TTL."""
    return returncode == 0 and "ttl=" in output.lower()


async def ping(host: str) -> bool | None:
    """True si responde a ICMP, False si no, None si el ping no se pudo ejecutar."""
    if not PING_ENABLED:
        return None
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *ping_command(host), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        limit = PING_COUNT * (PING_TIMEOUT_MS / 1000 + 1) + 2
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=limit)
    except (OSError, asyncio.TimeoutError) as error:
        log.warning(f"[{host}] No se pudo ejecutar ping: {error}")
        if process is not None and process.returncode is None:
            process.kill()
        return None
    return ping_succeeded(process.returncode, stdout.decode(errors="ignore"))

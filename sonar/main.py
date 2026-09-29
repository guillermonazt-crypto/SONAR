# sonar/main.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Punto de entrada principal de SONAR.
# Loop de monitoreo continuo con switches reales via SNMP.

import asyncio
import time

from sonar.utils.logger import get_logger
from sonar.utils.config import load_inventory, validate_snmp, POLL_INTERVAL, SNMP_CONCURRENCY
from sonar.database.influx_writer import InfluxWriter
from sonar.database.django_store import record_poll, notify_alerts
from sonar.collector.snmp_collector import obtener_datos_reales

log = get_logger(__name__)


async def procesar_switch(dispositivo: dict, writer: InfluxWriter) -> bool:
    """
    Consulta un switch real via SNMP y escribe sus datos en InfluxDB.

    Args:
        dispositivo: Diccionario del inventario
        writer: Instancia activa de InfluxWriter

    Returns:
        True si todo salio bien, False si hubo error
    """
    nombre = dispositivo.get('name', dispositivo['hostname'])

    try:
        datos = await obtener_datos_reales(dispositivo)

        await asyncio.to_thread(record_poll, dispositivo, datos)
        await asyncio.to_thread(notify_alerts, dispositivo)

        if not datos:
            log.warning(f"[{nombre}] Sin datos, saltando...")
            return False

        await asyncio.to_thread(writer.escribir_cpu, datos)
        await asyncio.to_thread(writer.escribir_sistema, datos)
        await asyncio.to_thread(writer.escribir_interfaces, datos)
        await asyncio.to_thread(writer.escribir_optica, datos)

        log.info(f"[{nombre}] ok CPU={datos['cpu_5m']}% "
                 f"Interfaces={len(datos['interfaces'])}")
        return True

    except Exception as e:
        log.error(f"[{nombre}] x Error: {e}")
        return False


async def ejecutar_ciclo(inventario: list, writer: InfluxWriter) -> None:
    """
    Ejecuta un ciclo completo consultando todos los switches en paralelo.
    """
    inicio = time.time()
    log.info(f"━━━ Iniciando ciclo: {len(inventario)} dispositivos ━━━")

    # Consulta en paralelo con un límite para no saturar UDP ni provocar
    # timeouts falsos cuando el inventario crece.
    limite = asyncio.Semaphore(max(1, SNMP_CONCURRENCY))

    async def con_limite(dispositivo):
        async with limite:
            return await procesar_switch(dispositivo, writer)

    tareas = [con_limite(d) for d in inventario]
    resultados = await asyncio.gather(*tareas, return_exceptions=True)

    exitosos = sum(1 for r in resultados if r is True)
    fallidos  = len(resultados) - exitosos
    duracion  = round(time.time() - inicio, 2)

    log.info(f"━━━ Ciclo completo en {duracion}s | "
             f" ok {exitosos} exitosos | "
             f" x {fallidos} fallidos ━━━")
    if duracion > POLL_INTERVAL:
        log.warning(f"El ciclo tardó {duracion}s, más que el intervalo de {POLL_INTERVAL}s. "
                    "Sube SNMP_CONCURRENCY o POLL_INTERVAL_SECONDS.")


async def main() -> None:
    """
    Loop principal de SONAR con switches reales.
    """
    log.info("=" * 55)
    log.info("  S.O.N.A.R. - Modo produccion")
    log.info(f"  Intervalo: {POLL_INTERVAL} segundos")
    log.info("=" * 55)

    validate_snmp()
    writer = InfluxWriter()
    log.info("SONAR activo. Presiona Ctrl+C para detener.\n")

    try:
        while True:
            try:
                inventario = await asyncio.to_thread(load_inventory)
            except Exception:
                log.exception("No se pudo recargar el inventario; se omite este ciclo")
            else:
                await ejecutar_ciclo(inventario, writer)
            log.info(f"Esperando {POLL_INTERVAL}s...\n")
            await asyncio.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log.info("SONAR detenido por el usuario.")

    finally:
        await asyncio.to_thread(writer.cerrar)
        log.info("Hasta luego.")


if __name__ == "__main__":
    asyncio.run(main())

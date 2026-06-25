# sonar/main.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Punto de entrada principal de SONAR.
# Ejecuta el loop de monitoreo continuo consultando todos los switches
# del inventario y escribiendo las metricas en InfluxDB.

import sys
from pathlib import Path

# Add project root to sys.path to support running directly (e.g. python sonar/main.py)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import time
from datetime import datetime

# pyrefly: ignore [missing-import]
from sonar.utils.logger import get_logger
from sonar.database.influx_writer import InfluxWriter, log
from sonar.utils.config import load_inventory, POLL_INTERVAL
from snmp_simulator import obtener_datos_switch

logger = get_logger(__name__)

def procesar_switch(dispositivo: dict, writer: InfluxWriter) -> bool:
    """
    Obtiene los datos de un switch específico y los escribe en InfluxDB.

    Args:
        dispositivo: Diccionario con la configuración del dispositivo del inventario.
        writer: Instancia activa de InfluxWriter.
    Returns:
        True si el proceso fue exitoso, False de lo contrario.
    """
    nombre = dispositivo.get("name", dispositivo["hostname"])
    try:
        log.info(f"Consultando switch: {nombre}")
        datos = obtener_datos_switch(nombre)
        
        # Override simulated metadata with actual device inventory metadata
        datos = datos.copy()
        datos["nombre"] = nombre
        datos["ip"] = dispositivo["hostname"]
        datos["rol"] = dispositivo.get("role", "unknown")
        datos["sitio"] = dispositivo.get("site", "unknown")
        
        writer.escribir_cpu(datos)
        writer.escribir_interfaces(datos)
        writer.escribir_optica(datos)
        return True
    except Exception as e:
        log.error(f"Error al procesar el switch {nombre}: {e}")
        return False

def ejecutar_ciclo(inventario: list, writer: InfluxWriter) -> None:
    """
    Ejecuta un ciclo completo de monitoreo para todos los switches.
    Un ciclo = consultar y escribir datos de todos los dispositivos.

    Args:
        inventario: Lista de dispositivos del archivo devices.yaml
        writer: Instancia activa de InfluxWriter
    """
    inicio = time.time()
    exitosos = 0
    fallidos = 0

    log.info(f"Iniciando ciclo: {len(inventario)} dispositivos")

    for dispositivo in inventario:
        exito = procesar_switch(dispositivo, writer)

        if exito:
            exitosos += 1
        else:
            fallidos += 1

    duracion = round(time.time() - inicio, 2)
    log.info(
        f"-- Ciclo completo en {duracion}s\n"
        f"--- Exitosos: {exitosos} | Fallidos: {fallidos}\n"
        f"--- Esperando {POLL_INTERVAL}s para el próximo ciclo"
    )

def main() -> None:
    """
    Función principal de SONAR - loop infinito de monitoreo
    """
    log.info("\n" + "=" * 55)
    log.info("SONAR - Sistema de Observabilidad de Nodos y Analisis de Red")
    log.info("Iniciando SONAR en modo monitoreo continuo")
    log.info("=" * 55 + "\n")

    inventario = load_inventory()

    if not inventario:
        log.error("No hay dispositivos para monitorear - revisar devices.yaml")
        sys.exit(1)

    log.info(f"Dispositivos cargados: {len(inventario)}")
    for d in inventario:
        log.info(f"  -> {d.get('name', d['hostname'])} ({d.get('role', 'unknown')})")

    writer = InfluxWriter()
    log.info("SONAR activo. Presiona Ctrl + C para detener. \n")

    try:
        while True:
            ejecutar_ciclo(inventario, writer)
            log.info(f"Esperando {POLL_INTERVAL} segundos para el siguiente ciclo...\n")
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        log.info("\nSONAR detenido por el usuario")
    finally:
        writer.cerrar()
        log.info("Hasta luego.")

if __name__ == "__main__":
    main()
# sonar/utils/config.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Este modulo carga toda la configuracion del proyecto.
# Lee el archivo .env y el inventario de switches en YAML.
# Todos los demas modulos obtienen su configuracion desde aqui.

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

from sonar.utils.logger import get_logger

log = get_logger(__name__)

# Ruta raiz del proyecto (dos niveles arriba de este archivo)
ROOT = Path(__file__).resolve().parents[2]

# Carga las variables del archivo .env
load_dotenv(dotenv_path=ROOT / ".env")


# ---------------------------------------------------------------------------
# Configuracion de InfluxDB
# ---------------------------------------------------------------------------
INFLUX_URL    = os.getenv("INFLUX_URL",    "http://localhost:8086")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN",  "")
INFLUX_ORG    = os.getenv("INFLUX_ORG",    "universidad")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "red_universitaria")

# ---------------------------------------------------------------------------
# Configuracion SNMP
# ---------------------------------------------------------------------------
SNMP_COMMUNITY = os.getenv("SNMP_COMMUNITY", "public")
SNMP_PORT      = int(os.getenv("SNMP_PORT",  "161"))
SNMP_TIMEOUT   = int(os.getenv("SNMP_TIMEOUT", "2"))
SNMP_RETRIES   = int(os.getenv("SNMP_RETRIES", "3"))

# ---------------------------------------------------------------------------
# Configuracion del Worker
# ---------------------------------------------------------------------------
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))


# ---------------------------------------------------------------------------
# Inventario de dispositivos
# ---------------------------------------------------------------------------
def load_inventory() -> list[dict]:
    """
    Carga el inventario de switches desde inventory/devices.yaml.

    Returns:
        Lista de diccionarios, uno por dispositivo.
        Cada diccionario contiene hostname, nombre, rol y sitio.
        Retorna lista vacia si el archivo no existe.

    Ejemplo de un dispositivo en la lista:
        {
            "hostname": "10.0.1.1",
            "name": "SW-CORE-01",
            "role": "core",
            "site": "campus_central"
        }
    """
    inventory_path = ROOT / "inventory" / "devices.yaml"

    if not inventory_path.exists():
        log.warning(f"Inventario no encontrado en: {inventory_path}")
        return []

    with open(inventory_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    devices = data.get("devices", [])
    log.info(f"Inventario cargado: {len(devices)} dispositivos")
    return devices
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
# v2c usa SNMP_COMMUNITY; v3 usa usuario USM con autenticación y cifrado.
# No hay comunidad por defecto: "public" es la primera que se prueba en un ataque.
SNMP_VERSION   = os.getenv("SNMP_VERSION", "2c").strip().lower().lstrip("v")
SNMP_COMMUNITY = os.getenv("SNMP_COMMUNITY", "")
SNMP_V3_USER       = os.getenv("SNMP_V3_USER", "")
SNMP_V3_AUTH_KEY   = os.getenv("SNMP_V3_AUTH_KEY", "")
SNMP_V3_PRIV_KEY   = os.getenv("SNMP_V3_PRIV_KEY", "")
SNMP_V3_AUTH_PROTO = os.getenv("SNMP_V3_AUTH_PROTOCOL", "sha").lower()
SNMP_V3_PRIV_PROTO = os.getenv("SNMP_V3_PRIV_PROTOCOL", "aes").lower()
# Máximo de switches consultados a la vez en un ciclo.
SNMP_CONCURRENCY = int(os.getenv("SNMP_CONCURRENCY", "20"))
SNMP_PORT      = int(os.getenv("SNMP_PORT",  "161"))
SNMP_TIMEOUT   = int(os.getenv("SNMP_TIMEOUT", "2"))
SNMP_RETRIES   = int(os.getenv("SNMP_RETRIES", "3"))
# VLAN cuya tabla MAC se consulta por contexto (comunidad@vlan / vlan-N) en cada ciclo.
SNMP_MAX_VLANS = int(os.getenv("SNMP_MAX_VLANS", "32"))



def snmp_v3_keys() -> dict:
    """Argumentos de UsmUserData para el nivel authPriv configurado."""
    from pysnmp.hlapi.asyncio import (
        usmHMACSHAAuthProtocol, usmHMAC192SHA256AuthProtocol, usmHMAC384SHA512AuthProtocol,
        usmAesCfb128Protocol, usmAesCfb256Protocol)
    auth = {'sha': usmHMACSHAAuthProtocol, 'sha256': usmHMAC192SHA256AuthProtocol,
            'sha512': usmHMAC384SHA512AuthProtocol}
    priv = {'aes': usmAesCfb128Protocol, 'aes256': usmAesCfb256Protocol}
    if SNMP_V3_AUTH_PROTO not in auth or SNMP_V3_PRIV_PROTO not in priv:
        raise ValueError('SNMP_V3_AUTH_PROTOCOL admite sha/sha256/sha512 y SNMP_V3_PRIV_PROTOCOL aes/aes256')
    return dict(authKey=SNMP_V3_AUTH_KEY, privKey=SNMP_V3_PRIV_KEY,
                authProtocol=auth[SNMP_V3_AUTH_PROTO], privProtocol=priv[SNMP_V3_PRIV_PROTO])


def validate_snmp() -> None:
    """Falla al arrancar el worker si las credenciales SNMP están incompletas."""
    if SNMP_VERSION == '3':
        if not (SNMP_V3_USER and len(SNMP_V3_AUTH_KEY) >= 8 and len(SNMP_V3_PRIV_KEY) >= 8):
            raise ValueError('SNMPv3 requiere SNMP_V3_USER y claves SNMP_V3_AUTH_KEY/SNMP_V3_PRIV_KEY de 8+ caracteres')
        snmp_v3_keys()
    elif SNMP_VERSION == '2c':
        if not SNMP_COMMUNITY:
            raise ValueError('Define SNMP_COMMUNITY en .env (o usa SNMP_VERSION=3)')
    else:
        raise ValueError('SNMP_VERSION debe ser 2c o 3')


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
    source = os.getenv("INVENTORY_SOURCE", "django")
    if source == "django":
        return load_django_inventory()
    if source != "yaml":
        raise ValueError("INVENTORY_SOURCE debe ser yaml o django")
    inventory_path = ROOT / "inventory" / "devices.yaml"

    if not inventory_path.exists():
        log.warning(f"Inventario no encontrado en: {inventory_path}")
        return []

    with open(inventory_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    devices = data.get("devices", [])
    log.info(f"Inventario cargado: {len(devices)} dispositivos")
    return devices

def setup_django() -> None:
    """Inicializa Django para usar el ORM desde el worker."""
    import sys
    import django
    backend_path = str(ROOT / "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def load_django_inventory() -> list[dict]:
    """Lectura ORM en el hilo del worker; no modifica Django."""
    setup_django()
    from django.db import connections, close_old_connections
    from switches.models import Switch
    close_old_connections()
    try:
        return [dict(django_id=s.pk, hostname=s.hostname, name=s.nombre, role=s.rol,
                     site=str(s.plantel))
                for s in Switch.objects.filter(activo=True, plantel__activo=True)
                .select_related('plantel__division')]
    finally:
        connections.close_all()

# sonar/database/influx_writer.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Este modulo escribe las metricas recolectadas en InfluxDB.
# Es el puente entre los datos del switch y la base de datos.

# pyrefly: ignore [missing-import]
from influxdb_client import InfluxDBClient, Point, WritePrecision
# pyrefly: ignore [missing-import]
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime, timezone

from sonar.utils.logger import get_logger
from sonar.utils import config

log = get_logger(__name__)


class InfluxWriter:
    """
    Maneja la conexion y escritura de datos en InfluxDB.

    Cada metrica se escribe como un Point que contiene:
    - measurement: el tipo de dato (cpu, interfaces, optica)
    - tags: identificadores del dispositivo (no son valores numericos)
    - fields: los valores numericos reales
    - timestamp: cuando se tomo la medicion
    """

    def __init__(self):
        """
        Inicializa la conexion con InfluxDB usando los valores del .env
        """
        self.client = InfluxDBClient(
            url=config.INFLUX_URL,
            token=config.INFLUX_TOKEN,
            org=config.INFLUX_ORG,
        )
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.bucket = config.INFLUX_BUCKET
        self.org = config.INFLUX_ORG
        log.info(f"InfluxDB conectado en {config.INFLUX_URL}")

    def escribir_cpu(self, datos: dict) -> None:
        """
        Escribe las metricas de CPU de un switch en InfluxDB.

        Args:
            datos: Diccionario con datos del switch que incluye
                   nombre, rol, sitio y valores de cpu_5s, cpu_1m, cpu_5m
        """
        punto = (
            Point("cpu")
            .tag("device", datos["nombre"])
            .tag("role",   datos["rol"])
            .tag("site",   datos["sitio"])
            .field("cpu_5s", datos["cpu_5s"])
            .field("cpu_1m", datos["cpu_1m"])
            .field("cpu_5m", datos["cpu_5m"])
            .time(datetime.now(timezone.utc), WritePrecision.S)
        )

        self.write_api.write(bucket=self.bucket, org=self.org, record=punto)
        log.info(f"[{datos['nombre']}] CPU escrito -> "
                 f"5s={datos['cpu_5s']}% "
                 f"1m={datos['cpu_1m']}% "
                 f"5m={datos['cpu_5m']}%")

    def escribir_interfaces(self, datos: dict) -> None:
        """
        Escribe los errores de cada interfaz del switch en InfluxDB.

        Args:
            datos: Diccionario con datos del switch que incluye
                   la lista de interfaces con sus errores
        """
        for intf in datos["interfaces"]:
            punto = (
                Point("interfaces")
                .tag("device",    datos["nombre"])
                .tag("role",      datos["rol"])
                .tag("site",      datos["sitio"])
                .tag("interface", intf["nombre"])
                .tag("status",    intf["estado"])
                .field("errores_entrada", intf["errores_entrada"])
                .field("errores_crc",     intf["errores_crc"])
                .field("errores_salida",  intf["errores_salida"])
                .time(datetime.now(timezone.utc), WritePrecision.S)
            )

            self.write_api.write(bucket=self.bucket, org=self.org, record=punto)

        log.info(f"[{datos['nombre']}] "
                 f"{len(datos['interfaces'])} interfaces escritas en InfluxDB")

    def escribir_optica(self, datos: dict) -> None:
        """
        Escribe las metricas opticas de cada transceptor en InfluxDB.
        Calcula automaticamente la atenuacion del enlace (Tx - Rx).

        Args:
            datos: Diccionario con datos del switch que incluye
                   la lista de transceptores con rx_dbm y tx_dbm
        """
        for tx in datos["transceptores"]:
            # Calculo de atenuacion: diferencia entre lo que transmite
            # y lo que recibe el otro extremo
            atenuacion = round(abs(tx["tx_dbm"] - tx["rx_dbm"]), 2)

            punto = (
                Point("optica")
                .tag("device",    datos["nombre"])
                .tag("role",      datos["rol"])
                .tag("site",      datos["sitio"])
                .tag("interface", tx["interfaz"])
                .tag("status",    tx["estado"])
                .field("rx_dbm",      tx["rx_dbm"])
                .field("tx_dbm",      tx["tx_dbm"])
                .field("temperatura", tx["temp_c"])
                .field("atenuacion",  atenuacion)
                .time(datetime.now(timezone.utc), WritePrecision.S)
            )

            self.write_api.write(bucket=self.bucket, org=self.org, record=punto)

        log.info(f"[{datos['nombre']}] "
                 f"{len(datos['transceptores'])} transceptores escritos en InfluxDB")

    def cerrar(self) -> None:
        """
        Cierra la conexion con InfluxDB limpiamente.
        Siempre llamar esto al terminar el programa.
        """
        self.client.close()
        log.info("Conexion con InfluxDB cerrada")
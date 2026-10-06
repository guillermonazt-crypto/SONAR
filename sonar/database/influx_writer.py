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
from collections import deque
from datetime import datetime, timezone
import os
import threading
import time

from sonar.utils.logger import get_logger
from sonar.utils import config

log = get_logger(__name__)

# Si InfluxDB no responde, las métricas esperan en una cola local acotada (las
# más antiguas se descartan al llenarse) y se reintenta como mucho una vez por
# INFLUX_RETRY_SECONDS, sin frenar el ciclo de sondeo.
INFLUX_QUEUE_MAX = int(os.getenv("INFLUX_QUEUE_MAX", "100000"))
INFLUX_RETRY_SECONDS = float(os.getenv("INFLUX_RETRY_SECONDS", "30"))
INFLUX_TIMEOUT_MS = int(os.getenv("INFLUX_TIMEOUT_MS", "5000"))


class InfluxWriter:
    """
    Maneja la conexion y escritura de datos en InfluxDB.

    Cada metrica se escribe como un Point que contiene:
    - measurement: el tipo de dato (cpu, interfaces, optica)
    - tags: identificadores del dispositivo (no son valores numericos)
    - fields: los valores numericos reales
    - timestamp: cuando se tomo la medicion
    """

    def __init__(self, clock=time.monotonic, queue_max=INFLUX_QUEUE_MAX, retry_seconds=INFLUX_RETRY_SECONDS):
        """
        Inicializa la conexion con InfluxDB usando los valores del .env
        """
        self.client = InfluxDBClient(
            url=config.INFLUX_URL,
            token=config.INFLUX_TOKEN,
            org=config.INFLUX_ORG,
            timeout=INFLUX_TIMEOUT_MS,
        )
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.bucket = config.INFLUX_BUCKET
        self.org = config.INFLUX_ORG
        self._clock = clock
        self._retry_seconds = retry_seconds
        self._queue = deque(maxlen=queue_max)
        self._lock = threading.Lock()
        self._offline = False
        self._retry_at = 0.0
        log.info(f"InfluxDB conectado en {config.INFLUX_URL}")

    def estado(self) -> dict:
        """{disponible, en_cola}: se reporta a Django con el latido del worker."""
        with self._lock:
            return dict(disponible=not self._offline, en_cola=len(self._queue))

    @staticmethod
    def _lines(record) -> list:
        records = record if isinstance(record, list) else [record]
        return [item if isinstance(item, str) else item.to_line_protocol() for item in records]

    def _write(self, record) -> bool:
        """Escribe `record` (Point o lista); si InfluxDB no responde lo encola y devuelve False."""
        with self._lock:
            if self._offline and self._clock() < self._retry_at:
                self._queue.extend(self._lines(record))
                return False
            # Un solo hilo reintenta por ventana; los demás encolan mientras tanto.
            self._retry_at = self._clock() + self._retry_seconds
            backlog = list(self._queue)
            self._queue.clear()
        try:
            if backlog:
                self.write_api.write(bucket=self.bucket, org=self.org, record=backlog,
                                     write_precision=WritePrecision.S)
            self.write_api.write(bucket=self.bucket, org=self.org, record=record)
        except Exception as error:
            with self._lock:
                # Lo pendiente va antes de lo que otros hilos encolaron durante el intento.
                pending = backlog + self._lines(record) + list(self._queue)
                self._queue.clear()
                self._queue.extend(pending)
                was_online, self._offline = not self._offline, True
                queued = len(self._queue)
            if was_online:
                log.warning(f"InfluxDB no disponible ({error}); las métricas se encolan ({queued}) "
                            f"y se reintenta cada {self._retry_seconds:g}s sin pausar el sondeo.")
            return False
        with self._lock:
            recovered, self._offline = self._offline, False
        if recovered:
            log.info(f"InfluxDB disponible de nuevo; se enviaron {len(backlog)} métricas en cola.")
        return True

    def escribir_cpu(self, datos: dict) -> None:
        """
        Escribe las metricas de CPU de un switch en InfluxDB.

        Args:
            datos: Diccionario con datos del switch que incluye
                   nombre, rol, sitio y valores de cpu_5s, cpu_1m, cpu_5m
        """
        if all(datos.get(f) is None for f in ('cpu_5s', 'cpu_1m', 'cpu_5m')):
            return
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

        self._write(punto)
        log.info(f"[{datos['nombre']}] CPU escrito -> "
                 f"5s={datos['cpu_5s']}% "
                 f"1m={datos['cpu_1m']}% "
                 f"5m={datos['cpu_5m']}%")

    def escribir_sistema(self, datos: dict) -> None:
        """Guarda memoria y uptime; omite campos que el equipo no publique."""
        fields = {
            key: datos.get(key) for key in (
                'memoria_usada_pct', 'memoria_total_bytes',
                'memoria_usada_bytes', 'uptime_segundos')
            if datos.get(key) is not None
        }
        if not fields:
            return
        point = Point("sistema").tag("device", datos["nombre"]).tag("role", datos["rol"]).tag("site", datos["sitio"])
        for key, value in fields.items():
            point.field(key, value)
        point.time(datetime.now(timezone.utc), WritePrecision.S)
        self._write(point)

    def escribir_interfaces(self, datos: dict) -> None:
        """
        Escribe los errores de cada interfaz del switch en InfluxDB.

        Args:
            datos: Diccionario con datos del switch que incluye
                   la lista de interfaces con sus errores
        """
        ahora = datetime.now(timezone.utc)
        # Un solo write por switch. El estado va como field, no como tag:
        # como tag, cada cambio up/down abría una serie nueva en InfluxDB.
        puntos = []
        for intf in datos["interfaces"]:
            punto = (
                Point("interfaces")
                .tag("device",    datos["nombre"])
                .tag("role",      datos["rol"])
                .tag("site",      datos["sitio"])
                .tag("interface", intf["nombre"])
                .field("estado", intf["estado"])
                .time(ahora, WritePrecision.S)
            )
            for field in ('errores_entrada', 'errores_crc', 'errores_salida', 'octetos_entrada', 'octetos_salida'):
                value = intf.get(field)
                if value is not None:
                    punto.field(field, value)
            puntos.append(punto)

        if puntos:
            self._write(puntos)

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
        ahora = datetime.now(timezone.utc)
        puntos = []
        transceptores = datos.get("transceptores") or []
        for tx in transceptores:
            atenuacion = None
            if tx.get("tx_dbm") is not None and tx.get("rx_dbm") is not None:
                atenuacion = round(abs(tx["tx_dbm"] - tx["rx_dbm"]), 2)

            punto = (
                Point("optica")
                .tag("device",    datos["nombre"])
                .tag("role",      datos["rol"])
                .tag("site",      datos["sitio"])
                .tag("interface", tx["interfaz"])
                .field("estado",  tx["estado"])
                .time(ahora, WritePrecision.S)
            )
            for field, value in (("rx_dbm", tx.get("rx_dbm")), ("tx_dbm", tx.get("tx_dbm")),
                                 ("temperatura", tx.get("temp_c")), ("voltaje_v", tx.get("voltaje_v")),
                                 ("bias_ma", tx.get("bias_ma")), ("atenuacion", atenuacion)):
                if value is not None:
                    punto.field(field, value)

            puntos.append(punto)

        if puntos:
            self._write(puntos)

        log.info(f"[{datos['nombre']}] "
                 f"{len(transceptores)} transceptores escritos en InfluxDB")

    def escribir_sintetico(self, resultados: list) -> None:
        """Escribe las pruebas sintéticas (ping): latencia, jitter y pérdida por equipo."""
        ahora = datetime.now(timezone.utc)
        puntos = []
        for item in resultados:
            device, result = item["dispositivo"], item["resultado"]
            punto = (
                Point("sintetico")
                .tag("device", device.get("name", device["hostname"]))
                .tag("role",   device.get("role", "access"))
                .tag("site",   device.get("site", ""))
                .tag("target", device["hostname"])
                .field("alcanzable", 1 if result["alcanzable"] else 0)
                .field("enviados", result["enviados"])
                .field("recibidos", result["recibidos"])
                .time(ahora, WritePrecision.S)
            )
            for field in ("perdida_pct", "rtt_min_ms", "rtt_avg_ms", "rtt_max_ms", "jitter_ms"):
                if result.get(field) is not None:
                    punto.field(field, float(result[field]))
            puntos.append(punto)
        if puntos:
            self._write(puntos)

    def cerrar(self) -> None:
        """
        Cierra la conexion con InfluxDB limpiamente.
        Siempre llamar esto al terminar el programa.
        """
        self.write_api.close()
        self.client.close()
        log.info("Conexion con InfluxDB cerrada")

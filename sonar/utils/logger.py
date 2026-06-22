# sonar/utils/logger.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Este modulo centraliza el sistema de logging de SONAR.
# Todos los demas modulos importan su logger desde aqui.
# Usamos Rich para tener output con colores y formato en consola.

import logging
import os
from rich.logging import RichHandler
from rich.console import Console

# Consola compartida para todo el proyecto
console = Console()


def get_logger(name: str) -> logging.Logger:
    """
    Crea y retorna un logger configurado con Rich.

    Args:
        name: Nombre del modulo que solicita el logger.
              Generalmente se pasa __name__ para identificar
              de donde viene cada mensaje.

    Returns:
        Logger configurado y listo para usar.

    Ejemplo de uso en otro modulo:
        from sonar.utils.logger import get_logger
        log = get_logger(__name__)
        log.info("Conectando al switch...")
    """
    # El nivel de log se controla desde el archivo .env
    # INFO muestra mensajes normales
    # DEBUG muestra todo, incluyendo detalles tecnicos
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_path=False,
            )
        ],
        force=True,
    )

    return logging.getLogger(name)
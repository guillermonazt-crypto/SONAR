"""Una pasada de descubrimiento (vecinos CDP y, si hay DISCOVERY_SUBNETS, barrido SNMP)."""
import asyncio
import sys
from pathlib import Path

from django.core.management.base import BaseCommand

# El paquete del worker (sonar/) vive en la raíz del proyecto, junto a backend/.
ROOT = str(Path(__file__).resolve().parents[4])


class Command(BaseCommand):
    help = 'Busca equipos fuera del inventario. Usa DISCOVERY_SUBNETS de .env para el barrido SNMP.'

    def handle(self, *args, **options):
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from sonar.discovery import run
        count = asyncio.run(run(force=True))
        self.stdout.write(f'{count} equipo(s) candidato(s) pendientes de revisar.')

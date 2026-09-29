"""Respalda la configuración de los switches por SSH (ver switches/backups.py)."""
from django.core.management.base import BaseCommand

from switches.backups import backup_all
from switches.models import Switch


class Command(BaseCommand):
    help = 'Respalda show running-config de los switches activos (o de --switch ID).'

    def add_arguments(self, parser):
        parser.add_argument('--switch', type=int, action='append', help='ID del switch (se puede repetir)')

    def handle(self, *args, **options):
        switches = Switch.objects.filter(pk__in=options['switch']) if options['switch'] else None
        for result in backup_all(switches=switches):
            state = 'ok' if result.exito else f'error: {result.error}'
            self.stdout.write(f'{result.switch.nombre}: {state}')

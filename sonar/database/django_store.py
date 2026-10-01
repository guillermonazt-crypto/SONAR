import threading
from django.db import connections, close_old_connections

_lock = threading.Lock()

def record_poll(dispositivo, datos):
    if 'django_id' not in dispositivo:
        return
    from switches.services import record_poll as save
    # SQLite admite un escritor a la vez; serializar las escrituras del worker.
    with _lock:
        close_old_connections()
        try:
            save(dispositivo['django_id'], dispositivo['hostname'], datos)
        finally:
            connections.close_all()


def notify_alerts(dispositivo):
    """Evalúa el switch tras el sondeo y envía la alerta fuera del lock de SQLite."""
    if 'django_id' not in dispositivo:
        return
    from switches.alerts import evaluate, send
    with _lock:
        close_old_connections()
        try:
            message = evaluate(dispositivo['django_id'])
        finally:
            connections.close_all()
    send(message)


class BackupScheduler:
    """Respalda configuraciones cada BACKUP_INTERVAL_HOURS si BACKUP_ENABLED=true."""

    def __init__(self, clock=None):
        import time
        self.clock = clock or time.monotonic
        self.last = None

    def due(self):
        import os
        if os.getenv('BACKUP_ENABLED', 'false').strip().lower() not in ('1', 'true', 'si', 'sí', 'yes'):
            return False
        hours = float(os.getenv('BACKUP_INTERVAL_HOURS', '24'))
        return self.last is None or self.clock() - self.last >= hours * 3600

    async def maybe_run(self):
        import asyncio
        if not self.due():
            return None
        self.last = self.clock()
        return await asyncio.to_thread(self._run)

    def _run(self):
        from sonar.utils.config import load_django_inventory
        load_django_inventory()  # inicializa Django si hace falta
        from switches.backups import backup_all
        with _lock:
            close_old_connections()
            try:
                results = backup_all()
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Los respaldos fallaron')
                return None
            finally:
                connections.close_all()
        return results

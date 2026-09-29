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

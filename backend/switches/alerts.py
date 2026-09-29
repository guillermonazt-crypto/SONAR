"""Notificaciones cuando un switch entra o sale del estado de riesgo.

Canales opcionales, configurados en .env:
- Correo: ALERT_EMAIL_TO (lista separada por comas) + EMAIL_* de Django.
- Telegram: TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID.
- Webhook (Teams, Slack, Google Chat): ALERT_WEBHOOK_URL, recibe {"text": ...}.
"""
import json
import logging
import os
from datetime import timedelta
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.core.mail import send_mail
from django.utils import timezone

from .health import assess, port_stats, thresholds_by_role
from .models import Switch

log = logging.getLogger(__name__)


def cooldown():
    return timedelta(minutes=int(os.getenv('ALERT_COOLDOWN_MINUTES', '30')))


def evaluate(switch_id, now=None):
    """Actualiza el nivel de alerta y devuelve el mensaje a enviar, o None.

    Avisa al pasar a riesgo (rojo) y al recuperarse. El cooldown evita
    repetir avisos cuando un equipo oscila entre estados.
    """
    now = now or timezone.now()
    switch = Switch.objects.select_related('plantel').filter(pk=switch_id).first()
    if switch is None:
        return None
    level, reasons = assess(switch, port_stats([switch.pk], now)[switch.pk],
                            thresholds_by_role()[switch.rol], now)
    was_critical = switch.nivel_alerta == 'critical'
    is_critical = level == 'critical'
    if was_critical == is_critical:
        if switch.nivel_alerta != level:
            Switch.objects.filter(pk=switch.pk).update(nivel_alerta=level)
        return None
    recent = switch.alerta_enviada and now - switch.alerta_enviada < cooldown()
    Switch.objects.filter(pk=switch.pk).update(nivel_alerta=level,
                                               alerta_enviada=switch.alerta_enviada if recent else now)
    if recent:
        return None
    where = f'{switch.nombre} ({switch.hostname}) · {switch.plantel.nombre}'
    if is_critical:
        detail = '; '.join(r['text'] for r in reasons if r['level'] == 'critical')
        return f'🔴 SONAR: {where} en riesgo. {detail}'
    return f'🟢 SONAR: {where} se recuperó.'


def _post(url, payload):
    request = Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=10):
        pass


def send(message):
    """Envía por cada canal configurado; un canal caído no bloquea a los demás."""
    if not message:
        return
    recipients = [a.strip() for a in os.getenv('ALERT_EMAIL_TO', '').split(',') if a.strip()]
    token, chat = os.getenv('TELEGRAM_BOT_TOKEN', ''), os.getenv('TELEGRAM_CHAT_ID', '')
    webhook = os.getenv('ALERT_WEBHOOK_URL', '')
    channels = []
    if recipients:
        channels.append(('correo', lambda: send_mail('Alerta SONAR', message, None, recipients)))
    if token and chat:
        channels.append(('telegram', lambda: _post(
            f'https://api.telegram.org/bot{quote(token, safe=":")}/sendMessage', dict(chat_id=chat, text=message))))
    if webhook:
        channels.append(('webhook', lambda: _post(webhook, dict(text=message))))
    for name, deliver in channels:
        try:
            deliver()
        except Exception as error:
            log.error('No se pudo enviar la alerta por %s: %s', name, error)

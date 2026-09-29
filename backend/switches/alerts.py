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
from .models import Alerta, Mantenimiento, Switch

log = logging.getLogger(__name__)


def cooldown():
    return timedelta(minutes=int(os.getenv('ALERT_COOLDOWN_MINUTES', '30')))


def evaluate(switch_id, now=None):
    """Actualiza el nivel de alerta y devuelve el mensaje a enviar, o None.

    Avisa al pasar a riesgo (rojo) y al recuperarse. Cada episodio queda como
    Alerta (centro de alertas). El cooldown evita repetir avisos cuando un
    equipo oscila; en una ventana de mantenimiento se registra sin notificar.
    """
    now = now or timezone.now()
    switch = Switch.objects.select_related('plantel').filter(pk=switch_id).first()
    if switch is None:
        return None
    level, reasons = assess(switch, port_stats([switch.pk], now)[switch.pk],
                            thresholds_by_role()[switch.rol], now)
    was_critical = switch.nivel_alerta == 'critical'
    is_critical = level == 'critical'
    open_alert = Alerta.objects.filter(switch=switch, fin__isnull=True).first()
    critical_reasons = [r for r in reasons if r['level'] == 'critical']
    if was_critical == is_critical:
        if switch.nivel_alerta != level:
            Switch.objects.filter(pk=switch.pk).update(nivel_alerta=level)
        if is_critical and open_alert and open_alert.motivos != critical_reasons:
            Alerta.objects.filter(pk=open_alert.pk).update(motivos=critical_reasons)
        return None
    maintenance = Mantenimiento.por_switch([switch], now).get(switch.pk)
    recent = switch.alerta_enviada and now - switch.alerta_enviada < cooldown()
    if is_critical:
        notify = not recent and maintenance is None
        Alerta.objects.create(switch=switch, motivos=critical_reasons, inicio=now,
                              notificada=notify, en_mantenimiento=maintenance is not None)
    else:
        if open_alert:
            Alerta.objects.filter(pk=open_alert.pk).update(fin=now)
        # Sólo se avisa la recuperación de un episodio que sí se notificó.
        notify = not recent and maintenance is None and (open_alert is None or open_alert.notificada)
    Switch.objects.filter(pk=switch.pk).update(nivel_alerta=level,
                                               alerta_enviada=now if notify else switch.alerta_enviada)
    if not notify:
        return None
    where = f'{switch.nombre} ({switch.hostname}) · {switch.plantel.nombre}'
    if is_critical:
        detail = '; '.join(r['text'] for r in critical_reasons)
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

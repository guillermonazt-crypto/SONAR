"""Notificaciones cuando un switch entra o sale del estado de riesgo.

Canales opcionales, configurados en .env:
- Correo: ALERT_EMAIL_TO (lista separada por comas) + EMAIL_* de Django.
- Telegram: TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID.
- Webhook (Teams, Slack, Google Chat): ALERT_WEBHOOK_URL, recibe {"text": ...}.
- Escalamiento: ALERT_ESCALATION_EMAIL_TO recibe además los avisos de alertas
  que siguen sin reconocer después de UmbralRol.escalar_minutos.
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


class Notice(str):
    """Mensaje a enviar. Si `escalamiento` es True también va a ALERT_ESCALATION_EMAIL_TO."""
    escalamiento = False


def _where(switch):
    return f'{switch.nombre} ({switch.hostname}) · {switch.plantel.nombre}'


def _escalation(switch, alert, reasons, minutes, maintenance, now):
    """Aviso único cuando un episodio sigue abierto sin reconocer más de `minutes`."""
    if (not minutes or alert is None or alert.reconocida_en or alert.escalada_en or alert.en_mantenimiento
            or maintenance is not None or now - alert.inicio < timedelta(minutes=minutes)):
        return None
    # Condicional: si otro proceso ya la escaló, no se repite el aviso.
    if not Alerta.objects.filter(pk=alert.pk, escalada_en__isnull=True).update(escalada_en=now):
        return None
    elapsed = round((now - alert.inicio).total_seconds() / 60)
    detail = '; '.join(r['text'] for r in reasons)
    notice = Notice(f'⏫ SONAR: {_where(switch)} sigue en riesgo desde hace {elapsed} min sin que nadie '
                    f'reconozca la alerta. {detail}')
    notice.escalamiento = True
    return notice


def evaluate(switch_id, now=None):
    """Actualiza el nivel de alerta y devuelve el mensaje a enviar, o None.

    Avisa al pasar a riesgo (rojo) y al recuperarse. Cada episodio queda como
    Alerta (centro de alertas) y nunca hay dos abiertas para el mismo switch.
    El cooldown evita repetir avisos cuando un equipo oscila; en una ventana de
    mantenimiento se registra sin notificar. Si el episodio sigue abierto sin
    reconocer más de UmbralRol.escalar_minutos, se escala una sola vez.
    """
    now = now or timezone.now()
    switch = Switch.objects.select_related('plantel').filter(pk=switch_id).first()
    if switch is None:
        return None
    thresholds = thresholds_by_role()[switch.rol]
    level, reasons = assess(switch, port_stats([switch.pk], now)[switch.pk], thresholds, now)
    was_critical = switch.nivel_alerta == 'critical'
    is_critical = level == 'critical'
    open_alerts = list(Alerta.objects.filter(switch=switch, fin__isnull=True).order_by('inicio'))
    open_alert = open_alerts[0] if open_alerts else None
    if len(open_alerts) > 1:
        # Duplicados de versiones anteriores o de un reinicio a medio ciclo: se conserva el primero.
        Alerta.objects.filter(pk__in=[a.pk for a in open_alerts[1:]]).update(fin=now)
    critical_reasons = [r for r in reasons if r['level'] == 'critical']
    maintenance = Mantenimiento.por_switch([switch], now).get(switch.pk)
    if is_critical and open_alert:
        # Episodio en curso (o nivel_alerta se perdió): se actualiza, nunca se duplica ni se re-notifica.
        if open_alert.motivos != critical_reasons:
            Alerta.objects.filter(pk=open_alert.pk).update(motivos=critical_reasons)
        if not was_critical:
            Switch.objects.filter(pk=switch.pk).update(nivel_alerta=level)
            return None
        return _escalation(switch, open_alert, critical_reasons, thresholds['escalar_minutos'], maintenance, now)
    if was_critical == is_critical:
        if switch.nivel_alerta != level:
            Switch.objects.filter(pk=switch.pk).update(nivel_alerta=level)
        if is_critical:
            # En rojo sin episodio registrado (se borró a mano): se registra sin volver a avisar.
            Alerta.objects.create(switch=switch, motivos=critical_reasons, inicio=now,
                                  en_mantenimiento=maintenance is not None)
        elif open_alert:
            # Abierta sin transición (nivel editado a mano): se cierra sin avisar.
            Alerta.objects.filter(pk=open_alert.pk).update(fin=now)
        return None
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
    if is_critical:
        detail = '; '.join(r['text'] for r in critical_reasons)
        return Notice(f'🔴 SONAR: {_where(switch)} en riesgo. {detail}')
    return Notice(f'🟢 SONAR: {_where(switch)} se recuperó.')


def _post(url, payload):
    request = Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=10):
        pass


def _emails(variable):
    return [a.strip() for a in os.getenv(variable, '').split(',') if a.strip()]


def send(message):
    """Envía por cada canal configurado; un canal caído no bloquea a los demás."""
    if not message:
        return
    recipients = _emails('ALERT_EMAIL_TO')
    if getattr(message, 'escalamiento', False):
        recipients += [a for a in _emails('ALERT_ESCALATION_EMAIL_TO') if a not in recipients]
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

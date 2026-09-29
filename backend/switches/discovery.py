"""Parte Django del descubrimiento (sonar/discovery.py): candidatos y su registro."""
from django.db.models import Q
from django.utils import timezone

from .models import Descubierto, Puerto, Switch


def known_addresses():
    return set(Switch.objects.values_list('hostname', flat=True))


def cdp_candidates():
    """Vecinos CDP con IP que no están en el inventario (switches, routers, APs)."""
    known = known_addresses()
    ports = (Puerto.objects.select_related('switch').exclude(vecino_ip__isnull=True)
             .exclude(vecino_ip__in=known).order_by('switch__nombre', 'indice'))
    found = {}
    for port in ports:
        found.setdefault(port.vecino_ip, dict(
            ip=port.vecino_ip, nombre=port.vecino_nombre or '', descripcion='',
            plataforma=port.vecino_plataforma or '', origen='cdp',
            visto_desde=f'{port.switch.nombre} · {port.nombre}'))
    return list(found.values())


def record_candidates(items, now=None):
    """Crea o actualiza candidatos; respeta los que un editor ya ignoró."""
    now = now or timezone.now()
    known = known_addresses()
    count = 0
    for item in items:
        if item['ip'] in known:
            continue
        candidate, created = Descubierto.objects.get_or_create(ip=item['ip'], defaults=dict(
            nombre=item.get('nombre', '')[:255], descripcion=item.get('descripcion', '')[:1000],
            plataforma=item.get('plataforma', '')[:255], origen=item.get('origen', 'barrido'),
            visto_desde=item.get('visto_desde', '')[:255], primera_vez=now, ultima_vez=now))
        if not created:
            for field in ('nombre', 'descripcion', 'plataforma', 'visto_desde'):
                if item.get(field):
                    setattr(candidate, field, item[field][:1000 if field == 'descripcion' else 255])
            candidate.ultima_vez = now
            candidate.save()
        if candidate.estado == 'pendiente':
            count += 1
    return count


def pending():
    """Candidatos por revisar: ni ignorados ni ya dados de alta."""
    return (Descubierto.objects.filter(estado='pendiente')
            .exclude(Q(ip__in=known_addresses())).order_by('-ultima_vez'))

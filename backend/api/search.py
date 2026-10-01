"""Buscador global: ¿en qué switch y puerto está conectado este equipo?

Busca en lo que el worker ya guarda por puerto (IP y MAC del equipo, MAC del
teléfono y descripción) y en el nombre/IP de los switches.
"""
import re

from django.db.models import Q, TextField, Value
from django.db.models.functions import Lower, Replace

from switches.models import Puerto, Switch

LIMIT = 50
MIN_LENGTH = 3
HEX = re.compile(r'^[0-9a-f]+$')
# IPv4 completa o parcial ("10.1.", "192.168.27.4"); lo demás puede ser MAC en cualquier formato.
IP_PARTIAL = re.compile(r'^\d{1,3}(\.\d{0,3}){1,3}$')


def compact_mac(text):
    """'AA-BB-CC', 'aabb.cc' o 'aa:bb:cc' → 'aabbcc' (vacío si no parece MAC)."""
    compact = re.sub(r'[\s:.\-]', '', text.lower())
    return compact if len(compact) >= 4 and HEX.match(compact) else ''


def _mac_field(name):
    """Campo MAC sin separadores, para comparar contra cualquier formato escrito."""
    return Replace(Lower(name), Value(':'), Value(''), output_field=TextField())


def _values(text):
    return [value.strip() for value in (text or '').split(',') if value.strip()]


def _port_match(port, query, mac):
    """Qué campo coincidió y si fue exacto (para ordenar los resultados)."""
    for field, label in (('ip_equipo', 'ip'), ('mac_equipo', 'mac'), ('mac_telefono', 'telefono')):
        for value in _values(getattr(port, field)):
            if field == 'ip_equipo':
                if value == query:
                    return label, value, True
                if query in value:
                    return label, value, False
            elif mac and mac in value.replace(':', ''):
                return label, value, value.replace(':', '') == mac
    return 'descripcion', port.descripcion, False


def search(query, plantel=None):
    query = (query or '').strip()
    if len(query) < MIN_LENGTH:
        return dict(query=query, puertos=[], switches=[])
    is_ip = bool(IP_PARTIAL.match(query))
    mac = '' if is_ip else compact_mac(query)
    ports = Puerto.objects.filter(es_fisico=True).select_related('switch__plantel')
    switches = Switch.objects.select_related('plantel')
    if plantel is not None:
        ports = ports.filter(switch__plantel_id=plantel)
        switches = switches.filter(plantel_id=plantel)
    if is_ip:
        filters = Q(ip_equipo__contains=query)
    else:
        filters = Q(ip_equipo__icontains=query) | Q(descripcion__icontains=query)
    if mac:
        ports = ports.annotate(mac_eq=_mac_field('mac_equipo'), mac_tel=_mac_field('mac_telefono'))
        filters |= Q(mac_eq__contains=mac) | Q(mac_tel__contains=mac)
    results = []
    for port in ports.filter(filters)[:LIMIT * 2]:
        field, value, exact = _port_match(port, query, mac)
        switch = port.switch
        results.append(dict(
            id=port.id, nombre=port.nombre, descripcion=port.descripcion,
            estado_operativo=port.estado_operativo, vlan=port.vlan, voice_vlan=port.voice_vlan, es_trunk=port.es_trunk,
            ip_equipo=port.ip_equipo, mac_equipo=port.mac_equipo, mac_telefono=port.mac_telefono,
            coincide=field, valor=value, exacto=exact, actualizado=port.actualizado.isoformat(),
            switch=dict(id=switch.id, nombre=switch.nombre, hostname=switch.hostname,
                        plantel=switch.plantel_id, plantel_nombre=switch.plantel.nombre),
        ))
    # Coincidencias exactas primero; los troncales al final (ahí aparecen MACs de otros switches).
    results.sort(key=lambda item: (not item['exacto'], item['es_trunk'], item['coincide'] == 'descripcion', item['switch']['nombre'], item['nombre']))
    switches = (switches
                .filter(Q(nombre__icontains=query) | Q(hostname__contains=query))[:10])
    return dict(
        query=query,
        puertos=results[:LIMIT],
        switches=[dict(id=s.id, nombre=s.nombre, hostname=s.hostname, plantel=s.plantel_id,
                       plantel_nombre=s.plantel.nombre, activo=s.activo) for s in switches],
    )

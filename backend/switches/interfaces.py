import re

PHYSICAL_INTERFACE_RE = re.compile(
    r'^(?:FastEthernet0/\d+|GigabitEthernet0/[1-9]\d*|'
    r'GigabitEthernet\d+/\d+/\d+|TenGigabitEthernet\d+/\d+/\d+|'
    r'TwentyFiveGigE\d+/\d+/\d+|FortyGigabitEthernet\d+/\d+/\d+)$'
)
GENERIC_PHYSICAL_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_.-]*\d+/\d+(?:/\d+)?$')
LOGICAL_TOKENS = ('vlan', 'loopback', 'tunnel', 'null', 'stack', 'bluetooth', 'port-channel', 'portchannel', 'unrouted')


def is_physical_interface(name):
    """Conectores reales del chasis; descarta interfaces lógicas históricas."""
    name = (name or '').strip()
    if any(token in name.lower() for token in LOGICAL_TOKENS):
        return False
    if name.endswith('/0/0') or name.endswith('0/0'):
        return False
    return bool(PHYSICAL_INTERFACE_RE.fullmatch(name) or GENERIC_PHYSICAL_NAME_RE.fullmatch(name))

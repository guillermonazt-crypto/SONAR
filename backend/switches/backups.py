"""Respaldo de configuraciones por SSH (show running-config) con historial y diferencias.

Apagado por defecto. Variables en .env:
- BACKUP_ENABLED=true para que el worker respalde cada BACKUP_INTERVAL_HOURS (24).
- BACKUP_SSH_USER y BACKUP_SSH_PASSWORD o BACKUP_SSH_KEY_FILE (usuario de sólo lectura, privilege 15 o
  'show running-config' autorizado); BACKUP_SSH_PORT (22), BACKUP_TIMEOUT (30 s).
- BACKUP_COMMAND (por defecto 'show running-config').
- BACKUP_SSH_KNOWN_HOSTS: archivo known_hosts; si se define, se rechazan llaves desconocidas.
Requiere el paquete paramiko (pip install paramiko) sólo cuando se activa.

Sólo se guarda una versión nueva cuando la configuración cambió de verdad: se
descartan líneas volátiles como la hora del último cambio.
"""
import difflib
import hashlib
import os
import re
import time

from django.utils import timezone

from .models import Respaldo, Switch

VOLATILE = re.compile(r'^(! (Last configuration change|NVRAM config last updated)|Current configuration :|'
                      r'Building configuration|ntp clock-period)')
SECRET = re.compile(r'(\b(?:secret|password|key-string|pre-shared-key|community|key 7|key 0|md5)\s+(?:\d+\s+)?)\S+',
                    re.IGNORECASE)


def settings():
    return dict(
        enabled=os.getenv('BACKUP_ENABLED', 'false').strip().lower() in ('1', 'true', 'si', 'sí', 'yes'),
        user=os.getenv('BACKUP_SSH_USER', ''), password=os.getenv('BACKUP_SSH_PASSWORD', ''),
        key_file=os.getenv('BACKUP_SSH_KEY_FILE', '') or None, port=int(os.getenv('BACKUP_SSH_PORT', '22')),
        known_hosts=os.getenv('BACKUP_SSH_KNOWN_HOSTS', '') or None,
        timeout=float(os.getenv('BACKUP_TIMEOUT', '30')),
        command=os.getenv('BACKUP_COMMAND', 'show running-config'),
        interval_hours=float(os.getenv('BACKUP_INTERVAL_HOURS', '24')),
    )


def clean(config):
    """Quita encabezados y líneas volátiles para comparar sólo cambios reales."""
    lines = [line.rstrip() for line in config.replace('\r\n', '\n').split('\n')]
    lines = [line for line in lines if not VOLATILE.match(line.strip())]
    # El eco del comando y el prompt final no son parte de la configuración.
    while lines and (not lines[0].strip() or lines[0].strip().endswith(('running-config', 'length 0'))):
        lines.pop(0)
    while lines and (not lines[-1].strip() or re.fullmatch(r'\S+[#>]', lines[-1].strip())):
        lines.pop()
    return '\n'.join(lines) + '\n'


def redact(config):
    """Oculta contraseñas y comunidades para quien no es administrador."""
    return SECRET.sub(lambda match: match.group(1) + '<oculto>', config)


def ssh_fetch(host, config):
    """Ejecuta el comando por SSH con paramiko y devuelve la salida."""
    try:
        import paramiko
    except ImportError as error:
        raise RuntimeError('Instala paramiko para respaldar configuraciones (pip install paramiko).') from error
    client = paramiko.SSHClient()
    if config.get('known_hosts'):
        # Recomendado: sólo se conecta a equipos cuya llave ya está registrada.
        client.load_host_keys(config['known_hosts'])
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        # Sin archivo de llaves se acepta la del equipo y se deja aviso en el log.
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
    client.connect(host, port=config['port'], username=config['user'], password=config['password'] or None,
                   key_filename=config['key_file'], timeout=config['timeout'], look_for_keys=False, allow_agent=False)
    try:
        shell = client.invoke_shell(width=512)
        shell.settimeout(config['timeout'])
        output = b''

        def read_until_prompt(deadline):
            nonlocal output
            chunk = b''
            while time.monotonic() < deadline:
                if shell.recv_ready():
                    chunk += shell.recv(65535)
                    if re.search(rb'\n\S+#\s*$', chunk):
                        break
                else:
                    time.sleep(0.2)
            output += chunk

        deadline = time.monotonic() + config['timeout']
        shell.send('terminal length 0\n')
        read_until_prompt(deadline)
        output = b''
        shell.send(config['command'] + '\n')
        read_until_prompt(time.monotonic() + config['timeout'])
        return output.decode('utf-8', errors='replace')
    finally:
        client.close()


def backup_switch(switch, fetch=ssh_fetch, config=None, now=None):
    """Respalda un switch; devuelve el Respaldo creado o el último si no cambió."""
    config = config or settings()
    now = now or timezone.now()
    last = Respaldo.objects.filter(switch=switch, exito=True).order_by('-momento').first()
    try:
        content = clean(fetch(switch.hostname, config))
        if len(content.strip()) < 20:
            raise RuntimeError('La salida está vacía: revisa permisos del usuario SSH.')
    except Exception as error:
        return Respaldo.objects.create(switch=switch, momento=now, exito=False, error=str(error)[:1000])
    digest = hashlib.sha256(content.encode()).hexdigest()
    if last and last.hash == digest:
        Respaldo.objects.filter(pk=last.pk).update(verificado=now)
        last.verificado = now
        return last
    added = removed = 0
    if last:
        for line in difflib.unified_diff(last.contenido.splitlines(), content.splitlines(), lineterm='', n=0):
            if line.startswith('+') and not line.startswith('+++'):
                added += 1
            elif line.startswith('-') and not line.startswith('---'):
                removed += 1
    return Respaldo.objects.create(switch=switch, momento=now, verificado=now, exito=True, contenido=content,
                                   hash=digest, lineas_agregadas=added, lineas_eliminadas=removed)


def backup_all(fetch=ssh_fetch, config=None, switches=None):
    config = config or settings()
    switches = switches if switches is not None else Switch.objects.filter(activo=True, plantel__activo=True)
    return [backup_switch(switch, fetch, config) for switch in switches]


def diff(previous, current):
    return '\n'.join(difflib.unified_diff(
        previous.splitlines() if previous else [], current.splitlines(),
        fromfile='versión anterior', tofile='esta versión', lineterm=''))

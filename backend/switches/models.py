# backend/switches/models.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Modelos para switches y puertos de red.

# pyrefly: ignore [missing-import]
from django.db import models
from planteles.models import Plantel


class Switch(models.Model):
    """
    Representa un switch Cisco Catalyst en la red de la UAEH.
    """
    ROLES = [
        ('core',         'Core'),
        ('distribution', 'Distribución'),
        ('access',       'Acceso'),
    ]

    nombre   = models.CharField(max_length=100)
    hostname = models.GenericIPAddressField(unique=True)
    rol      = models.CharField(max_length=20, choices=ROLES, default='access')
    plantel  = models.ForeignKey(
        Plantel,
        on_delete=models.CASCADE,
        related_name='switches'
    )
    activo   = models.BooleanField(default=True)
    creado   = models.DateTimeField(auto_now_add=True)
    ultima_consulta = models.DateTimeField(null=True, blank=True)
    lectura_correcta = models.BooleanField(null=True, default=None)
    cpu_5s = models.IntegerField(null=True, blank=True)
    cpu_1m = models.IntegerField(null=True, blank=True)
    cpu_5m = models.IntegerField(null=True, blank=True)
    memoria_usada_pct = models.FloatField(null=True, blank=True)
    memoria_total_bytes = models.BigIntegerField(null=True, blank=True)
    memoria_usada_bytes = models.BigIntegerField(null=True, blank=True)
    uptime_segundos = models.BigIntegerField(null=True, blank=True)
    ultimo_reinicio = models.DateTimeField(null=True, blank=True)
    modelo = models.CharField(max_length=100, null=True, blank=True)
    firmware = models.CharField(max_length=100, null=True, blank=True)
    # Último nivel notificado por las alertas del worker (ok/warning/critical).
    nivel_alerta = models.CharField(max_length=10, default='ok')
    alerta_enviada = models.DateTimeField(null=True, blank=True)
    # Salud física (CISCO-ENVMON-MIB): temperatura máxima y componentes
    # [{tipo: temperatura|ventilador|fuente, nombre, estado: ok|warning|critical, valor}].
    temperatura_c = models.FloatField(null=True, blank=True)
    hardware = models.JSONField(default=list, null=True, blank=True)
    # PoE (POWER-ETHERNET-MIB): presupuesto y consumo del switch en watts.
    poe_presupuesto_w = models.FloatField(null=True, blank=True)
    poe_consumo_w = models.FloatField(null=True, blank=True)

    class Meta:
        verbose_name = "Switch"
        verbose_name_plural = "Switches"
        ordering = ['plantel', 'nombre']

    def __str__(self):
        return f"{self.nombre} ({self.hostname})"


class Puerto(models.Model):
    """
    Estado actual de un puerto del switch.
    Se actualiza cada ciclo de polling SNMP.
    """
    ESTADOS = [
        ('verde',    'Uso general'),
        ('rojo',     'Dañado'),
        ('naranja',  'Trunk'),
        ('amarillo', 'AP Native VLAN'),
        ('azul',     'Telefonía'),
        ('gris',     'Desconectado'),
    ]

    switch         = models.ForeignKey(
        Switch,
        on_delete=models.CASCADE,
        related_name='puertos'
    )
    nombre         = models.CharField(max_length=50)   # GigabitEthernet1/0/1
    descripcion    = models.TextField(null=True, blank=True)
    indice         = models.IntegerField()              # ifIndex SNMP
    estado         = models.CharField(max_length=20, choices=ESTADOS, default='gris')
    vlan           = models.IntegerField(null=True, blank=True)
    voice_vlan     = models.IntegerField(null=True, blank=True)
    es_trunk       = models.BooleanField(default=False)
    estado_operativo = models.CharField(max_length=20, default="unknown")
    ip_equipo = models.TextField(null=True, blank=True)
    mac_equipo = models.TextField(null=True, blank=True)
    mac_telefono = models.TextField(null=True, blank=True)
    dhcp = models.BooleanField(null=True, blank=True)
    errores_crc = models.BigIntegerField(null=True, blank=True)
    errores_entrada = models.BigIntegerField(null=True, blank=True)
    errores_salida  = models.BigIntegerField(null=True, blank=True)
    # Errores nuevos (entrada+salida+CRC) desde el sondeo anterior: los
    # contadores SNMP son acumulados desde el arranque del equipo.
    errores_nuevos  = models.BigIntegerField(null=True, blank=True)
    ultimo_error    = models.DateTimeField(null=True, blank=True)
    es_fisico       = models.BooleanField(default=True)
    octetos_entrada = models.BigIntegerField(null=True, blank=True)
    octetos_salida  = models.BigIntegerField(null=True, blank=True)
    actualizado    = models.DateTimeField(auto_now=True)
    # Vecino CDP (otro switch, AP, router); los teléfonos van en mac_telefono.
    vecino_nombre = models.CharField(max_length=255, null=True, blank=True)
    vecino_puerto = models.CharField(max_length=100, null=True, blank=True)
    vecino_plataforma = models.CharField(max_length=255, null=True, blank=True)
    vecino_ip = models.GenericIPAddressField(null=True, blank=True)
    # Velocidad negociada (ifHighSpeed) y tasa calculada entre dos sondeos.
    velocidad_mbps = models.IntegerField(null=True, blank=True)
    bps_entrada = models.BigIntegerField(null=True, blank=True)
    bps_salida = models.BigIntegerField(null=True, blank=True)
    uso_pct = models.FloatField(null=True, blank=True)
    # Último cambio up/down (ifLastChange o transición observada) y última vez con enlace.
    ultimo_cambio = models.DateTimeField(null=True, blank=True)
    ultimo_activo = models.DateTimeField(null=True, blank=True)
    # PoE: deliveringPower, searching, fault, disabled…; consumo en milliwatts.
    poe_estado = models.CharField(max_length=20, null=True, blank=True)
    poe_mw = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Puerto"
        verbose_name_plural = "Puertos"
        ordering = ['indice']
        unique_together = ['switch', 'indice']

    def __str__(self):
        return f"{self.switch.nombre} — {self.nombre} [{self.estado}]"


class EventoPuerto(models.Model):
    """Cambio de estado up/down observado; sirve para detectar puertos inestables."""
    puerto = models.ForeignKey(Puerto, on_delete=models.CASCADE, related_name='eventos')
    estado = models.CharField(max_length=20)
    momento = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = "Evento de puerto"
        verbose_name_plural = "Eventos de puerto"
        ordering = ['-momento']


class UmbralRol(models.Model):
    """Umbrales de salud por rol de switch; editables en el admin."""
    rol = models.CharField(max_length=20, choices=Switch.ROLES, unique=True)
    cpu_atencion = models.PositiveSmallIntegerField(default=70)
    cpu_riesgo = models.PositiveSmallIntegerField(default=90)
    memoria_atencion = models.PositiveSmallIntegerField(default=80)
    memoria_riesgo = models.PositiveSmallIntegerField(default=90)
    # Condición compuesta: tantos puertos con errores (o inestables) a la vez
    # indican una falla del equipo o de su enlace, no de un cable suelto.
    puertos_riesgo = models.PositiveSmallIntegerField(
        default=3, help_text='Puertos con errores o inestables a la vez que ponen el switch en riesgo (0 = desactivado)')
    escalar_minutos = models.PositiveSmallIntegerField(
        default=30, help_text='Minutos en riesgo sin reconocer antes de escalar la alerta (0 = no escalar)')

    class Meta:
        verbose_name = "Umbral por rol"
        verbose_name_plural = "Umbrales por rol"

    def __str__(self):
        return f"Umbrales {self.get_rol_display()}"


class UmbralOptico(models.Model):
    """Rangos aceptables de los transceptores SFP (fila única, editable en el admin).

    Los valores por defecto cubren ópticas 1G/10G comunes (SX/LX/LR); ajústalos
    a la hoja de datos de tus módulos.
    """
    rx_atencion = models.FloatField(default=-17.0, help_text='RX (dBm) por debajo: atención')
    rx_riesgo = models.FloatField(default=-20.0, help_text='RX (dBm) por debajo: en riesgo')
    rx_saturacion = models.FloatField(default=0.0, help_text='RX (dBm) por encima: receptor saturado')
    tx_minimo = models.FloatField(default=-9.5, help_text='TX (dBm) por debajo: láser débil')
    temp_atencion = models.FloatField(default=65.0, help_text='Temperatura (°C) para atención')
    temp_riesgo = models.FloatField(default=75.0, help_text='Temperatura (°C) en riesgo')
    caida_rx = models.FloatField(default=3.0, help_text='dB de caída de RX en 24 h que se consideran degradación')

    class Meta:
        verbose_name = "Umbral óptico"
        verbose_name_plural = "Umbrales ópticos"

    def __str__(self):
        return "Umbrales de ópticas SFP"

    @classmethod
    def actual(cls):
        return cls.objects.first() or cls()


class Mantenimiento(models.Model):
    """Ventana de mantenimiento: las alertas del switch o del plantel se registran pero no se notifican."""
    switch = models.ForeignKey(Switch, null=True, blank=True, on_delete=models.CASCADE, related_name='mantenimientos')
    plantel = models.ForeignKey(Plantel, null=True, blank=True, on_delete=models.CASCADE, related_name='mantenimientos')
    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    motivo = models.CharField(max_length=255)
    creado_por = models.ForeignKey('usuarios.Usuario', null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='mantenimientos')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ventana de mantenimiento"
        verbose_name_plural = "Ventanas de mantenimiento"
        ordering = ['-inicio']

    def __str__(self):
        return f"{self.switch or self.plantel}: {self.motivo}"

    @classmethod
    def activas(cls, now):
        return cls.objects.filter(inicio__lte=now, fin__gt=now)

    @classmethod
    def por_switch(cls, switches, now):
        """{switch_id: ventana activa} considerando ventanas por switch y por plantel."""
        windows = list(cls.activas(now).filter(
            models.Q(switch__in=[s.pk for s in switches]) | models.Q(plantel__in={s.plantel_id for s in switches})))
        result = {}
        for switch in switches:
            match = [w for w in windows if w.switch_id == switch.pk or w.plantel_id == switch.plantel_id]
            if match:
                result[switch.pk] = max(match, key=lambda window: window.fin)
        return result


class Alerta(models.Model):
    """Episodio en riesgo (rojo) de un switch: se abre al entrar y se cierra al recuperarse."""
    switch = models.ForeignKey(Switch, on_delete=models.CASCADE, related_name='alertas')
    nivel = models.CharField(max_length=10, default='critical')
    motivos = models.JSONField(default=list, blank=True)
    inicio = models.DateTimeField(db_index=True)
    fin = models.DateTimeField(null=True, blank=True)
    notificada = models.BooleanField(default=False)
    en_mantenimiento = models.BooleanField(default=False)
    reconocida_por = models.ForeignKey('usuarios.Usuario', null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name='alertas_reconocidas')
    reconocida_en = models.DateTimeField(null=True, blank=True)
    nota = models.TextField(blank=True, default='')
    # Aviso adicional cuando sigue abierta y sin reconocer más de UmbralRol.escalar_minutos.
    escalada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Alerta"
        verbose_name_plural = "Alertas"
        ordering = ['-inicio']

    def __str__(self):
        return f"{self.switch.nombre} · {self.inicio:%Y-%m-%d %H:%M}"


class Descubierto(models.Model):
    """Equipo visto por CDP o por barrido SNMP que no está en el inventario."""
    ORIGENES = [('cdp', 'Vecino CDP'), ('barrido', 'Barrido SNMP')]
    ESTADOS = [('pendiente', 'Pendiente'), ('ignorado', 'Ignorado'), ('agregado', 'Agregado')]
    ip = models.GenericIPAddressField(unique=True)
    nombre = models.CharField(max_length=255, blank=True, default='')
    descripcion = models.TextField(blank=True, default='')
    plataforma = models.CharField(max_length=255, blank=True, default='')
    origen = models.CharField(max_length=10, choices=ORIGENES)
    visto_desde = models.CharField(max_length=255, blank=True, default='')
    estado = models.CharField(max_length=10, choices=ESTADOS, default='pendiente')
    primera_vez = models.DateTimeField()
    ultima_vez = models.DateTimeField()

    class Meta:
        verbose_name = "Equipo descubierto"
        verbose_name_plural = "Equipos descubiertos"
        ordering = ['-ultima_vez']

    def __str__(self):
        return f"{self.nombre or self.ip} ({self.get_origen_display()})"


class Respaldo(models.Model):
    """Versión de la configuración de un switch (sólo se guarda cuando cambia)."""
    switch = models.ForeignKey(Switch, on_delete=models.CASCADE, related_name='respaldos')
    momento = models.DateTimeField(db_index=True)
    # Última vez que se comprobó que la configuración seguía igual.
    verificado = models.DateTimeField(null=True, blank=True)
    exito = models.BooleanField(default=True)
    error = models.TextField(blank=True, default='')
    contenido = models.TextField(blank=True, default='')
    hash = models.CharField(max_length=64, blank=True, default='')
    lineas_agregadas = models.IntegerField(default=0)
    lineas_eliminadas = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Respaldo de configuración"
        verbose_name_plural = "Respaldos de configuración"
        ordering = ['-momento']

    def __str__(self):
        return f"{self.switch.nombre} · {self.momento:%Y-%m-%d %H:%M}"

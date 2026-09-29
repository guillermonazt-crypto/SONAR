from rest_framework import serializers
from planteles.models import Division, Plantel
from switches.health import assess, reason_type
from switches.models import Alerta, Descubierto, Mantenimiento, Respaldo, Switch, Puerto
from usuarios.models import Bitacora

class DivisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Division
        fields = ['id', 'nombre']

class PlantelSerializer(serializers.ModelSerializer):
    division_nombre = serializers.CharField(source='division.nombre', read_only=True)
    class Meta:
        model = Plantel
        fields = ['id', 'nombre', 'division', 'division_nombre', 'ubicacion', 'activo']

class SwitchSerializer(serializers.ModelSerializer):
    plantel_nombre = serializers.CharField(source='plantel.nombre', read_only=True)
    # Nivel verde/amarillo/rojo y motivos (switches/health.py), sólo si la vista
    # entrega el contexto 'health'; así Monitoreo y Resumen usan las mismas reglas.
    estado = serializers.SerializerMethodField()
    motivos = serializers.SerializerMethodField()
    mantenimiento = serializers.SerializerMethodField()

    def get_mantenimiento(self, switch):
        window = (self.context.get('health') or {}).get('maintenance', {}).get(switch.pk)
        return window and dict(id=window.pk, hasta=window.fin.isoformat(), motivo=window.motivo)

    def _health(self, switch):
        health = self.context.get('health')
        if health is None:
            return None
        if not hasattr(switch, '_health'):
            switch._health = assess(switch, health['stats'].get(switch.pk, {}),
                                    health['thresholds'][switch.rol], health['now'])
        return switch._health

    def get_estado(self, switch):
        health = self._health(switch)
        return health and health[0]

    def get_motivos(self, switch):
        health = self._health(switch)
        return health and health[1]

    class Meta:
        model = Switch
        fields = ['id', 'nombre', 'hostname', 'modelo', 'firmware', 'rol', 'plantel', 'plantel_nombre', 'activo',
                  'ultima_consulta', 'lectura_correcta', 'cpu_5s', 'cpu_1m', 'cpu_5m',
                  'memoria_usada_pct', 'memoria_total_bytes', 'memoria_usada_bytes',
                  'uptime_segundos', 'ultimo_reinicio', 'temperatura_c', 'hardware',
                  'poe_presupuesto_w', 'poe_consumo_w', 'estado', 'motivos', 'mantenimiento']
        read_only_fields = ['ultima_consulta', 'lectura_correcta', 'cpu_5s', 'cpu_1m', 'cpu_5m',
                            'memoria_usada_pct', 'memoria_total_bytes', 'memoria_usada_bytes',
                            'uptime_segundos', 'ultimo_reinicio', 'modelo', 'firmware',
                            'temperatura_c', 'hardware', 'poe_presupuesto_w', 'poe_consumo_w']

class PuertoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Puerto
        fields = ['id', 'switch', 'nombre', 'descripcion', 'indice', 'estado', 'estado_operativo',
                  'ip_equipo', 'mac_equipo', 'mac_telefono', 'dhcp',
                  'vlan', 'voice_vlan', 'es_trunk', 'errores_entrada', 'errores_salida',
                  'errores_crc', 'errores_nuevos', 'ultimo_error', 'octetos_entrada', 'octetos_salida',
                  'actualizado', 'vecino_nombre', 'vecino_puerto', 'vecino_plataforma', 'vecino_ip', 'vecino_tipo',
                  'velocidad_mbps', 'bps_entrada', 'bps_salida', 'uso_pct', 'ultimo_cambio', 'ultimo_activo',
                  'poe_estado', 'poe_mw']


def switch_brief(switch):
    return dict(id=switch.pk, nombre=switch.nombre, hostname=switch.hostname,
                plantel=switch.plantel_id, plantel_nombre=switch.plantel.nombre)


class AlertaSerializer(serializers.ModelSerializer):
    switch = serializers.SerializerMethodField()
    motivos = serializers.SerializerMethodField()
    reconocida_por = serializers.CharField(source='reconocida_por.username', read_only=True, default=None)

    def get_switch(self, alert):
        return switch_brief(alert.switch)

    def get_motivos(self, alert):
        return [dict(reason, tipo=reason_type(reason)) for reason in alert.motivos or []]

    class Meta:
        model = Alerta
        fields = ['id', 'switch', 'nivel', 'motivos', 'inicio', 'fin', 'notificada', 'en_mantenimiento',
                  'reconocida_por', 'reconocida_en', 'nota', 'escalada_en']
        read_only_fields = fields


class MantenimientoSerializer(serializers.ModelSerializer):
    switch_nombre = serializers.CharField(source='switch.nombre', read_only=True, default=None)
    plantel_nombre = serializers.CharField(source='plantel.nombre', read_only=True, default=None)
    creado_por = serializers.CharField(source='creado_por.username', read_only=True, default=None)

    def validate(self, data):
        switch = data.get('switch', getattr(self.instance, 'switch', None))
        plantel = data.get('plantel', getattr(self.instance, 'plantel', None))
        if bool(switch) == bool(plantel):
            raise serializers.ValidationError('Elige un switch o un plantel (sólo uno).')
        start = data.get('inicio', getattr(self.instance, 'inicio', None))
        end = data.get('fin', getattr(self.instance, 'fin', None))
        if start and end and end <= start:
            raise serializers.ValidationError('El fin debe ser posterior al inicio.')
        return data

    class Meta:
        model = Mantenimiento
        fields = ['id', 'switch', 'switch_nombre', 'plantel', 'plantel_nombre', 'inicio', 'fin', 'motivo',
                  'creado_por', 'creado']
        read_only_fields = ['creado_por', 'creado']


class BitacoraSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bitacora
        fields = ['id', 'usuario_nombre', 'accion', 'objeto', 'objeto_id', 'descripcion', 'cambios', 'ip', 'momento']
        read_only_fields = fields


class DescubiertoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Descubierto
        fields = ['id', 'ip', 'nombre', 'descripcion', 'plataforma', 'origen', 'visto_desde', 'estado',
                  'primera_vez', 'ultima_vez']
        read_only_fields = fields


class RespaldoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Respaldo
        fields = ['id', 'switch', 'momento', 'verificado', 'exito', 'error', 'hash',
                  'lineas_agregadas', 'lineas_eliminadas']
        read_only_fields = fields

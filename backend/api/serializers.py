from rest_framework import serializers
from planteles.models import Division, Plantel
from switches.models import Switch, Puerto

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
    class Meta:
        model = Switch
        fields = ['id', 'nombre', 'hostname', 'modelo', 'firmware', 'rol', 'plantel', 'plantel_nombre', 'activo',
                  'ultima_consulta', 'lectura_correcta', 'cpu_5s', 'cpu_1m', 'cpu_5m']
        read_only_fields = ['ultima_consulta', 'lectura_correcta', 'cpu_5s', 'cpu_1m', 'cpu_5m', 'modelo', 'firmware']

class PuertoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Puerto
        fields = ['id', 'switch', 'nombre', 'descripcion', 'indice', 'estado', 'estado_operativo',
                  'ip_equipo', 'mac_equipo', 'mac_telefono', 'dhcp',
                  'vlan', 'voice_vlan', 'es_trunk', 'errores_entrada', 'errores_salida',
                  'errores_crc', 'octetos_entrada', 'octetos_salida',
                  'actualizado']

# test_escritura.py
# Prueba de escritura completa en InfluxDB usando datos simulados.
# Autor: Guillermo Nazt

from snmp_simulator import obtener_datos_switch
from sonar.database.influx_writer import InfluxWriter

print("\n" + "="*55)
print("  SONAR - Prueba de escritura en InfluxDB")
print("="*55 + "\n")

# Obtener datos simulados del switch
datos = obtener_datos_switch()
print(f"Datos obtenidos de: {datos['nombre']}\n")

# Escribir en InfluxDB
writer = InfluxWriter()

writer.escribir_cpu(datos)
writer.escribir_interfaces(datos)
writer.escribir_optica(datos)

writer.cerrar()

print("\n✅ Datos escritos correctamente en InfluxDB")
print("Abre http://localhost:8086 para verificarlos\n")
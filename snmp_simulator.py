# snmp_simulator.py
# Simulador de respuestas SNMP para desarrollo de SONAR.
# Imita exactamente lo que responderia un switch Cisco Catalyst real.
# Autor: Guillermo Nazt

# ---------------------------------------------------------------------------
# Por que este enfoque?
# pysnmp aun no es compatible con Python 3.14.
# En lugar de bloquear el desarrollo, simulamos los datos directamente.
# Cuando tengamos acceso a switches reales, este archivo se reemplaza
# por consultas SNMP reales. La estructura del resto de SONAR no cambia.
# ---------------------------------------------------------------------------

# Datos que responderia un switch Cisco Catalyst via SNMP
SWITCH_SIMULADO = {
    "nombre":       "SW-CORE-01",
    "descripcion":  "Cisco IOS Software, Catalyst L3 Switch",
    "ip":           "192.168.1.1",
    "rol":          "core",
    "sitio":        "campus_central",

    # CPU (porcentaje)
    "cpu_5s":  45,
    "cpu_1m":  31,
    "cpu_5m":  23,

    # Interfaces
    "interfaces": [
        {
            "nombre":         "GigabitEthernet1/0/1",
            "estado":         "up",
            "errores_entrada": 5,
            "errores_crc":    2,
            "errores_salida": 0,
        },
        {
            "nombre":         "GigabitEthernet1/0/2",
            "estado":         "down",
            "errores_entrada": 0,
            "errores_crc":    0,
            "errores_salida": 0,
        },
        {
            "nombre":         "GigabitEthernet1/0/3",
            "estado":         "up",
            "errores_entrada": 127,
            "errores_crc":    43,
            "errores_salida": 0,
        },
    ],

    # Optica (dBm)
    # Rango normal: entre -3 y -20 dBm
    # Menos de -25 dBm indica problema serio
    "transceptores": [
        {
            "interfaz":  "GigabitEthernet1/0/1",
            "rx_dbm":    -4.2,   # Normal
            "tx_dbm":    -2.1,   # Normal
            "temp_c":    35.2,
            "estado":    "ok",
        },
        {
            "interfaz":  "GigabitEthernet1/0/2",
            "rx_dbm":    -22.7,  # Degradacion moderada
            "tx_dbm":    -2.3,
            "temp_c":    36.1,
            "estado":    "degradado",
        },
        {
            "interfaz":  "GigabitEthernet1/0/3",
            "rx_dbm":    -29.8,  # Critico, casi sin luz
            "tx_dbm":    -2.0,
            "temp_c":    37.4,
            "estado":    "critico",
        },
    ],
}


def obtener_datos_switch(nombre: str = "SW-CORE-01") -> dict:
    """
    Simula la consulta SNMP completa a un switch.

    Args:
        nombre: Nombre del switch a consultar

    Returns:
        Diccionario con todos los datos del switch,
        exactamente como los retornara el modulo SNMP real.
    """
    return SWITCH_SIMULADO


def mostrar_reporte(datos: dict) -> None:
    """
    Muestra un reporte legible de los datos del switch.
    """
    print("\n" + "=" * 55)
    print(f"  SONAR - Reporte: {datos['nombre']}")
    print(f"  IP: {datos['ip']} | Rol: {datos['rol']}")
    print("=" * 55)

    # CPU
    print("\n  [CPU]")
    print(f"    5 segundos : {datos['cpu_5s']}%")
    print(f"    1 minuto   : {datos['cpu_1m']}%")
    print(f"    5 minutos  : {datos['cpu_5m']}%")

    # Interfaces
    print("\n  [Interfaces]")
    for intf in datos["interfaces"]:
        errores = intf["errores_entrada"] + intf["errores_crc"]
        alerta = "   ERRORES DETECTADOS" if errores > 0 else ""
        print(f"    {intf['nombre']:<28} {intf['estado']:<6}{alerta}")

    # Optica
    print("\n  [Optica - Potencia Rx]")
    for tx in datos["transceptores"]:
        atenuacion = abs(tx["tx_dbm"] - tx["rx_dbm"])
        print(f"    {tx['interfaz']:<28} "
              f"Rx: {tx['rx_dbm']:>6.1f} dBm  "
              f"Atenuacion: {atenuacion:.1f} dB  "
              f"[{tx['estado'].upper()}]")

    print("=" * 55 + "\n")


# Punto de entrada
if __name__ == "__main__":
    datos = obtener_datos_switch()
    mostrar_reporte(datos)
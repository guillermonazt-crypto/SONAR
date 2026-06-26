# ⬡ S.O.N.A.R.
### Sistema de Observabilidad de Nodos y Análisis de Red

[![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python)](https://python.org)
[![InfluxDB](https://img.shields.io/badge/InfluxDB-2.7-purple?logo=influxdb)](https://influxdata.com)
[![Grafana](https://img.shields.io/badge/Grafana-10.4-orange?logo=grafana)](https://grafana.com)
[![Flask](https://img.shields.io/badge/Flask-3.0-black?logo=flask)](https://flask.palletsprojects.com)

---

## ¿Qué es SONAR?

SONAR es un sistema de observabilidad de red diseñado como complemento
a SolarWinds Orion para redes universitarias Cisco Catalyst.

Mientras Orion ofrece visibilidad macro, SONAR cubre los puntos ciegos:

- **Atenuación de fibra óptica** — Potencia Rx/Tx en dBm por transceptor
- **Errores físicos de interfaz** — CRC, input errors en tiempo real
- **Consumo del switch** — CPU cada 60 segundos con historial

> "Orion te dice que algo se cayó. SONAR te avisa antes de que se caiga."

---

## Stack Tecnológico

| Componente    | Tecnología      |           Rol             |
|---------------|-----------------|---------------------------|
| Recolección   | Python + SNMP   | Consulta switches via OIDs|
| Base de datos | InfluxDB 2.7    | Almacena series de tiempo |
| Visualización | Grafana 10.4    | Dashboards y alertas      |
| Interfaz web  | Flask           | Gestión de inventario     |
| Despliegue    | Docker Compose  | Orquestación de servicios |

---

## Arquitectura
Switches Cisco Catalyst

(SNMP v2c/v3)

↓

Python Worker

(polling cada 60s)

↓

InfluxDB 2.7

(series de tiempo)

↓

Grafana Dashboards

(visualización)

↑

Flask Web UI

(gestión de inventario)

---

## Métricas Monitoreadas

### CPU
- Uso promedio 5 segundos, 1 minuto y 5 minutos

### Interfaces
- Estado operacional (up/down)
- Errores de entrada y salida
- Errores CRC
- Tasa de error calculada automáticamente

### Óptica
- Potencia Rx en dBm por transceptor
- Potencia Tx en dBm por transceptor
- Temperatura del transceptor
- **Atenuación calculada automáticamente** (Tx - Rx)
- Estado: OK / Degradado / Crítico

---

## Instalación

### Requisitos
- Python 3.10+
- Docker Desktop
- Git

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/guillermonazt-crypto/SONAR.git
cd SONAR

# 2. Crear entorno virtual
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows
source .venv/bin/activate    # Linux/Mac

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales

# 5. Levantar base de datos y Grafana
docker compose up -d

# 6. Iniciar SONAR
python sonar/main.py
```

### Acceso a los servicios

| Servicio |            URL         |           Credenciales            |
|----------|------------------------|-----------------------------------|
| SONAR Web| http://localhost:5000  | —                                 |
| Grafana  | http://localhost:3000  | admin / sonar_grafana_2024        |
| InfluxDB | http://localhost:8086  | sonar_admin / sonar_password_2024 |

---

## Estructura del Proyecto
SONAR/

├── sonar/

│   ├── collector/      # Recolección SNMP

│   ├── parsers/        # Procesamiento de datos

│   ├── database/       # Escritura en InfluxDB

│   ├── utils/          # Logger y configuración

│   └── web/            # Interfaz Flask

├── inventory/

│   └── devices.yaml    # Inventario de switches

├── data/

│   └── samples/        # Datos de prueba

├── tests/              # Pruebas unitarias

├── docker-compose.yml

├── requirements.txt

└── .env.example

---

## Roadmap

- [x] Fase 0 — Estructura del proyecto y Git
- [x] Fase 1 — Logger y configuración
- [x] Fase 2 — Simulador de datos SNMP
- [x] Fase 3 — Escritura en InfluxDB
- [x] Fase 4 — Dashboards en Grafana
- [x] Fase 5 — Loop automático de monitoreo
- [x] Fase 6 — Interfaz web de onboarding
- [ ] Fase 7 — Conexión con switches reales UAEH
- [ ] Fase 8 — Integración Zabbix
- [ ] Fase 9 — Sistema de alertas

---

## Autor

**Guillermo Nazt**
Departamento de Telecomunicaciones — UAEH
[github.com/guillermonazt-crypto](https://github.com/guillermonazt-crypto)

---

## Licencia

MIT License — Ver archivo LICENSE para detalles.
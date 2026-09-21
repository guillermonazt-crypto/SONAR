# SONAR

Sistema de Observabilidad de Nodos y Análisis de Red.
Recolecta métricas SNMP y las almacena en InfluxDB para visualizarlas con Grafana.

## Dónde está cada cosa

```text
SONAR/
├── sonar/                  Monitoreo y aplicación Flask
│   ├── main.py             Worker: recarga, consulta y escritura
│   ├── collector/          Consultas SNMP
│   ├── database/           Escritura en InfluxDB
│   ├── utils/              Configuración y registro de eventos
│   └── web/                Interfaz Flask y plantillas
├── backend/                Backend Django
│   ├── manage.py           Comandos Django
│   ├── config/             Settings, rutas, ASGI y WSGI
│   ├── planteles/          Divisiones y planteles
│   ├── switches/           Switches y puertos
│   ├── usuarios/           Usuarios y roles
│   └── db.sqlite3          Base local, excluida de Git
├── tests/                  Pruebas automáticas del worker
├── scripts/                Utilidades de ejecución manual
│   ├── snmp_simulator.py   Datos simulados, sin red
│   ├── check_snmp.py       Consulta SNMP manual, usa red
│   └── local/              Experimentos privados, excluidos de Git
├── inventory/              Inventario YAML privado
├── data/                   Datos locales, excluidos de Git
├── grafana/                Configuración de Grafana
├── docs/                   Documentación adicional
├── requirements.txt        Dependencias Python
├── .env.example            Ejemplo de configuración
└── .env                    Credenciales locales, excluidas de Git
```

Las pruebas de los modelos Django permanecen dentro de cada aplicación Django.
Las carpetas `migrations/` contienen el historial del esquema de la base;
`__pycache__/` y `.venv/` son generadas por Python.

## Instalación y ejecución

Requiere Python 3.12+, Git y Docker para InfluxDB/Grafana.
Ejecuta los comandos desde la raíz del proyecto con el entorno virtual activado:

```powershell
python -m pip install -r requirements.txt
# Solo si aún no tienes .env:
Copy-Item .env.example .env
```

Configura SECRET_KEY en `.env` o en el entorno; no hay clave predeterminada.
Genera una clave con `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
Conserva las credenciales existentes al editar `.env`.

| Acción | Comando desde la raíz |
|---|---|
| InfluxDB y Grafana (compose local) | `docker compose up -d` |
| Worker SNMP (consulta dispositivos) | `python -m sonar.main` |
| Interfaz Flask | `python -m sonar.web.app` |
| Administración Django | `python backend/manage.py runserver` |
| Aplicar migraciones Django | `python backend/manage.py migrate` |
| Reporte simulado sin red | `python -m scripts.snmp_simulator` |

Flask usa el puerto 5000, Django el 8000, Grafana el 3000 e InfluxDB el 8086.
Flask administra el inventario YAML; Django administra su propio inventario.

## Inventario, datos y permisos

INVENTORY_SOURCE=yaml lee `inventory/devices.yaml`.
INVENTORY_SOURCE=django lee por ORM los switches activos de planteles activos
en la base local Django. Cada ciclo vuelve a leer la fuente; si falla, omite
ese ciclo y reintenta. No se sincronizan automáticamente YAML y Django.

El worker requiere acceso local a la base y SECRET_KEY para usar Django;
no utiliza HTTP ni sesión de usuario, y no actualiza Puerto. Su cuenta necesita
acceso de lectura a la base y su directorio, sin ser superusuario Django.
El campo rol es descriptivo: el administrador usa is_staff y permisos/grupos
Django. Las API futuras deberán aplicar permisos explícitos.

Las lecturas SNMP ausentes se representan como None y se omiten como campos
numéricos en InfluxDB; cero es una lectura válida. Las interfaces conservan
su estado incluso sin contadores. Escrituras y cierre se ejecutan en hilos
para permitir que avance el bucle asíncrono.

## Validación sin dispositivos reales

```powershell
python -m unittest discover -s tests
$env:PYTHONPATH = (Get-Location).Path
python backend/manage.py test switches.test_worker --noinput
python backend/manage.py check
```

Las pruebas usan mocks y una base Django temporal. Configura SECRET_KEY antes
de ejecutarlas. `scripts/check_snmp.py` y los experimentos de `scripts/local/`
son manuales y pueden conectarse a dispositivos o servicios reales.
Para los experimentos usa `python -m scripts.local.NOMBRE_SIN_EXTENSION`.

## Cambios de ubicación

- `backend/backend/` pasó a `backend/config/`: el módulo de configuración ahora
  es `config.settings`, y los entrypoints son `config.wsgi` y `config.asgi`.
  Actualiza DJANGO_SETTINGS_MODULE si lo habías definido externamente.
- `snmp_simulator.py` pasó a `scripts/snmp_simulator.py`.
- `tests/test_snmp.py` pasó a `scripts/check_snmp.py` porque es una consulta manual.
- Los tres experimentos de la raíz pasaron a `scripts/local/`.
- Los esqueletos duplicados de `sonar/` están respaldados en
  `.local-backup/structure-20260921/`, fuera del seguimiento Git.

## Autor y licencia

Guillermo Nazt — Departamento de Telecomunicaciones, UAEH.
Licencia MIT; consulta LICENSE.

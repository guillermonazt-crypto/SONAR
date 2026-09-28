# SONAR

Observabilidad de red con **React + Django + SNMP + InfluxDB**.
La interfaz conserva el diseño oscuro y cian de SONAR; Flask está retirado.

## Dónde está cada cosa

```text
frontend/             Interfaz React con Vite
  src/components/     Login, inventario, planteles y puertos
  src/api/            Cliente HTTP, sesión y CSRF
backend/              Django
  api/                Rutas, serializers, permisos y pruebas HTTP
  config/             Configuración, ASGI y WSGI
  switches/           Modelos y servicio de persistencia del worker
  planteles/          Divisiones y planteles
  usuarios/           Usuarios y roles
  manage.py           Comandos Django
sonar/                Worker SNMP
  collector/          Consultas SNMP
  database/           Adaptadores InfluxDB y Django
  utils/              Configuración y logs
  main.py             Ciclo de monitoreo
scripts/              Simulador y utilidades manuales
tests/               Pruebas offline del worker
docs/                Arquitectura y contrato de API
inventory/            Inventario YAML opcional y privado
data/                Datos locales
grafana/             Configuración Grafana
```

## Iniciar en desarrollo

Requiere Python 3.12+ y Node 20.19+ o 22.12+ (se validó con Node 24).
Activa `.venv` y ejecuta desde la raíz:

```powershell
python -m pip install -r requirements.txt
# Solo para una instalación nueva: copia .env.example a .env.
# Define SECRET_KEY sin sobrescribir las demás credenciales.
python backend/manage.py migrate
# Solo si necesitas crear una cuenta administradora:
python backend/manage.py createsuperuser
python backend/manage.py runserver 127.0.0.1:8000
```

En otra terminal:

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Abre http://127.0.0.1:5173 e inicia sesión con una cuenta Django existente.
Se incluye pnpm-lock.yaml para instalaciones reproducibles. Si pnpm no está en PATH,
usa la ruta de tu instalación de pnpm. El administrador Django permanece en
http://127.0.0.1:8000/admin/ para usuarios y permisos.

Para abrirlo desde otro equipo conectado a la misma red, inicia Vite y Django
escuchando en `0.0.0.0` y abre `http://10.128.3.139:5173`. La API de Django
queda en el puerto 8000 y Grafana en el 3000. Esta dirección depende de la IP
Ethernet actual de la máquina; si cambia, actualiza `frontend/.env.local` y
`DJANGO_ALLOWED_HOSTS`/`DJANGO_CSRF_ORIGINS`.

INVENTORY_SOURCE=django conecta el worker al mismo inventario que React.
Para iniciar sondeos reales, cuando estés listo: `python -m sonar.main`.
No es necesario iniciar el worker para usar o probar la interfaz.
Configura frontend/.env.local con VITE_GRAFANA_URL para habilitar el enlace a Grafana.
Las variables VITE_* son públicas: nunca pongas secretos en ellas.

## Pruebas sin switches reales

```powershell
python -m unittest discover -s tests
$env:PYTHONPATH = (Get-Location).Path
python backend/manage.py test api switches --noinput
python backend/manage.py check
python backend/manage.py makemigrations --check --dry-run
cd frontend
pnpm test
pnpm build
```

Las pruebas usan mocks y bases temporales. Los scripts en scripts/local/ y
scripts/check_snmp.py son manuales y pueden acceder a equipos o servicios reales.

El panel frontal de puertos muestra la topología observada por `ifIndex`. Al
seleccionar un puerto se ven IP/MAC aprendidas, VLAN, voice VLAN, MAC de teléfono
y el estado de DHCP snooping. IP y MAC se correlacionan con ARP/FDB; los teléfonos
se identifican mediante CDP. Un valor vacío significa que el switch no lo publicó,
no que se haya convertido en cero.

## Datos locales y estructura

`.env`, `backend/db.sqlite3`, `.local-backup/`, scripts/local/, node_modules/ y
frontend/dist/ están excluidos de Git. Los cambios de esquema se guardan en migraciones.
La base anterior a React está respaldada en `.local-backup/before-react-django.sqlite3`.
El módulo de settings Django es `config.settings`.

Consulta [arquitectura, permisos y contrato HTTP](docs/architecture.md).
Sesiones y CSRF siguen la [documentación de DRF](https://www.django-rest-framework.org/api-guide/authentication/).
El frontend utiliza [Vite](https://vite.dev/guide/).

Guillermo Nazt — Departamento de Telecomunicaciones, UAEH. Licencia MIT.

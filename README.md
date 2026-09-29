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
grafana/             Configuración histórica opcional
```

## Iniciar en desarrollo

Requiere Python 3.12+ y Node 20.19+ o 22.12+ (se validó con Node 24).
Activa `.venv` y ejecuta desde la raíz:

```powershell
python -m pip install -r requirements.txt
# Solo para una instalación nueva: copia .env.example a .env.
# Define SECRET_KEY sin sobrescribir las demás credenciales.
# En desarrollo local deja DJANGO_DEBUG=true (el valor por defecto ahora es false).
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
queda en el puerto 8000. Esta dirección depende de la IP Ethernet actual de la
máquina; si cambia, actualiza `frontend/.env.local` y
`DJANGO_ALLOWED_HOSTS`/`DJANGO_CSRF_ORIGINS`.

INVENTORY_SOURCE=django conecta el worker al mismo inventario que React.
Para iniciar sondeos reales, cuando estés listo: `python -m sonar.main`.
El worker exige credenciales SNMP explícitas: `SNMP_COMMUNITY` (v2c) o
`SNMP_VERSION=3` con `SNMP_V3_USER`, `SNMP_V3_AUTH_KEY` y `SNMP_V3_PRIV_KEY`
(recomendado). Ya no existe la comunidad `public` por defecto.
No es necesario iniciar el worker para usar o probar la interfaz.
Las variables `VITE_*` son públicas: nunca pongas secretos en ellas.

## Monitoreo

La pestaña **Monitoreo** agrupa los switches por plantel en carpetas expandibles.
El panel físico reconoce interfaces de Catalyst antiguos y actuales, además de
formatos comunes de otros fabricantes. La clasificación física usa `IF-MIB.ifType`
y descarta interfaces lógicas como VLAN, Loopback, Stack y Port-channel.

Al seleccionar un puerto se muestran descripción, estado, errores, IP/MAC, VLAN,
Voice VLAN, MAC del teléfono y tráfico de entrada/salida. La velocidad se calcula
entre dos lecturas consecutivas del worker y no se guarda como historial en Django.

Las vistas se refrescan solas: el selector del encabezado permite cada 3 s (por
defecto), 5 s, 30 s o desactivarlo. El refresco se pausa con la pestaña oculta y
el switch, puerto, pestaña y carpetas abiertas se conservan al recargar la página.

Los datos de voz, CDP, VLAN y DHCP snooping se muestran sólo cuando el equipo los
publica. Los OID específicos de un fabricante son enriquecimientos opcionales;
estado, alias, errores y tráfico se obtienen con MIBs estándar.

## Resumen, umbrales y alertas

La pestaña **Resumen** usa un solo endpoint (`/api/resumen/`, caché de 60 s) con el
estado verde/amarillo/rojo de cada switch, sus motivos, conteos de puertos físicos
y el histórico de 24 h (CPU, memoria y tráfico total) agrupado por plantel.
Las reglas viven en `backend/switches/health.py`; los umbrales de CPU y memoria se
editan por rol (core, distribución, acceso) en el admin Django, en **Umbrales por rol**.

El tablero **Estado por plantel** (arriba del Resumen) muestra cada plantel activo con
el peor estado de sus equipos (mismas reglas de `health.py`), cuántos responden a SNMP,
puertos activos, alertas abiertas y puertos con errores. Al elegir un plantel se filtra
el análisis por equipo. Los planteles sin equipos aparecen como "Sin equipos".

En Resumen y en Alertas los filtros se combinan (plantel, estado de salud y tipo de
problema: SNMP, CPU, memoria, errores, inestables, saturación, hardware, PoE…) y se
recuerdan al recargar, igual que la pestaña y el switch abiertos. El API acepta
`/api/alertas/?plantel=<id>&tipo=<tipo>&estado=abiertas|cerradas&sin_reconocer=1`.

Los errores de puerto se evalúan por ciclo (`errores_nuevos`, `ultimo_error`), no
por el contador acumulado desde el arranque del equipo.

El worker envía una alerta cuando un switch pasa a rojo y otra cuando se recupera,
con un cooldown (`ALERT_COOLDOWN_MINUTES`). Canales opcionales en `.env`: correo
(`ALERT_EMAIL_TO` + `EMAIL_*`), Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)
y webhook de Teams/Slack/Google Chat (`ALERT_WEBHOOK_URL`).

**Alertas inteligentes.** Condición compuesta: si 3 o más puertos de un mismo switch
tienen errores nuevos (o están inestables) a la vez, el switch pasa a rojo aunque cada
puerto por separado sólo sería "atención"; el número se ajusta por rol (`puertos_riesgo`,
0 lo desactiva). Escalamiento por rol: una alerta que sigue abierta y sin reconocer más
de `escalar_minutos` (core 15, distribución 30, acceso 60 por defecto) se vuelve a
avisar una sola vez por todos los canales y, además, a `ALERT_ESCALATION_EMAIL_TO`.
Nunca hay dos alertas abiertas para el mismo switch: si aparecen duplicados se conserva
la más antigua.

La salud también considera el hardware (fuentes, ventiladores y temperatura por
CISCO-ENVMON-MIB), el PoE al 90 % o más del presupuesto, los puertos inestables
(4 o más cambios up/down en 1 h) y los puertos al 90 % o más de su capacidad.

## Buscador, ópticas y centro de alertas

- **Buscador global** (barra de pestañas): MAC en cualquier formato, IP completa o
  parcial, MAC del teléfono, descripción de puerto o switch. Abre el puerto encontrado.
- **Ópticas**: RX/TX, temperatura y degradación de cada SFP (`/api/opticas/`, lee
  InfluxDB con caché de 30 s). Umbrales en el admin, **Umbrales ópticos**.
- **Alertas**: cada episodio en rojo queda registrado; un editor lo reconoce con una
  nota. Las **ventanas de mantenimiento** (por switch o plantel) registran las alertas
  sin notificarlas.
- **Bitácora de cambios** (Inventario, sólo editores): altas, ediciones, bajas,
  reconocimientos, respaldos e inicios de sesión.
- **Reportes → Tendencias**: CPU y memoria (promedio y máximo), tráfico promedio y pico,
  reinicios, alertas y minutos en riesgo por switch en 7 o 30 días, con gráficas diarias
  de toda la red. Lee el bucket de largo plazo `<INFLUX_BUCKET>_15m` (o
  `INFLUX_TREND_BUCKET`) y, si no existe, el crudo. Si InfluxDB no responde, el reporte
  sale igual con las alertas guardadas en Django y lo avisa.
- **Reportes**: inventario, disponibilidad, puertos sin uso, inestables, saturados y
  con errores, PoE, hardware, ópticas y topología CDP. En pantalla, CSV o impresos.

El API responde `304 Not Modified` (ETag) cuando nada cambió, así el refresco cada
3 s casi no transfiere datos.

## Descubrimiento y respaldos (opcionales)

Ambos están apagados por defecto; las variables están en `.env.example`.

- `DISCOVERY_ENABLED=true` propone equipos fuera del inventario: vecinos CDP y, con
  `DISCOVERY_SUBNETS`, un barrido SNMP limitado por `DISCOVERY_MAX_HOSTS`. Aparecen en
  Inventario → **Equipos descubiertos**; nunca se agregan solos. A mano:
  `python backend/manage.py descubrir`.
- `BACKUP_ENABLED=true` respalda `show running-config` por SSH cada
  `BACKUP_INTERVAL_HOURS` (requiere `pip install paramiko` y `BACKUP_SSH_USER`).
  Sólo se guarda una versión cuando la configuración cambia; en Inventario →
  **Respaldos** se ven las diferencias. Las contraseñas se ocultan salvo para
  administradores. A mano: `python backend/manage.py respaldar_configs`.

## Producción con Docker

`docker compose up -d --build` levanta Nginx con HTTPS (puertos 80/443), Django con
gunicorn, el worker, PostgreSQL, InfluxDB y Grafana. InfluxDB y Grafana sólo
escuchan en `127.0.0.1` del servidor y Grafana ya no admite acceso anónimo.
Completa en `.env` al menos `SECRET_KEY`, `POSTGRES_PASSWORD`, `INFLUX_ADMIN_PASSWORD`,
`INFLUX_TOKEN`, `GRAFANA_ADMIN_PASSWORD`, `SONAR_HOSTNAME`, las credenciales SNMP,
y agrega el nombre del servidor a `DJANGO_ALLOWED_HOSTS` y `https://<nombre>` a
`DJANGO_CSRF_ORIGINS`. Sin certificados propios (`SONAR_CERTS_DIR` con `sonar.crt`
y `sonar.key`) se genera uno autofirmado. Crea el administrador con
`docker compose exec django python backend/manage.py createsuperuser`.

Si el volumen de InfluxDB ya existía, cambiar las variables no rota las
credenciales anteriores: cámbialas en la interfaz de InfluxDB.

### Retención de InfluxDB

`python scripts/setup_influx_downsampling.py` crea el bucket `<bucket>_15m`
(400 días) y una tarea que guarda promedios de 15 min. `--read-token` crea un
token de sólo lectura para Django (`INFLUX_READ_TOKEN`). `--raw-retention-days 14`
reduce la retención del bucket crudo y **borra** los datos más antiguos.

## Integración opcional con Zabbix

SONAR puede consultar los hosts publicados por Zabbix desde **Resumen**. Configura
estas variables en `.env` y reinicia Django:

```env
ZABBIX_URL=http://servidor-zabbix/zabbix
ZABBIX_TOKEN=
```

La integración es de sólo lectura. Zabbix puede encargarse de métricas, históricos
y alertas SNMP, mientras SONAR conserva la vista física y el inventario por plantel.

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

`.env`, `backend/db.sqlite3`, `.local-backup/`, scripts/local/, node_modules/,
frontend/dist/ e `inventory/devices.yaml` están excluidos de Git
(`inventory/devices.example.yaml` es la plantilla). Los cambios de esquema se guardan en migraciones.
La base anterior a React está respaldada en `.local-backup/before-react-django.sqlite3`.
El módulo de settings Django es `config.settings`.

Consulta [arquitectura, permisos y contrato HTTP](docs/architecture.md).
Sesiones y CSRF siguen la [documentación de DRF](https://www.django-rest-framework.org/api-guide/authentication/).
El frontend utiliza [Vite](https://vite.dev/guide/).

Guillermo Nazt — Departamento de Telecomunicaciones, UAEH. Licencia MIT.

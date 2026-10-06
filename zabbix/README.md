# Zabbix para SONAR

Zabbix 7.0 LTS en Docker para el análisis en tiempo real: problemas activos,
disponibilidad (ICMP y SNMP) y últimos valores de cada switch. SONAR los lee por
la API (`/api/vivo/`) y, si InfluxDB no responde, también toma de aquí el historial.

El stack es independiente del `docker-compose.yml` de SONAR (proyecto
`sonar-zabbix`, red propia); se puede levantar en el mismo equipo o en otro.

| Servicio | Imagen | Puerto en el equipo |
| --- | --- | --- |
| postgres | timescale/timescaledb:2.19.3-pg16 (PostgreSQL 16 + TimescaleDB) | (sólo red interna) |
| zabbix-server | zabbix/zabbix-server-pgsql:alpine-7.0-latest | `ZBX_SERVER_PORT` (10051/tcp) |
| zabbix-web | zabbix/zabbix-web-nginx-pgsql:alpine-7.0-latest | `ZBX_HTTP_PORT` (8090/tcp → 8080) |
| zabbix-agent | zabbix/zabbix-agent2:alpine-7.0-latest | (sólo red interna) |
| zabbix-snmptraps | zabbix/zabbix-snmptraps:alpine-7.0-latest (profile `traps`, sólo Linux) | `ZBX_TRAPS_PORT` (162/udp → 1162) |
| zabbix-proxy | zabbix/zabbix-proxy-sqlite3:alpine-7.0-latest (profile `proxy`) | (sólo red interna; se conecta al 10051) |

## Arranque

```powershell
cd zabbix
copy .env.example .env
# Edita .env: ZBX_POSTGRES_PASSWORD (obligatoria) y ZBX_ADMIN_PASSWORD (mínimo 8).
docker compose up -d
docker compose ps
```

La primera vez el servidor crea el esquema de la base (1 a 2 minutos). La
interfaz queda en http://localhost:8090 (usuario `Admin`).

## Alta inicial (init_zabbix.py)

Desde la raíz de SONAR, con el `.venv` activo:

```powershell
python zabbix/init_zabbix.py --switches --token
```

Después, para lo avanzado (traps, tendencias, correlación, Geomap, SLA y 365 días de
trends): `python zabbix/init_zabbix.py --timescaledb --avanzado` (ver más abajo).

El script es idempotente (se puede repetir) y sólo usa la biblioteca estándar y PyYAML:

1. Entra como `Admin`/`zabbix` y cambia la contraseña por `ZBX_ADMIN_PASSWORD`; si ya
   se cambió, entra con ésta.
2. Corrige la interfaz del agente del host "Zabbix server" (viene con 127.0.0.1)
   para que apunte al contenedor `zabbix-agent` por DNS.
3. `--switches`: da de alta los switches activos de SONAR (de la base si
   `INVENTORY_SOURCE=django`, si no de `inventory/devices.yaml`) con interfaz SNMP,
   plantilla **Cisco IOS by SNMP** (o *Network Generic Device by SNMP* si no existe),
   grupo `SONAR/<plantel>` y etiquetas `plantel`, `rol` y `sonar`. Omite los que ya
   existen (por nombre o IP).
   - SNMP v2c: la comunidad (`ZBX_SNMP_COMMUNITY` o `SNMP_COMMUNITY` de SONAR) se
     guarda como macro global secreta `{$SNMP_COMMUNITY}`.
   - SNMP v3 (`SNMP_VERSION=3` en el `.env` de SONAR): usa `SNMP_V3_USER`,
     `SNMP_V3_AUTH_KEY`, `SNMP_V3_PRIV_KEY` y sus protocolos, guardados como macros
     globales `{$SNMPV3_USER}`, `{$SNMPV3_AUTHPASS}` y `{$SNMPV3_PRIVPASS}` (secretas).
   - La plantilla de Cisco ya trae ping ICMP; no se agrega "ICMP Ping" aparte
     (Zabbix rechaza la clave `icmpping` duplicada).
4. `--token`: borra y recrea el token de API "SONAR" del Admin e imprime
   `ZABBIX_URL` y `ZABBIX_TOKEN` para el `.env` de SONAR. Reinicia Django después.

Otra carpeta de SONAR: `--sonar-root C:\ruta\a\SONAR`.

Todas las llamadas usan la cabecera `Authorization: Bearer` (el campo `auth` ya no
existe en Zabbix 7.2).

## Primeros pasos en la interfaz

- **Usuarios del NOC**: *Users → User groups*, crea "NOC" con permiso de lectura
  (o lectura-escritura si reconocerán desde Zabbix) sobre los grupos `SONAR/*`; luego
  *Users → Users* con el *User role* "User role". Admin queda sólo para administrar.
- Desde SONAR, reconocer o comentar un problema exige rol editor o administrador en
  SONAR y queda en la bitácora; Zabbix lo registra a nombre del token.
- Ajusta los umbrales con las macros de la plantilla (p. ej. `{$CPU.UTIL.CRIT}`,
  `{$IF.ERRORS.WARN}`) a nivel de grupo o host.

## Monitoreo avanzado (`--avanzado`)

```powershell
docker compose up -d                                   # postgres con TimescaleDB
python zabbix/init_zabbix.py --timescaledb --avanzado  # idempotente: se puede repetir
python zabbix/init_zabbix.py --backfill                # opcional: histórico de SONAR (ver abajo)
```

`--timescaledb` crea la extensión y convierte `history*`/`trends*` en hypertables
(detiene `zabbix-server` unos segundos; si ya están, no hace nada). `--avanzado`
configura todo lo siguiente, buscando cada objeto por nombre para actualizarlo en lugar
de duplicarlo. Los cambios hechos a mano en la plantilla se pierden al repetirlo:
ajusta las macros a nivel de host o grupo.

### Por qué no hay "agente" en los switches

Los Cisco IOS no admiten instalar el agente de Zabbix y sólo hablan SNMPv2c. El
equivalente real de los "agentes activos" es:

1. **Traps SNMP** (eventos al instante): el servidor lee `zabbix/snmptraps/snmptraps.log`
   (`StartSNMPTrapper=1`, variable `ZBX_ENABLE_SNMP_TRAPS`). Quién escribe ese archivo:
   - **Windows (Docker Desktop)**: `python zabbix/trap_relay.py` en el propio Windows.
     Docker Desktop reemplaza la IP de origen de lo que entra por un puerto publicado por
     la de su gateway (172.x; comprobado), así que el contenedor no sabría de qué switch
     viene cada trap. El receptor escucha UDP 162, ve la IP real, sólo acepta la comunidad
     de SONAR y escribe en el formato de Zabbix. `--prueba` envía un linkDown de prueba.
     Para que arranque con Windows, ver `entregas/zabbix-avanzado/switches-traps.txt` o:
     `Register-ScheduledTask` con `python zabbix	rap_relay.py --sonar-root <SONAR>`.
   - **Linux**: `docker compose --profile traps up -d` (el contenedor sí ve la IP real).

   La plantilla tiene los ítems
   `snmptrap["linkDown|…"]` y `snmptrap["linkUp|…"]` y el disparador
   *SONAR: trap linkDown recibido* (5 min abierto por trap; se puede cerrar a mano).
   Zabbix asocia el trap al host por la IP de origen, que debe ser la misma de su interfaz SNMP.
2. **Proxy activo** (`zabbix-proxy-sqlite3`, modo activo: empuja los datos al servidor
   por el 10051) preparado para una zona o sede:
   ```powershell
   docker compose --profile proxy up -d
   python zabbix/init_zabbix.py --proxy               # registra "SONAR-proxy-zona1" (ZBX_PROXY_HOSTNAME)
   ```
   En otra sede se copia sólo el servicio `zabbix-proxy` con `ZBX_PROXY_SERVER=<IP del
   servidor>` y `ZBX_PROXY_HOSTNAME` distinto, y se registra con `--proxy <nombre>`. Para
   que un plantel lo use: *Data collection → Hosts → (host) → Monitored by: Proxy*. Los
   traps de ese plantel deben ir al equipo del proxy (con su propio receptor de traps).
3. **Ítems críticos rápidos con SNMP bulk**: ping (`icmpping[,3]`, pérdida y
   latencia) y, en cada uplink, estado operativo, bits in/out, errores y CRC cada
   `{$SONAR.FAST.INTERVAL}` (30 s; admite 10-30 s). La interfaz SNMP de los hosts tiene
   *bulk* activado, así que el servidor agrupa esas consultas.

### Plantilla "SONAR Cisco avanzado"

Se enlaza a los hosts con la etiqueta `sonar=switch`, junto a *Cisco IOS by SNMP*.

- **Uplinks** (descubrimiento `sonar.uplink.discovery`): el `ifIndex` de los troncales que
  SONAR ya conoce (`Puerto.es_trunk`, macro por host `{$SONAR.UPLINK.IFINDEX.MATCHES}`),
  interfaces Te/Twe/Fo/Hu o descripción con "uplink/troncal/core/enlace".
- **Óptica RX** (`sonar.optical.discovery`): sensores dBm de CISCO-ENTITY-SENSOR-MIB, los
  mismos que lee el worker de SONAR; umbral `{$SONAR.OPTICAL.RX.MIN}` = -24 dBm.
- **CPU**: `sonar.cpu.util`, el máximo de `cpmCPUTotal1minRev` (switches apilados).

"ML nativo" de Zabbix 7 = funciones de tendencia y pronóstico (no hay otro motor):

| Disparador | Función |
| --- | --- |
| CPU anómala, tráfico anómalo, RX anómala | `trendstl` (descomposición STL de trends horarios, estacionalidad diaria, 7-14 días, 3 MAD) |
| CPU fuera de su línea base | `baselinedev` (misma hora de los 7 días anteriores) |
| Tráfico / CRC sobre su línea base | `trendavg` contra `baselinewma` |
| CPU llegará a 95 % en < 7 d, RX llegará a -24 dBm en < 14 d | ítem calculado con `timeleft` sobre 30 días |
| Uplink se saturará en 7 días | ítem calculado con `forecast` sobre 30 días |

Las funciones de tendencia se evalúan cada hora y necesitan datos: los primeros días
quedan como *Unknown* ("not enough data"). Para no dar falsas anomalías con datos con
huecos, STL y líneas base sólo se evalúan si `trendcount` cubre al menos
`{$SONAR.TREND.MIN.RATIO}` (80 %) de las horas del periodo, y los pronósticos sólo avisan
con 6 días de historia o más. Es normal.

### Backfill desde SONAR (`--backfill`)

Copia a Zabbix lo que SONAR ya guardó, para los mismos ítems de los disparadores:
`sonar.cpu.util` (InfluxDB `cpu_1m`), `sonar.uplink.in/out` (InfluxDB, bps en ventanas de
5 min) y `sonar.optical.rx` (muestras ópticas de SONAR). `history.push` de Zabbix 7 sólo
acepta ítems trapper, así que se escribe con `COPY` en las tablas `history` y `trends`
(una transacción) y después se reinicia `zabbix-server` para que su caché de valores lo
vea. Sólo inserta valores **anteriores** al primero que ya tiene cada ítem: no pisa ni
duplica nada y repetirlo no agrega filas. Saca un respaldo antes (ver abajo).

El histórico de SONAR sólo existe mientras corrió el worker: si fueron unas horas al día,
los pronósticos (timeleft/forecast) ya funcionan pero STL y líneas base esperan a que
Zabbix junte su propia historia continua (la guarda de `trendcount`).

### Correlación de eventos

- **Etiquetas** en todos los disparadores SONAR: `equipo` ({HOST.HOST}), `componente`
  (`disponibilidad`, `red`, `enlace`, `cpu`, `optica`), `interfaz`, `correlacion`
  (`causa`/`sintoma`) y `analisis`; `plantel` y `rol` vienen del host.
- **Disparador compuesto** *SONAR: enlace físico dañado en <interfaz>*: CRC sostenido en
  el uplink **y** pérdida o latencia hacia el switch. Los disparadores de CRC de esa
  interfaz dependen de él (no se generan mientras está activo).
- **Dependencias**: el ping rápido de cada switch de acceso depende del core de su plantel.
- **Correlación global** (*Data collection → Event correlation*):
  1. una causa abierta cierra los síntomas nuevos del mismo equipo;
  2. una causa nueva cierra los síntomas previos del mismo equipo;
  3. un core sin ping cierra los "sin ping" de los accesos del mismo plantel.
- **SONAR** muestra en *En vivo (Zabbix)* cada causa con sus síntomas debajo ("↳ Síntoma
  de …"), tanto los que Zabbix marca como síntoma (`cause_eventid`) como los que comparten
  equipo e interfaz; los síntomas de Zabbix no suman al semáforo ponderado.

### Tablero "SONAR – Planteles", servicios y SLA

- Inventario de cada switch en modo manual con `location_lat`/`location_lon` del plantel:
  "latitud, longitud" del campo *ubicación* del plantel en SONAR o, si está vacío, la
  tabla de `frontend/src/utils/locations.js` (la misma del mapa del NOC).
- Servicio "SONAR · Red UAEH" con un hijo "Plantel: <nombre>" por plantel (problemas con
  `plantel=<nombre>` y `componente=disponibilidad`).
- SLA "SONAR planteles 99.5%" mensual sobre los servicios `sonar=plantel`.
- Tablero (público) con Geomap, reporte SLA, problemas por severidad y problemas con sus
  etiquetas. *Dashboards → SONAR – Planteles*.

### Histórico de 365 días sin InfluxDB

- PostgreSQL con TimescaleDB: hypertables y compresión de lo mayor a 7 días.
- Housekeeping: history `ZBX_HISTORY_DAYS` (90 por omisión, 30-90) y trends 365 días.
- SONAR (`HISTORY_SOURCE=auto`): las gráficas aceptan `?horas=` (hasta 8760); más de
  24 h en Zabbix sale de trends. El reporte *Tendencias* ofrece 90 días y 1 año y, si
  InfluxDB no responde o no tiene el periodo, usa los trends de Zabbix.

### Lo que hay que configurar en cada switch (a mano, no lo hace el script)

En modo configuración de cada Cisco, con la IP del equipo donde corre el receptor de traps
(o el del proxy de la sede) y la misma comunidad v2c que ya usa SONAR. Los comandos ya
completos por switch (IP de Soportet3 e interfaz de gestión real leída por SNMP) están en
`entregas/zabbix-avanzado/switches-traps.txt`, fuera de Git porque llevan la comunidad.

```text
snmp-server enable traps snmp linkdown linkup
snmp-server host <IP del servidor Zabbix> version 2c <comunidad>
snmp-server trap-source <interfaz de gestión, p. ej. Vlan1>
```

`trap-source` hace que el trap salga con la IP que Zabbix tiene dada de alta. Verifica
con `show snmp host`; luego, en Zabbix, *Monitoring → Latest data*, ítem "Trap SNMP
linkDown" del host al desconectar un puerto de prueba. En Windows el puerto 162/udp puede
estar ocupado por el servicio "Captura SNMP" (SNMPTRAP; detenlo) y el firewall debe
permitir 162/udp entrante desde la red de gestión:

```powershell
New-NetFirewallRule -DisplayName "SONAR traps SNMP (UDP 162)" -Direction Inbound -Protocol UDP -LocalPort 162 -RemoteAddress 192.168.27.0/24 -Action Allow -Profile Any
```

## Respaldo y restauración

```powershell
# Dentro del contenedor y luego se copia: en PowerShell 5.1 el ">" corrompe archivos binarios.
docker compose exec -T postgres pg_dump -U zabbix -d zabbix -Fc -f /tmp/zabbix.dump
docker compose cp postgres:/tmp/zabbix.dump zabbix-$(Get-Date -Format yyyyMMdd).dump
# Restaurar (con el servidor detenido):
docker compose stop zabbix-server zabbix-web
docker compose cp zabbix-AAAAMMDD.dump postgres:/tmp/zabbix.dump
docker compose exec -T postgres pg_restore -U zabbix -d zabbix --clean /tmp/zabbix.dump
docker compose start zabbix-server zabbix-web
```

Con TimescaleDB, para restaurar en una base nueva primero corre
`CREATE EXTENSION timescaledb;` y `SELECT timescaledb_pre_restore();`, y al terminar
`SELECT timescaledb_post_restore();`.

Los datos viven en el volumen `sonar-zabbix_zbx_postgres`; `docker compose down`
los conserva y `docker compose down -v` los **borra**.

## Puertos

- 8090/tcp: interfaz web y API (`ZBX_URL`). Ábrelo sólo a la red del NOC.
- 10051/tcp: servidor (agentes activos y proxies).
- 162/udp: traps SNMP desde los switches (`trap_relay.py` en Windows, `zabbix-snmptraps` en Linux).
- Salida hacia los switches: ICMP y SNMP 161/udp.

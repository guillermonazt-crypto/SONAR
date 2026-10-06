# Zabbix para SONAR

Zabbix 7.0 LTS en Docker para el análisis en tiempo real: problemas activos,
disponibilidad (ICMP y SNMP) y últimos valores de cada switch. SONAR los lee por
la API (`/api/vivo/`) y, si InfluxDB no responde, también toma de aquí el historial.

El stack es independiente del `docker-compose.yml` de SONAR (proyecto
`sonar-zabbix`, red propia); se puede levantar en el mismo equipo o en otro.

| Servicio | Imagen | Puerto en el equipo |
| --- | --- | --- |
| postgres | postgres:16-alpine | (sólo red interna) |
| zabbix-server | zabbix/zabbix-server-pgsql:alpine-7.0-latest | `ZBX_SERVER_PORT` (10051/tcp) |
| zabbix-web | zabbix/zabbix-web-nginx-pgsql:alpine-7.0-latest | `ZBX_HTTP_PORT` (8090/tcp → 8080) |
| zabbix-agent | zabbix/zabbix-agent2:alpine-7.0-latest | (sólo red interna) |
| zabbix-snmptraps | zabbix/zabbix-snmptraps:alpine-7.0-latest (profile `traps`) | `ZBX_TRAPS_PORT` (162/udp → 1162) |

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

## Traps SNMP (opcional)

```powershell
docker compose --profile traps up -d
```

Configura los switches para enviar traps al equipo (UDP `ZBX_TRAPS_PORT`). El
contenedor de traps comparte el volumen `zbx_snmptraps` con el servidor; la
plantilla los recibe en el ítem `snmptrap.fallback`. En Windows, el puerto 162 puede
estar ocupado por el servicio "Captura SNMP"; detenlo o usa otro puerto.

## Respaldo y restauración

```powershell
docker compose exec -T postgres pg_dump -U zabbix -d zabbix -Fc > zabbix-$(Get-Date -Format yyyyMMdd).dump
# Restaurar (con el servidor detenido):
docker compose stop zabbix-server zabbix-web
docker compose exec -T postgres pg_restore -U zabbix -d zabbix --clean < zabbix-AAAAMMDD.dump
docker compose start zabbix-server zabbix-web
```

Los datos viven en el volumen `sonar-zabbix_zbx_postgres`; `docker compose down`
los conserva y `docker compose down -v` los **borra**.

## Puertos

- 8090/tcp: interfaz web y API (`ZBX_URL`). Ábrelo sólo a la red del NOC.
- 10051/tcp: servidor (agentes activos y proxies).
- 162/udp: traps SNMP (sólo con el profile `traps`).
- Salida hacia los switches: ICMP y SNMP 161/udp.

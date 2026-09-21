# Arquitectura de SONAR

```text
React (frontend/src/components)
  → cliente HTTP (frontend/src/api/client.js)
  → /api/ (backend/api/urls.py)
  → vistas + permisos + serializers (backend/api/)
  → modelos Django (planteles, switches, usuarios)
  → SQLite local

Worker SNMP → servicios (backend/switches/services.py) → estado actual en Django
            → InfluxWriter → historial en InfluxDB → Grafana
```

## Responsabilidades

- React conserva el aspecto oscuro/cian de Flask. Gestiona sesión, inventario,
  planteles y consulta de puertos. Solo utiliza HTTP; no accede directamente a bases.
- La API autentica cada solicitud, aplica roles y valida los datos antes de escribir.
- Los servicios reciben observaciones del worker, revalidan que el dispositivo siga
  activo y guardan cambios atómicamente. No modifican VLAN ni clasificación manual.
- El ORM representa el inventario y estado actual. InfluxDB conserva series históricas.
- Las migraciones versionan el esquema. La base local y las credenciales no van a Git.

## Autenticación y autorización

Sesiones Django en cookie HttpOnly y token CSRF para login, logout y escrituras.
React obtiene el token de GET /api/auth/session/ y lo renueva después del login.
Vite reenvía /api al puerto 8000; el navegador usa el mismo origen.
En producción sirve React y /api bajo un mismo origen con un proxy HTTPS.
DJANGO_DEBUG=false activa cookies Secure; define hosts y orígenes según despliegue.

| Perfil | API inventario | Usuarios |
|---|---|---|
| Anónimo | Sin acceso | Sin acceso |
| Lector | Consultar | Sin acceso |
| Editor | Consultar, crear, editar, activar/desactivar | Sin acceso |
| Administrador | Igual que editor | Mediante admin Django y permisos Django |

El rol admin de SONAR no equivale a is_superuser. La administración de usuarios
requiere is_staff y los permisos Django correspondientes. No existe registro público
ni endpoint para modificar el propio rol. No se exponen contraseñas o credenciales SNMP.
La API no borra inventario: utiliza activo=false para conservar historial y puertos.

## Contrato HTTP

| Ruta | Métodos | Uso |
|---|---|---|
| /api/auth/session/ | GET | Usuario actual y CSRF |
| /api/auth/login/ | POST formulario | username y password |
| /api/auth/logout/ | POST | Cerrar sesión |
| /api/divisiones/ | GET, POST | Divisiones |
| /api/planteles/ | GET, POST | Planteles |
| /api/switches/ | GET, POST | Inventario |
| /api/{recurso}/{id}/ | GET, PUT, PATCH | Consultar/editar |
| /api/switches/{id}/puertos/ | GET | Últimas observaciones |

Los endpoints de listado retornan arreglos JSON. Las métricas de Switch son de solo
lectura para la API. Los puertos solo se escriben por el servicio del worker.
Errores de validación: 400. Sin sesión o permiso: 403. Login inválido: 401.

## Lecturas y persistencia

SNMP conserva ifIndex para identificar interfaces. Un contador ausente se guarda
como null; 0 es válido. estado_operativo es independiente de estado (color manual).
Un sondeo fallido elimina métricas actuales y marca lectura_correcta=false.
Puertos ausentes en un sondeo pasan a unknown; actualizado conserva la fecha de
la última observación directa. CPU y puertos se muestran junto a sus fechas.
Las operaciones del ORM y de InfluxDB se ejecutan fuera del event loop.
La persistencia Django ocurre antes de InfluxDB: una caída de InfluxDB no impide
actualizar el estado local. No existe transacción distribuida entre ambos almacenes.

El worker necesita acceso de escritura a SQLite y a su directorio. Serializa sus
escrituras para SQLite; se recomienda un único proceso worker. Para mayor concurrencia
puede sustituirse SQLite por PostgreSQL sin cambiar el contrato React.

## Desarrollo y despliegue

Flask fue retirado y está respaldado localmente en .local-backup/flask-web/.
No inicia al ejecutar SONAR y ya no es una dependencia.
INVENTORY_SOURCE=django es la fuente predeterminada. YAML permanece como opción
manual del worker; no sincroniza datos con React ni actualiza puertos Django.

Esta entrega es una base de desarrollo local: no publica servicios, no configura
TLS/proxy productivo ni arranca sondeos reales. Los dashboards abren Grafana por
VITE_GRAFANA_URL, sin incrustar paneles ligados a un switch fijo.

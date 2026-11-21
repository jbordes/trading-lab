# ADR-0021: Rutas descriptivas para la API central

**Estado:** accepted
**Fecha:** 2026-11-05

## Contexto

Las rutas actuales `/v1/telemetry` y `/v2/telemetry` se crearon para distinguir
los dos contratos de los collectors. Sus nombres exponen la forma temporal de
versionado de los mensajes como si fueran recursos del API y dejan ambiguo qué
datos recibe cada ruta. Se decide hacer explícitos los recursos de cuenta y
actividad.

El ADR-0020 decidió una sola base SQLite central con esquema global 6 y mantuvo
las rutas anteriores mientras sus clientes dependieran de ellas. Esta decisión
mantiene el principio de archivo central único, pero evoluciona el esquema a 7
para el contrato wire descriptivo y sus restricciones de almacenamiento.

## Alternativas consideradas

1. Mantener las rutas `/v1` y `/v2` como endpoints públicos. Evita cambios en
   clientes, pero conserva nombres poco descriptivos y mezcla la versión del
   contrato con la forma del recurso.
2. Añadir rutas descriptivas en paralelo y sostener ambas indefinidamente.
   Facilita transición, pero duplica superficie y prolonga la compatibilidad.
3. Cambiar coordinadamente los endpoints y valores de contrato del API, relay y
   collectors, con corte controlado de las colas existentes. Se elige esta opción.

## Decisión

La API central usa las rutas descriptivas siguientes:

| Método | Nueva ruta | Ruta anterior |
| --- | --- | --- |
| POST | `/api/account-state` | `/v1/telemetry` |
| POST | `/api/trading-events` | `/v2/telemetry` |
| GET | `/api/accounts/health` | `/v1/health` |
| GET | `/api/accounts/snapshot` | `/v1/snapshot` |
| GET | `/api/accounts/deals` | `/v1/deals` |
| GET | `/api/accounts/history` | `/v1/account-history` |
| GET | `/api/trading/activity` | `/v2/activity` |
| GET | `/api/trading/activity-progress` | `/v2/activity-progress` |
| GET | `/api/trading/position-cycle-magics` | `/v2/position-cycle-magics` |
| GET | `/api/trading/position-cycles` | `/v2/position-cycles` |

`/health`, `/docs` y `/openapi.json` permanecen iguales. Los identificadores de
formato wire pasan a `mt5-account-state-v1` y `mt5-trading-events-v1`, en lugar
de `mt5-telemetry-v1` y `mt5-telemetry-v2`. El breaking change incrementa la
metadata de los collectors: Telemetry `0.3.0` y Activity `activity-0.8.0`, con
`#property 1.100` en ambos. Los `SourceId` no cambian y las credenciales no se
rotan por el renombrado.

Los nombres de credenciales centrales son `CENTRAL_SNAPSHOT_INGEST`,
`CENTRAL_ACCOUNT_READ`, `CENTRAL_LIVE_INGEST`, `CENTRAL_ACTIVITY_INGEST` y
`CENTRAL_TRADING_READ`. El host config cambia las claves
`v1_source_id` → `snapshot_source_id`, `v2_live_source_id` → `live_source_id` y
`v2_activity_source_id` → `activity_source_id`. La configuración JSON del relay
cambia la clave `version` por `contract` y expresa el contrato como
`account-state` con rol `snapshot`, o `trading-events` con rol `live` o
`activity`. Las combinaciones incompatibles se rechazan.

SQLite conserva el archivo único `central.sqlite3` y los nombres físicos de sus
tablas. Los prefijos del API no definen la versión del esquema. Al cambiar
también los valores del contrato
wire y sus restricciones `CHECK`, el esquema central nuevo es global 7. Una base
`central.sqlite3` nueva usa `PRAGMA user_version=7`; las bases de esquema 6 se
preservan y no se migran implícitamente.

La CLI de la API usa `--db` para esta base única; maintenance usa
`--database central.sqlite3` y crea copias consistentes mediante la API de
backup de SQLite (`BackupPlan`). Los argumentos duales antiguos no forman parte
del circuito central nuevo.

El cambio es incompatible y requiere cutover coordinado: drenar la outbox
anterior y crear una nueva, o preservar la cola no drenada y crear otra con
aprobación explícita y un plan de recuperación. El relay rechaza bindings v1/v2
antiguos aunque la cola esté ACKed; no adopta la outbox anterior automáticamente.
También rechaza fuentes pendientes que no estén configuradas para evitar
orfanarlas sin aviso. No se reescriben mensajes pendientes, ACKs ni cursores. El cutover
requiere recompilar los EAs con rutas y contratos nuevos y generar manualmente
los targets/configuración correspondientes. No se rotan credenciales ni se
despliega automáticamente.

## Consecuencias

- Clientes, relay, API, host config, documentación y EAs deben cambiar como un
  conjunto coordinado; los endpoints antiguos no se dan por compatibles después
  del corte.
- No se añaden aliases de compatibilidad en la API. La versión del formato wire
  sigue siendo independiente de SQLite 7 y de las versiones propias de los EAs.
- Los receptores, CLIs y esquemas aislados anteriores no forman parte del
  producto central y fueron retirados. No se implementa compatibilidad
  ejecutable ni migración automática; los archivos y datasets anteriores no se
  borran.
- El circuito central ya no mantiene el modelo operativo de bases aisladas:
  CLIs, receptores desplegables, migradores y módulos de provisión/runtime de
  ese circuito se retiran; los adaptadores SQLite centrales admiten únicamente
  esquema 7. El catálogo `docs.json` de adaptadores internos se conserva como
  apoyo de pruebas, no como runtime desplegable.
  Archivos y datos antiguos se preservan y las recetas históricas no son
  instrucciones ejecutables actuales.
- La creación central vacía no migra datos, reinicia cursores ni reenvía mensajes
  que ya fueron confirmados.
- Mac aún no está probado. Esta decisión no autoriza el cutover ni el despliegue.

## Relación con ADR anteriores

Este ADR sustituye la decisión de compatibilidad de rutas HTTP de
[ADR-0020](0020-single-central-sqlite-database.md) y corrige el esquema objetivo
del contrato central a 7. Se mantiene el principio de un solo archivo central;
las bases anteriores de esquema 6 se conservan sin migración automática.

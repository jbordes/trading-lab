# Cutover al contrato descriptivo de la API central

Esta guía resume una transición incompatible aprobada por
[ADR-0021](../adr/0021-descriptive-central-api-contract.md). No autoriza
despliegue inmediato. Mac no ha sido probado y ningún cambio se aplica
automáticamente.

La rama actual prepara este contrato; la integración y el cutover operativo
siguen pendientes de revisión y aprobación.

## Rutas y contratos

Los endpoints de ingesta cambian así:

| Uso | Ruta anterior | Ruta nueva | Formato wire nuevo |
| --- | --- | --- | --- |
| Estado de cuenta snapshot | `/v1/telemetry` | `/api/account-state` | `mt5-account-state-v1` |
| Eventos de trading/actividad | `/v2/telemetry` | `/api/trading-events` | `mt5-trading-events-v1` |

Las lecturas v1 cambian a:

- `/api/accounts/health` (antes `/v1/health`)
- `/api/accounts/snapshot` (antes `/v1/snapshot`)
- `/api/accounts/deals` (antes `/v1/deals`)
- `/api/accounts/history` (antes `/v1/account-history`)

Las lecturas v2 cambian a:

- `/api/trading/activity` (antes `/v2/activity`)
- `/api/trading/activity-progress` (antes `/v2/activity-progress`)
- `/api/trading/position-cycle-magics` (antes `/v2/position-cycle-magics`)
- `/api/trading/position-cycles` (antes `/v2/position-cycles`)

`/health`, `/docs` y `/openapi.json` no cambian. Las nuevas versiones de
collector son Telemetry `0.3.0` y Activity `activity-0.8.0` (`#property 1.100`
en ambos). Los `SourceId` existentes se conservan; no rote credenciales por
este cambio. SQLite usa `central.sqlite3`, esquema global 7 y conserva
los nombres internos de sus tablas.

## Configuración que cambia

Los nombres de credenciales centrales son:

| Uso | Variable |
| --- | --- |
| Ingesta de snapshot | `CENTRAL_SNAPSHOT_INGEST` |
| Lectura de cuenta | `CENTRAL_ACCOUNT_READ` |
| Ingesta live | `CENTRAL_LIVE_INGEST` |
| Ingesta Activity | `CENTRAL_ACTIVITY_INGEST` |
| Lectura de trading | `CENTRAL_TRADING_READ` |

Los archivos de host deben usar las claves nuevas: `snapshot_source_id`,
`live_source_id` y `activity_source_id` en lugar de
`v1_source_id`, `v2_live_source_id` y `v2_activity_source_id`.

En la configuración del relay, cambia la clave `version` por `contract` y usa
`account-state` con `role: snapshot`, o `trading-events` con `role: live` o
`role: activity`. Las combinaciones incompatibles se rechazan. Los targets de ingesta deben apuntar a las
rutas nuevas del API central. No copies valores de
tokens a comandos, Git, logs o esta guía. La rotación de secretos no forma parte
automática de este cambio.

## Plan de transición

Coordina con el operador y prepara una ventana de mantenimiento antes de cambiar
API, relay o EAs:

1. Verifica que la versión de API y sus consumidores sean compatibles con el
   nuevo contrato. Respalda los archivos y la configuración privada según el
   procedimiento operativo establecido.
2. Deja drenar la outbox anterior, verifica ACKs centrales y crea una outbox
   nueva. Si no puede drenarse, preserva intacta la cola y crea una nueva solo con
   aprobación explícita y plan de recuperación. El relay rechaza la cola ligada
   a bindings v1/v2 antiguos incluso si quedó ACKed; no la adopta automáticamente.
   No apuntes una outbox existente a otra identidad o destino.
3. Genera y revisa manualmente la configuración nueva de API, host y relay,
   incluyendo los `SourceId`, roles y contratos correspondientes. No reescribas
   mensajes pendientes ni ACKs almacenados.
4. Compila los EAs con las rutas y formatos wire nuevos: Telemetry `0.3.0` y
   Activity `activity-0.8.0`, ambos con `#property 1.100`. Conserva los `SourceId`
   y no rotes credenciales por el renombrado.
5. Durante el corte, detén o retira únicamente los componentes incluidos en el
   plan aprobado. Actualiza API, configuración del relay y EAs como una unidad.
   No cambies ni borres cursores.
6. Verifica por separado aceptación local, ACK central, lecturas de cuenta y
   trading, estado de outbox y datos persistidos. `/health` no reemplaza la
   verificación de lecturas ni prueba por sí solo la cobertura histórica.
7. Conserva la configuración y colas anteriores para rollback. No borres datos
   legacy al finalizar el cambio.

Si no se puede drenar la cola ni preservar la antigua con identidad y destino
intactos, detén el cutover y solicita revisión. No cambies targets a ciegas.

## Datos anteriores y herramientas retiradas

El nuevo esquema SQLite es versión global 7; la API no usa `/v7`. Las
tablas mantienen sus nombres físicos. La clave JSON del relay es `contract`,
no `version`; sus valores son `account-state` y `trading-events`. Se retiraron
las CLIs, receptores y rutas de código del modelo operativo de bases aisladas;
no hay aliases HTTP de compatibilidad ni runtime antiguo desplegable. Los
datasets se preservan sin migración automática.

La creación de una base central vacía de esquema 7 no migra bases anteriores de
esquema 6, no reinicia
cursores de MT5 y no reenvía historial ya confirmado. Antes de conectar datos que
deban preservarse, prepara importación y reconciliación con corte explícito. No
hay un traslado o cutover de Mac aprobado por esta guía.

## Referencias

- [ADR-0021: rutas descriptivas](../adr/0021-descriptive-central-api-contract.md)
- [Una base SQLite central](central-sqlite.md)
- [Preparación de host remoto](remote-host-setup.md)
- [Operación del relay durable](durable-telemetry-relay.md)

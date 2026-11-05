# SQLite de la API central

**Estado:** guía de referencia para la base central y el contrato descriptivo
en la rama actual, pendiente de integración.

La API central usa un único archivo `central.sqlite3`. Su versión global es
`PRAGMA user_version=7` para el contrato descriptivo nuevo. Las bases previas
de esquema 6 se preservan y no se migran implícitamente. La decisión de archivo
único está en
[ADR-0020](../adr/0020-single-central-sqlite-database.md). Este esquema no está
desplegado en la VPS ni en Mac y no ha migrado bases operativas.

## Identidad y tablas

La tabla `accounts` conserva una identidad compartida; `login_masked` es
obligatorio. La tabla `sources` registra las fuentes de la cuenta y su rol:

| Rol | Uso |
| --- | --- |
| `snapshot` | Estado de cuenta del contrato `mt5-account-state-v1` |
| `live` | Eventos live del contrato `mt5-trading-events-v1` |
| `activity` | Actividad e historial del contrato `mt5-trading-events-v1` |

La combinación cuenta + rol es única. La fuente de snapshot del API debe estar
configurada con rol `snapshot` y la misma `account_id`; el ingreso valida el login
enmascarado y el rol.

Tablas de captura:

- `telemetry_messages`: mensajes del contrato de estado de cuenta;
- `telemetry_v2_messages`: mensajes del contrato de eventos de trading;
- `activity_observations`, `activity_coverage` y
  `position_cycle_observations`: observaciones y proyecciones durables derivadas
  de v2.

Los formatos wire actuales son `mt5-account-state-v1` y
`mt5-trading-events-v1`; la API usa rutas descriptivas. No representan
versiones de SQLite y no existe un endpoint `/v7`.

## Operación y garantías

La CLI nueva de API recibe `--db central.sqlite3`; sustituye la configuración
anterior de dos rutas `--v1-db` y `--v2-db`. La tarea de mantenimiento recibe
`--database central.sqlite3` y crea una copia consistente mediante la API de
backup de SQLite, definida por `BackupPlan`.

La base usa WAL y `synchronous=FULL` en las conexiones escritoras. El proceso API
aloja dos adaptadores/conexiones escritoras; SQLite serializa las escrituras.

Al abrir la API se valida el esquema y la versión declarada, sin escanear todas
las filas. La creación inicial y la copia de backup verifican integridad. El
bootstrap nuevo crea una sola base y genera credenciales locales privadas; no usa
`V2ProvisionPlan`.

Las CLIs, receptores y SQL aislado anteriores se retiraron del producto. El
código central admite únicamente esquema 7 y roles `snapshot`, `live` y
`activity`; no acepta esquemas 1, 3, 4, 5 o 6 ni los migra. Los archivos
históricos no se borran, pero importarlos requiere un procedimiento separado.

## Alcance de adopción

El bootstrap crea una base nueva y vacía. No reinicia cursores de los EAs, no
reenvía de nuevo historia que ya fue confirmada y no migra una base existente.
El traslado de datos o un backfill requiere un plan y un corte explícitos; no
cambie la outbox operativa para apuntarla a la base nueva como si fuera una
continuación automática.

La implementación del contrato descriptivo está en la rama actual.
Este documento no afirma que los cambios estén mergeados ni desplegados.

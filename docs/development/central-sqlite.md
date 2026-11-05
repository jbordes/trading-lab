# SQLite de la API central

**Estado:** guía de referencia para el diseño de una sola base central. PR #64
sigue abierto, pendiente de revisión humana de CI y merge.

La API central usa un único archivo `central.sqlite3`. Su versión global es
`PRAGMA user_version=6`. La decisión y su motivación están en
[ADR-0020](../adr/0020-single-central-sqlite-database.md). Este esquema no está
desplegado en la VPS ni en Mac y no ha migrado bases operativas.

## Identidad y tablas

La tabla `accounts` conserva una identidad compartida; `login_masked` es
obligatorio. La tabla `sources` registra las fuentes de la cuenta y su rol:

| Rol | Uso |
| --- | --- |
| `telemetry-v1` | Estado vivo del contrato HTTP v1 |
| `live` | Estado vivo del contrato HTTP v2 |
| `activity` | Actividad e historial del contrato HTTP v2 |

La combinación cuenta + rol es única. La fuente v1 del API debe estar configurada
con rol `telemetry-v1` y la misma `account_id`; el ingreso v1 valida el login
enmascarado y el rol.

Tablas de captura:

- `telemetry_messages`: mensajes del contrato HTTP v1;
- `telemetry_v2_messages`: mensajes del contrato HTTP v2;
- `activity_observations`, `activity_coverage` y
  `position_cycle_observations`: observaciones y proyecciones durables derivadas
  de v2.

Los prefijos `/v1` y `/v2` identifican formatos de mensajes de los collectors;
no representan versiones de SQLite. No existe un endpoint `/v6`.

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

Los lectores y creadores aislados anteriores que operan sobre dos archivos se
conservan para datasets antiguos. No se han eliminado todos los usos de dos
rutas, pero el código nuevo de API central no admite esa configuración.

## Alcance de adopción

El bootstrap crea una base nueva y vacía. No reinicia cursores de los EAs, no
reenvía de nuevo historia que ya fue confirmada y no migra una base existente.
El traslado de datos o un backfill requiere un plan y un corte explícitos; no
cambie la outbox operativa para apuntarla a la base nueva como si fuera una
continuación automática.

La implementación está bajo revisión en PR #64. Este documento describe el
modelo aprobado, no afirma que los cambios estén mergeados ni desplegados.

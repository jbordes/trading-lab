# ADR-0020: Una base SQLite para la API central

**Estado:** accepted

**Fecha:** 2026-11-05

## Contexto

La primera implementación de FastAPI abre una base SQLite v1 para el snapshot y
otra v2 para actividad y ciclos. Esa separación permitió introducir y validar
v2 sin migrar ni modificar la persistencia v1 ya usada por el piloto. No responde
a un requisito de negocio. Ambos almacenes pertenecen a la misma cuenta, API,
host, política de retención y ciclo de backup; mantenerlos separados duplica la
provisión, el mantenimiento y el riesgo de que una restauración cubra solo una
parte de los datos.

Los prefijos HTTP v1 y v2 identifican contratos de mensajes distintos que usan
los collectors. La versión SQLite es una dimensión independiente y no debe
determinar nombres ni rutas HTTP.

## Alternativas consideradas

1. Mantener dos archivos y respaldarlos/restaurarlos juntos. Conserva la
   implementación actual, pero duplica provisión y operación sin un ciclo de
   vida independiente que lo justifique.
2. Consolidar tablas y fuentes en un archivo central con una sola versión global.
   Requiere adaptar los validadores y el bootstrap; simplifica el host piloto y
   comparte identidad de cuenta.
3. Cambiar los collectors a un único contrato HTTP antes de consolidar. Aumenta
   el alcance y fuerza la recompilación/instalación de EAs sin ser necesaria para
   compartir la persistencia.

Se elige la segunda alternativa.

## Decisión

La API central y el bootstrap remoto usan un único archivo `central.sqlite3` con
un esquema global identificado por `PRAGMA user_version = 6`. El esquema comparte
cuentas y fuentes, y conserva tablas y controles específicos para los mensajes
de los contratos v1 y v2. El rol `telemetry-v1` identifica la fuente v1; los roles
`live` y `activity` permanecen limitados a v2.

Se mantienen `/v1/telemetry`, `/v2/telemetry` y sus rutas de lectura actuales
mientras los collectors y clientes dependan de esos contratos. No se renombra
una ruta por el número de versión SQLite. Un cambio de contrato HTTP requiere
su propia evolución coordinada de collector, relay y API.

El host nuevo se crea vacío y desde cero. El bootstrap no importa ni elimina las
dos bases del piloto anterior. El traslado de datos requerirá una herramienta de
importación verificada y un corte explícito; hasta entonces el host anterior
conserva sus datos.

## Consecuencias

- Una sola ruta de SQLite simplifica arranque, permisos, retención y backups.
- Ambos flujos comparten identidad de cuenta y las consultas pueden usar una
  transacción común cuando corresponda.
- SQLite serializa escrituras de ambos flujos en el mismo archivo; la carga del
  piloto es acotada y la API opera como un proceso con escrituras SQLite serializadas.
- `user_version = 6` versiona el esquema completo central, no el endpoint ni el
  payload del collector.
- Los creadores y migradores aislados v1/v2 permanecen disponibles para tests y
  herramientas del piloto anterior; no forman parte del bootstrap central nuevo.
- No se habilita una conversión implícita de archivos v1/v2 independientes a la
  base central. La importación debe comprobar identidad, deduplicación, conteos,
  integridad y el punto de corte antes de redirigir la outbox.

## Reemplaza

Reemplaza la decisión de dos archivos del [ADR-0019](0019-private-remote-host-bootstrap.md).
Mantiene su bootstrap por sistema, directorio privado, API en loopback y política
Tailscale VPS→Mac.

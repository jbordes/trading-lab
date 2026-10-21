# ADR-0007: Receptor local de telemetría con SQLite opcional

**Estado:** accepted

**Fecha:** 2026-10-20

## Contexto

El receptor del piloto confirma mensajes en un buffer volátil. El PR #18 agregó
un arranque supervisado de receptor y dashboard. Ya existe un journal SQLite
aislado, con registro explícito de cuentas/fuentes, deduplicación y recuperación
del último snapshot. Falta conectar ese journal al protocolo local sin dar por
sentada la identidad de cualquier emisor que conozca el token.

## Alternativas consideradas

1. Reemplazar el buffer existente en todos los arranques. Exigiría provisionar
   de inmediato una cuenta/base para cada uso y cambiaría el piloto actual.
2. Agregar un modo SQLite explícito por fuente, con base preexistente, y mantener
   el arranque en memoria cuando no se lo selecciona.
3. Crear un proceso SQLite separado. Añadiría coordinación entre procesos antes
   de observar una necesidad real en el piloto.

## Decisión

Se adopta la segunda alternativa. El supervisor transmite `--sqlite-db` y su
`source_id` al receptor. Ese modo exige una base existente bajo `_storage/` con
la fuente registrada; valida ambos antes de escuchar en el puerto. El token de
ese receptor autoriza únicamente esa fuente. No se descubre ni registra cuentas
a partir de mensajes entrantes.

El receptor conserva loopback y HTTP/1.1. En modo SQLite confirma inserciones
solo después del commit; los reenvíos idénticos reciben confirmación de duplicado.
Las lecturas restauradas conservan sus horas originales. Un error de almacenamiento
devuelve error controlado, sin confirmar solo en memoria.

El supervisor del PR #18 conserva sus comprobaciones de puertos, disponibilidad
HTTP y limpieza de hijos. Ninguna prueba de este modo requiere una terminal MT5.

## Consecuencias

La conexión SQLite se comparte entre los hilos del receptor con acceso
serializado. El primer piloto persistente autoriza una fuente por receptor/token;
se podrá ampliar después con credenciales por fuente si aparece un caso real.

Los contadores de `/health` describen el proceso en curso y se reinician con él;
`storage=sqlite` permite distinguir el modo. El snapshot restaurado puede ser
antiguo y el dashboard mantiene su comprobación de edad. Esta integración no
recupera observaciones que no llegaron al receptor ni elimina la necesidad de
retención y backups. La provisión de la base y de las identidades se mantiene
como paso operativo explícito antes de habilitar el piloto persistente.

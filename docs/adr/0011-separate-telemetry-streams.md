# ADR-0011: Separar estado vivo y actividad de cuenta

**Estado:** proposed

**Fecha:** 2026-10-22

## Contexto

El snapshot v1 mezcla estado vivo con historial de deals. Repetir historial a la
frecuencia de equity aumenta volumen y acopla recuperación a presentación. El
receptor persistente vigente admite una fuente por token (ADR-0007).

## Alternativas consideradas

1. Duplicar el collector v1 con intervalos distintos: duplica información y no
   define quién gobierna cada parte del estado.
2. Un collector con temporizadores lógicos separados: menos despliegue, pero
   conserva procesamiento y envío serializados en el mismo EA.
3. Dos EAs con módulos comunes, roles explícitos y composición por cuenta en un
   receptor local: permite frecuencias y recuperación independientes.

## Decisión

Se propone la tercera alternativa, inicialmente sobre la terminal demo actual.
El [contrato v2 propuesto](../architecture/telemetry-v2-contract.md) define
`live_snapshot` y `activity_batch`, más heartbeat por productor. Cada fuente
tiene un rol provisionado; la cuenta se resuelve desde ese registro. Un solo
productor primario por cuenta/rol evita una resolución implícita entre réplicas.
La credencial de cada productor autoriza su fuente y rol; el token humano continúa
separado. Las lecturas internas requerirán autorización explícita independiente
de las credenciales de escritura de los productores.

El backend preserva frescura y cobertura por flujo. Los eventos disparan captura
acotada y la reconciliación recupera pérdidas. Una orden cancelada es evidencia
operativa, no un trade ni una pérdida de trading.

El contrato v1 continúa sin cambios. V2 se activará mediante configuración
explícita después de implementar validación, almacenamiento y composición.
No se habilita mezclar productores v1 y v2 como primarios de la misma cuenta.

## Consecuencias

Se necesita evolucionar admisión, esquema de persistencia y vista del dashboard,
además de los collectors. El parser y receptor actuales siguen rechazando v2.
La migración de datos y el despliegue se aprobarán por separado. Este ADR sigue
propuesto: no modifica ADR-0004/0007 aceptados ni autoriza cambios operativos.

La terminal extra, SSE y captura cada segundo no son requisitos de este paso.
No se promete un registro completo de cambios intrasegundo ni se define aquí
la fórmula para agrupar ejecuciones en trades o calcular riesgo.

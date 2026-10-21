# ADR-0008: Retención conservadora de telemetría durante el piloto

**Estado:** accepted

**Fecha:** 2026-10-20

## Contexto

El receptor opcional guarda mensajes MT5 en SQLite y puede generar copias
locales consistentes. Todavía no hay una medición representativa del crecimiento
con EAs operando, ni un destino externo y una restauración probados. El historial
recibido permite reconstruir vistas y verificar deduplicación; eliminarlo antes
de definir métricas y reconciliación podría perder evidencia irrepetible.

## Alternativas consideradas

1. Aplicar un plazo fijo de borrado desde el inicio. Reduce espacio, pero fija
   una pérdida de datos sin conocer el volumen ni el uso analítico.
2. Conservar todo durante el piloto, medir crecimiento y decidir una política
   definitiva con datos reales.
3. Compactar o eliminar automáticamente snapshots antiguos. Requiere demostrar
   qué datos se pueden reconstruir sin afectar métricas, auditoría o reenvíos.

## Decisión

Se adopta la segunda alternativa **solo para el piloto demo**:

- La base SQLite conserva todos los mensajes recibidos, identidades y registros
  de deduplicación. No hay TTL, compactación ni borrado automático. La retención
  de estos registros debe seguir cubriendo los reenvíos que se prometen aceptar.
- Se hace una copia consistente antes de una migración o cambio manual de la
  base y al menos una vez por cada día con captura. La copia se verifica con su
  manifest y SHA-256; su sola creación no equivale a probar restauración.
- Se conservan todas las copias del piloto. El procedimiento actual es manual;
  ninguna tarea programada ni limpieza automática queda autorizada por este ADR.
- Registrar por día de captura el tamaño de la base, el tamaño acumulado de las
  copias, el espacio libre y si la copia fue verificada. Una jornada sin copia
  se señala como brecha, no como cobertura completa.
- Tras la primera semana completa de captura con operaciones reales, revisar
  crecimiento, frecuencia y utilidad de cada clase de dato con el socio. La
  política posterior requerirá una decisión nueva; este ADR no la anticipa.
- Si el espacio disponible amenaza la captura o las copias, detener el modo
  persistente y resolver capacidad o exportación antes de eliminar datos.
  Cualquier eliminación excepcional requiere autorización humana, alcance
  exacto y restauración verificada de la copia que se conservará.

Antes de depender de captura continua o de datos críticos, se necesita una copia
fuera de la VPS, un ensayo de restauración y objetivos de pérdida y recuperación
acordados. Las copias locales no protegen ante pérdida de esa máquina. Google
Drive puede transportar paquetes, pero no es fuente de verdad ni señal de
ejecución.

## Consecuencias

El piloto prioriza integridad y capacidad de análisis por encima de ahorrar
espacio. El almacenamiento crecerá y habrá que medirlo. Esta decisión no
modifica bases existentes, no activa SQLite en ninguna terminal y no autoriza
operar con cuentas reales ni automatizar borrados.

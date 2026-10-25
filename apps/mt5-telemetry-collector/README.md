# Collectors de telemetría MT5

Estos EAs emiten observaciones desde un terminal MT5 hacia receptores locales.
No abren, cierran ni modifican operaciones y no aceptan instrucciones remotas.

- `TradingLabTelemetry.mq5`: snapshot v1 vigente de cuenta, posiciones, órdenes
  pendientes y una ventana reciente de deals.
- `TradingLabActivity.mq5`: piloto v2 de actividad histórica con deals, órdenes
  finalizadas y recuperación por tramos. Todavía no está instalado.

## Collector vigente v1

- Solo admite un endpoint `http://127.0.0.1:<puerto>/...`.
- El EA no crea una base; el receptor decide si persiste los snapshots.
- Envía estado de cuenta, posiciones y órdenes activas.
- `OnTradeTransaction` solo marca actividad; el envío se realiza en el siguiente
  tick del temporizador para no bloquear el callback.
- No envían velas ni estado interno de otros EAs.
- El archivo compilado `.ex5` nunca se versiona.

## Prueba manual autorizada

Para el piloto existente, usar el
[procedimiento de arranque y recuperación](../../docs/development/telemetry-operation.md).
El arranque conjunto usa los puertos 8776/8775; los ejemplos individuales
de abajo conservan los valores genéricos 8766/8765.

1. Ejecutar el receptor con un token de prueba configurado fuera de Git.
2. Compilar `TradingLabTelemetry.mq5` mediante MetaEditor.
3. Autorizar exactamente `http://127.0.0.1:8766` en la lista de WebRequest de
   una terminal demo separada.
4. Adjuntar el EA a un solo gráfico con el mismo token y un `SourceId` no sensible.
5. Comparar `/health` con la captura Python actual.

La compilación, instalación y conexión a MT5 requieren aprobación humana y no
forman parte de las validaciones automáticas.

## Collector de actividad v2

El collector v2 exige un inicio histórico explícito y usa tiempo de servidor MT5.
Consulta ventanas de hasta seis horas por defecto, filtra exactamente por
milisegundos y envía como máximo 200 deals y 200 órdenes por lote. Si un rango
supera ese límite, lo divide hasta `MinimumWindowSeconds`. Un mínimo todavía
saturado se guarda como `truncated`, bloquea el avance y requiere revisión.

El cursor se conserva en las variables globales de la terminal, asociado a la
fuente y la identidad demo. Solo avanza después de HTTP 200/202 y fuerza el
guardado a disco. Un corte antes de confirmar vuelve a consultar con solapamiento;
la composición del backend resuelve reobservaciones por ticket. Los rechazos 4xx
detienen el EA y los fallos transitorios reintentan el mismo cuerpo con espera
creciente.

La base y el cursor no se coordinan automáticamente. Si se recrea la base, cambia
la fuente o se desea reiniciar el período, el operador debe revisar y eliminar
manualmente las variables `TL2.ACT.*` correspondientes antes de volver a adjuntar
el EA. No ejecutar dos instancias con la misma fuente. La instalación piloto debe
seguir un procedimiento supervisado y contrastarse con el historial de MT5.

# MT5 Telemetry Collector — spike

Este componente experimental emite observaciones desde un terminal MT5 hacia un
receptor local. No abre, cierra ni modifica operaciones y no acepta instrucciones
desde el receptor.

## Límites de este corte

- Solo admite un endpoint `http://127.0.0.1:<puerto>/...`.
- Conserva snapshots en memoria; no crea una base de datos.
- Envía estado de cuenta, posiciones y órdenes activas.
- `OnTradeTransaction` solo marca actividad; el envío se realiza en el siguiente
  tick del temporizador para no bloquear el callback.
- Todavía no envía deals históricos ni velas.
- El archivo compilado `.ex5` nunca se versiona.

## Prueba manual autorizada

1. Ejecutar el receptor con un token de prueba configurado fuera de Git.
2. Compilar `TradingLabTelemetry.mq5` mediante MetaEditor.
3. Autorizar exactamente `http://127.0.0.1:8766` en la lista de WebRequest de
   una terminal demo separada.
4. Adjuntar el EA a un solo gráfico con el mismo token y un `SourceId` no sensible.
5. Comparar `/health` con la captura Python actual.

La compilación, instalación y conexión a MT5 requieren aprobación humana y no
forman parte de las validaciones automáticas.

# Collectors MT5

## Estado del código

Las versiones preparadas para el contrato descriptivo son `0.3.0` y
`activity-0.8.0`. No están instaladas: requieren un cutover coordinado de API,
relay y outbox. No son versiones 1 y 2 del mismo collector. `-v1` en los
formatos wire indica la primera versión de cada contrato independiente.

| EA | Versión | Responsabilidad | Rol | Ruta de ingesta | Formato wire |
| --- | --- | --- | --- | --- | --- |
| `TradingLabTelemetry.mq5` | `0.3.0` | Estado actual de cuenta, balance/equity, posiciones y órdenes | `snapshot` | `POST /api/account-state` | `mt5-account-state-v1` |
| `TradingLabActivity.mq5` | `activity-0.8.0` | Deals y órdenes históricas, recuperación, progreso y reconciliación de posiciones | `activity` | `POST /api/trading-events` | `mt5-trading-events-v1` |

La topología es EA → relay local → API central → `central.sqlite3` (esquema 7);
el dashboard lee a través de la API. El ACK del relay confirma admisión en la
outbox local, no persistencia central ni cobertura histórica completa.

Los EAs leen la cuenta MT5 completa, no solo el símbolo o timeframe del gráfico.
No abren, cierran ni modifican órdenes, no ejecutan SQLite y no aceptan
instrucciones remotas. `OnTradeTransaction` registra señales mínimas en memoria;
la consulta de historial, la red y la reconciliación se realizan desde el
temporizador, fuera del callback.

## Identidad, transición y compilación

El `SourceId` y token local de cada EA deben coincidir con la fuente y credencial
configuradas en el relay. La credencial central del relay es distinta. Durante
la transición conserva los `SourceId` y tokens actuales; no los rotes por el
cambio de contrato. Antes de adoptar las versiones preparadas, sigue el
[cutover coordinado](../../docs/development/descriptive-api-cutover.md). No
reinicies ni borres cursores o datos para recrear la base central.

Compila desde este workspace con el MetaEditor RoboForex autorizado. Mantén
juntos los tres headers:

- `TradingLabCollectorCommon.mqh`
- `TradingLabActivityState.mqh`
- `TradingLabCollectorLog.mqh`

La compilación no instala los EAs. Los `.ex5` son artefactos locales y no se
versionan en Git; cualquier instalación requiere el procedimiento supervisado.

## Logs

Los archivos por terminal están en `MQL5\Files\TradingLab\logs\`:

- `telemetry-<SourceId>-YYYYMMDD.jsonl`
- `activity-<SourceId>-YYYYMMDD.jsonl`

La fecha es UTC y `:` del `SourceId` se sustituye por `~` en el nombre. Se
registran `WARN`, `ERROR` y `RESOLVED` al cerrar una incidencia; no hay mensajes
de inicio/parada ni estado healthy. El registro nunca incluye tokens, headers,
payloads ni credenciales.

## Referencias

- [Manual de instalación y operación](../../docs/development/mt5-collector-operations.md)
- [API, relay y dashboard](../../docs/development/central-api-dashboard.md)
- [Resiliencia y evidencia histórica](../../docs/development/mt5-collector-resilience.md)

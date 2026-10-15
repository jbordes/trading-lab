# Spike de colector de telemetría MT5

**Fecha:** 2026-10-16

**Estado:** infraestructura local implementada; compilación y prueba demo pendientes

**Decisión:** [ADR-0003](../adr/0003-mt5-push-telemetry-spike.md)

## Objetivo

Comprobar si un colector MQL5 propio complementa la API Python cuando el terminal
está en otra VPS o se necesita reaccionar a actividad con menor demora. El spike
no reemplaza la fuente Python ni implementa métricas de riesgo.

```text
Terminal demo MT5
    |
    | POST /v1/telemetry + Bearer token
    v
receptor 127.0.0.1:8766
    |
    v
buffer acotado en memoria + /health
```

El receptor es un proceso separado. El servidor del dashboard continúa
rechazando `POST` y no conoce el token de ingestión.

## Contrato `mt5-telemetry-v1`

Cada mensaje contiene:

- versión del schema y del colector;
- `source_id` no sensible;
- `session_id` nuevo por inicio del EA;
- secuencia positiva y `event_id` idempotente;
- instante UTC;
- tipo `heartbeat` o `account_snapshot`;
- payload validado y acotado.

El snapshot conserva identificadores MT5 como texto, enmascara el login e incluye
estado de cuenta, cantidad total y muestra limitada de posiciones y órdenes. La
diferencia entre el total y la muestra hace visible cualquier truncamiento.

Una repetición idéntica es idempotente. Reutilizar una secuencia o `event_id` con
otro contenido se rechaza. Los saltos de secuencia se aceptan, pero quedan
contabilizados para el diagnóstico.

## Seguridad del spike

- Bind fijo a `127.0.0.1`.
- Endpoint de ingestión único y autenticado.
- Token leído desde `TRADINGLAB_TELEMETRY_TOKEN`; nunca por argumentos o Git.
- Cuerpo máximo de 256 KiB, JSON UTF-8 y schema estricto.
- Sin persistencia, logs de payload, eco del token ni comandos de respuesta.
- Fuente `.mq5` sin imports, DLLs o funciones de trading.
- Guarda automática del harness para llamadas MQL5 prohibidas.
- El `.ex5` resultante permanece ignorado por Git.

La guarda textual reduce accidentes, pero no reemplaza revisión humana ni la
compilación desde la fuente versionada.

## Ejecución local

Preparar el entorno y definir un token efímero de al menos 24 caracteres fuera
del repositorio. Luego ejecutar:

```text
uv run python scripts/telemetry_receiver.py --port 8766
```

El estado diagnóstico queda disponible en:

```text
http://127.0.0.1:8766/health
```

No expone un listado histórico completo y se pierde al detener el proceso.

## Fuente MQL5

`apps/mt5-telemetry-collector/TradingLabTelemetry.mq5`:

- valida que el endpoint sea loopback;
- usa un temporizador entre 2 y 60 segundos;
- marca actividad mediante `OnTradeTransaction`;
- envía el snapshot reconciliado en el siguiente tick del temporizador;
- reintenta exactamente el mismo mensaje si la respuesta es ambigua o falla;
- ignora el cuerpo de respuesta y nunca recibe instrucciones;
- limita posiciones y órdenes por snapshot.

Todavía no envía deals históricos, velas ni muestras intermedias de equity. Esos
incrementos dependen de lo observado en la comparación.

## Prueba manual pendiente

1. Revisar la fuente y compilarla con MetaEditor sin warnings.
2. Iniciar el receptor con un token efímero.
3. Autorizar únicamente `http://127.0.0.1:8766` en una terminal demo.
4. Adjuntar el EA a un solo gráfico.
5. Ejecutar simultáneamente el dashboard con fuente Python.
6. Comparar cuenta, posiciones, órdenes, Magic Numbers, timestamps y latencia.
7. Interrumpir el receptor, reanudarlo y comprobar reintento e idempotencia.
8. Reiniciar el EA y comprobar la nueva sesión.
9. Retirar el EA y revocar/eliminar el token de prueba.

## Gate de decisión

No se diseñará un endpoint remoto hasta documentar:

- brechas reales de la API Python;
- latencia y completitud de ambos mecanismos;
- comportamiento ante desconexiones;
- consumo del terminal y tamaño de payload;
- frecuencia necesaria para cuenta, operaciones, riesgo y velas;
- necesidad de persistencia y política de retención.

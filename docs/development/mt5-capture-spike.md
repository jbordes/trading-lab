# Spike de captura MT5 — contrato e inventario inicial

**Fecha:** 2026-10-14

**Estado:** Incremento 0A implementado; pendiente de ejecución en el terminal del socio

## Objetivo

Determinar qué información entrega realmente el terminal MT5 antes de diseñar la reconstrucción final o el Excel. El spike produce evidencia JSON local, inmutable y con hash; no ejecuta operaciones ni transforma los datos en trades canónicos.

## Conjuntos capturados

| Conjunto | Llamada MT5 | Uso esperado |
|---|---|---|
| Cuenta | `account_info()` | Contexto de balance, equity, moneda, broker y modo de cuenta |
| Terminal | `terminal_info()` | Build, conexión y capacidades del terminal |
| Órdenes históricas | `history_orders_get()` | Intenciones, estados, Magic Number, comentarios y relación con posiciones |
| Deals históricos | `history_deals_get()` | Ejecuciones, entradas/salidas, volumen, precio, costes y beneficio |
| Posiciones abiertas | `positions_get()` | Snapshot de volumen, SL, TP, precio, swap y beneficio flotante |
| Órdenes activas | `orders_get()` | Snapshot de pendientes y órdenes aún no finalizadas |

Todos los campos devueltos por las estructuras del paquete se conservan sin seleccionar columnas prematuramente. El contrato estable se limita por ahora a los seis conjuntos anteriores, la ventana solicitada, el instante de captura y la versión del schema.

## Evidencia generada

Cada ejecución completa produce fuera de Git:

```text
_storage/mt5-diagnostics/mt5-capture-<UTC>.json
_storage/mt5-diagnostics/mt5-capture-<UTC>.manifest.json
```

El manifest registra nombre, schema, tamaño y SHA-256 de la captura. Una repetición con contenido idéntico es idempotente; una ruta ocupada por contenido diferente se rechaza. Los consumidores futuros deberán considerar completa una captura solo cuando exista su manifest válido.

La evidencia puede contener cuenta, broker, saldos y actividad operativa. Por eso permanece en `_storage/`, nunca se imprime completa ni se incorpora a Git.

## Golden fixture

`tests/fixtures/incubation/mt5_capture_golden_v1.json` es una muestra sintética y anonimizada. Incluye:

- una posición cerrada con orden y deal de entrada y salida;
- una posición abierta;
- una orden pendiente;
- Magic Number y comentario de estrategia;
- snapshot mínimo de cuenta y terminal.

No representa resultados reales ni pretende fijar todavía el modelo final de trades. Su función es estabilizar la frontera de captura y permitir que la reconstrucción futura tenga un caso reproducible.

`tests/fixtures/incubation/expected_trades_golden_v1.json` fija la salida cerrada esperada para ese caso: las 37 columnas del workbook de referencia más `magic_number`. La prueba de contrato exige exactamente esas 38 columnas, pero todavía no implementa la transformación entre ambos fixtures.

## Uso

Validar argumentos sin conectarse:

```text
uv run python scripts/mt5_diagnostic.py \
  --date-from 2026-10-13T18:00:00Z \
  --date-to 2026-10-14T18:00:00Z \
  --dry-run
```

Preparar en Windows el extra opcional bloqueado y ejecutar con un terminal MT5 ya autenticado:

```text
uv sync --locked --extra mt5
uv run python scripts/mt5_diagnostic.py \
  --date-from 2026-10-13T18:00:00Z \
  --date-to 2026-10-14T18:00:00Z
```

El comando no recibe login ni contraseña y no importa ni expone funciones de envío de órdenes. Si una lectura falla, no publica evidencia parcial y siempre cierra la conexión inicializada.

## Qué debe comprobar la ejecución real

1. Campos exactos devueltos por el build de MT5 y por cada broker piloto.
2. Presencia y consistencia de `magic`, `position_id`, tickets, comentarios y milisegundos.
3. Diferencias entre cuentas netting y hedging, si ambas existen.
4. Representación de cierres parciales, comisiones, fees y swaps.
5. Cambios observables entre snapshots sucesivos de una posición abierta.
6. Qué modificaciones intradiarias no pueden reconstruirse mediante historial y snapshots.
7. Conteos y totales frente al reporte XLSX del mismo intervalo.

## Límites deliberados

- No reconstruye todavía el ciclo de vida de una posición.
- No genera el Excel de incubación.
- No implementa scheduler, alertas ni base de datos.
- No instala un EA ni un colector `OnTradeTransaction`.
- No decide cómo mostrar abiertas, pendientes o correcciones en el workbook.

Esos pasos se habilitan únicamente después de ejecutar el spike con datos reales anonimizables y resolver las aclaraciones funcionales pendientes.

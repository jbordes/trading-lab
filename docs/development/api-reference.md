# Referencia de APIs de TradingLab

Esta es la puerta de entrada única para las interfaces HTTP implementadas por
TradingLab. Describe el contrato operativo vigente; los documentos enlazados
amplían el formato de telemetría y los procedimientos de arranque.

Los receptores v1 y v2 publican `/docs` (guía navegable con ejemplos curl) y
`/docs.json` (catálogo JSON, no OpenAPI). Son rutas estáticas sin autenticación,
sin acceso a cuentas ni tokens, y funcionan sin servicios externos. Los
servidores están ligados a `127.0.0.1` y las APIs son internas al piloto. No se
deben exponer directamente a Internet.

En el piloto habitual: `http://127.0.0.1:8776/docs` para v1 y
`http://127.0.0.1:8777/docs` para v2. El dashboard conserva sus endpoints propios.
La evolución remota se define en el
[contrato central](../architecture/central-ingestion-api-contract.md).

## Mapa rápido

| Servicio | Puerto habitual | Interfaz | Consumidor | Autenticación |
| --- | ---: | --- | --- | --- |
| Dashboard | `8775` en el piloto v2 | `/api/*` | navegador autenticado | cookie de sesión |
| Telemetría v1 | `8776` | `/v1/*` | collector v1 y backend | Bearer del collector |
| Telemetría v2 | `8777` | `/v2/*` | collectors v2 y backend | Bearer por productor o de lectura |

Los puertos son configurables. Todas las fechas `*_msc` son enteros en
milisegundos según la escala temporal entregada por MT5. Los rangos temporales
usan inicio incluido y fin excluido: `[from_msc, to_msc)`.

## API del dashboard

Estas rutas están pensadas para la aplicación web, no como API pública. El
servidor valida el encabezado `Host`; las rutas protegidas requieren la cookie
de sesión creada por `POST /login`. El token humano nunca es el token de los EAs.

### `GET /api/account-history`

Proxy con sesión del historial de capturas de cuenta del receptor v1. Requiere
`from_msc` y `to_msc`; la fuente se resuelve en el backend. Admite como máximo
366 días y devuelve hasta 480 puntos, agrupados en buckets de al menos un minuto
con la última observación disponible. No preserva extremos de cada bucket, no
rellena huecos ni cambia la retención. La respuesta refleja capturas existentes.

### `GET /api/state`

Devuelve la muestra actual de la cuenta, operaciones abiertas, actividad
reciente, salud de la fuente y el historial ligero utilizado por la interfaz.
`interval_seconds` describe el polling del dashboard;
`capture_interval_seconds`, `freshness_tolerance_seconds` y
`latest_age_seconds` forman el contrato de frescura de la captura y no dependen
del reloj civil del navegador.

Parámetro opcional:

- `since`: cursor temporal emitido por una lectura anterior; permite pedir solo
  el incremento del historial. Un valor inválido devuelve `400`.

Respuestas principales: `200`, `401 authentication_required`.

### `GET /api/deals`

Devuelve una página descendente de deals históricos recuperados.

Parámetros:

- `from_msc` y `to_msc`: obligatorios, enteros canónicos y positivos, con
  `0 <= from_msc < to_msc < 2^63`.
- `magic_number`: filtro opcional por Magic Number.
- `limit`: opcional, `1..100`; valor predeterminado `50`.
- `cursor`: opcional; se debe reutilizar exactamente el `next_cursor` de la
  página anterior.

La respuesta contiene `account_id`, `source_id`, rango, filtro, `deals`,
`next_cursor` y, con la fuente v2, `coverage`. Un `next_cursor` nulo indica la
última página.

Respuestas principales: `200`, `400 invalid_history_query`, `401
authentication_required`, `404 history_unavailable`, `503
history_unavailable`.

### `GET /api/orders`

Devuelve una página descendente de órdenes históricas, incluidas las canceladas,
vencidas, rechazadas y ejecutadas que entregue MT5. Usa los mismos parámetros y
límites que `/api/deals`: `from_msc`, `to_msc`, `magic_number`, `limit` y
`cursor`.

La respuesta contiene `account_id`, `source_id`, rango, filtro, `orders`,
`next_cursor` y `coverage`. Cada orden conserva tipo, estado, volúmenes, precios,
SL/TP, tiempos, posición relacionada y comentario. Una orden sin ejecución puede
tener `position_id` igual a `0`; no constituye un trade ni genera P/L.

Respuestas principales: `200`, `400 invalid_order_history_query`, `401
authentication_required`, `404 order_history_unavailable`, `503
order_history_unavailable`.

### `GET /api/metrics`

Calcula las métricas actualmente implementadas sobre los deals seleccionados.
Admite `from_msc`, `to_msc` y `magic_number` con las mismas reglas que
`/api/deals`; no admite paginación explícita.

La respuesta identifica la versión de fórmula y la selección utilizada, e
incluye cantidad de trades, resultado neto, Profit Factor, porcentaje ganador,
promedio, drawdowns, Return/DD, expectativa en R, desviación estándar y las
series para gráficos. Los valores no calculables se representan con `null`.

Estas métricas todavía pertenecen al cálculo basado en deals. Los ciclos de
posición reconciliados son la base prevista para excluir operaciones incompletas
o intervenidas antes de considerar las métricas definitivas de un EA.

Respuestas principales: `200`, `400 invalid_metrics_query`, `401
authentication_required`, `404 metrics_unavailable`, `503
metrics_unavailable`.

### `GET /api/position-cycles`

Devuelve una página de ciclos de posición reconciliados a través de la sesión del
dashboard, sin entregar al navegador la credencial interna del receptor v2.

Parámetros opcionales:

- `owner_magic`: Magic Number propietario atribuido al ciclo.
- `owner_magics`: lista CSV de hasta 12 Magic Numbers, incompatible con
  `owner_magic`; se aplica en SQLite antes del cursor y el límite.
- `from_msc` y `to_msc`: período semiabierto opcional; deben aparecer juntos.
- `closed=true`: limita el resultado a ciclos cerrados.
- `limit`: tamaño de página `1..100`; valor predeterminado `50`.
- `cursor`: cursor opaco recibido como `next_cursor`.

La respuesta contiene `account_id`, `source_id`, `owner_magic`, `cycles` y
`next_cursor`. Los importes decimales se conservan como texto para no perder
precisión. Cada ciclo informa elegibilidad y motivos de exclusión.

Respuestas principales: `200`, `400 invalid_position_cycles_query`, `401
authentication_required`, `404 position_cycles_unavailable`, `503
position_cycles_unavailable`.

### `GET /api/cycle-metrics`

Calcula las métricas `position-cycle-v1` exclusivamente sobre ciclos cerrados y
elegibles. Requiere `from_msc` y `to_msc`; admite `magic_number` como filtro del EA
propietario o `magic_numbers` como lista CSV de hasta 12 Magic explícitos. Los
valores deben ser enteros signed 64-bit canónicos, únicos; `magic_number` y
`magic_numbers` no se pueden combinar. No admite paginación explícita. El backend
recorre todos los ciclos vigentes del período en orden cronológico y calcula los
resultados escalares sin el antiguo límite funcional de 500 operaciones.

La respuesta conserva las métricas y series existentes, donde cada punto
representa una posición completa reconstruida, y agrega `by_ea`. Este campo
agrupa por `account_id + magic_number` y contiene para cada grupo
`trade_count`, `net_profit`, `profit_factor`, `winning_percentage`,
`maximum_drawdown`, `average_trade` y `series` con los campos `time_msc`,
`cumulative_profit`, `net_profit`, `drawdown` y `rolling_average_20`. La respuesta
incluye `selected_magics` y `available_magics`; este último enumera los Magic
propietarios elegibles para el período. La consulta base sigue acotada y el
backend calcula la selección sobre ella; las métricas agregadas se recalculan
desde los ciclos seleccionados, sin sumar ratios. El cálculo mantiene memoria
acotada: conserva como máximo 1.200 puntos deterministas por serie para dibujar,
pero usa todas las operaciones para los valores escalares. Los grupos aplican las
mismas fórmulas y cobertura del contrato existente. Ciclos incompletos,
intervenidos o con Magic mixtos quedan fuera sin ser eliminados del historial.

Respuestas principales: `200`, `400 invalid_cycle_metrics_query`, `401
authentication_required`, `404 cycle_metrics_unavailable`, `503
cycle_metrics_unavailable`.

### `GET /health`

Devuelve únicamente `{"status": ...}`. No requiere sesión y no expone datos de
la cuenta. Se usa para salud local, no para descubrir el resto de la API.

### Sesión web

- `GET /login`: formulario o redirección al dashboard si ya hay sesión.
- `POST /login`: valida el token humano y crea una cookie local de sesión.
- `POST /logout`: invalida la sesión; el cuerpo debe estar vacío.

### `GET /api/cycle-magics`

Descubre hasta 100 Magic Numbers con ciclos persistidos mediante una consulta
separada y acotada. No recibe parámetros y evita cargar ciclos completos para
armar el selector. Requiere sesión del dashboard.

## Receptor de telemetría v2

Es la interfaz vigente del piloto para actividad durable. Está ligada a
loopback. La credencial de lectura es distinta de las credenciales de los
productores `live` y `activity`.

### `POST /v2/telemetry`

Recibe mensajes `mt5-telemetry-v2` de los collectors autorizados. Requiere:

- `Content-Type: application/json`;
- `Authorization: Bearer <credencial del productor>`;
- `Content-Length` único y cuerpo dentro del límite configurado;
- productor, rol y fuente previamente registrados para esa credencial.

`202` significa mensaje nuevo aceptado y `200` una repetición idempotente. La
respuesta informa `status`, `sequence_gap` y `out_of_order`.

Errores relevantes: `400 invalid_message`, `401 unauthorized`, `403
source_not_allowed`, `409 idempotency_conflict`, `409 stale_sequence`, `413
too_large`, `415 content_type`, `503 storage_unavailable`.

El cuerpo completo se define en el
[contrato de telemetría v2](../architecture/telemetry-v2-contract.md).

### `GET /v2/activity`

Consulta el historial durable de actividad. Requiere
`Authorization: Bearer <credencial de lectura>`.

Parámetros:

- `entity`: obligatorio; `deal` u `order`.
- `from_msc` y `to_msc`: obligatorios.
- `magic_number`, `limit` y `cursor`: opcionales; `limit` predeterminado `50`.

La respuesta contiene la página en `items`, `next_cursor` y `coverage`, que
separa rangos completos de lotes incompletos. La validez semántica de límites,
rangos, Magic Number y cursores se aplica en la capa de persistencia.

Respuestas principales: `200`, `400 invalid_activity_query`, `401 unauthorized`,
`503 storage_unavailable`.

### `GET /v2/activity-progress`

Devuelve el último heartbeat durable del productor `activity` que incluya progreso
de recuperación. No admite parámetros y requiere la credencial de lectura v2.
La respuesta contiene `activity_progress: null` hasta recibir el primero. Luego
identifica cuenta, fuente, sesión, secuencia y versión del collector, junto con:

- cursores reciente y profundo y atraso entre ambos;
- bloqueo independiente de cada carril;
- avisos de transacciones en cola o descartados;
- antigüedad de la última transacción observada y últimos tickets conocidos.

Es diagnóstico operativo: no demuestra cobertura completa ni modifica cursores.
Respuestas principales: `200`, `400 invalid_query`, `401 unauthorized`, `503
storage_unavailable`.

### `GET /v2/position-cycles`

Consulta ciclos de posición cerrados y reconciliados. Un ciclo agrupa los deals
de una posición por cuenta y `position_id`, desde su apertura hasta el cierre
completo. Es una proyección durable; no es una colección mantenida en memoria.

Parámetros opcionales:

- `owner_magic`: Magic Number propietario atribuido al ciclo.
- `owner_magics`: lista CSV de hasta 12 Magic Numbers, incompatible con
  `owner_magic`; se filtra antes de paginar.
- `from_msc` y `to_msc`: período semiabierto opcional; deben aparecer juntos.
- `closed_only`: `true` limita la consulta a ciclos cerrados.
- `order`: `asc` o `desc`; predeterminado `desc`.
- `include_details`: `false` omite el detalle derivado cuando el consumidor solo
  necesita la identidad y el resultado del ciclo.
- `limit`: tamaño de página; predeterminado `50`.
- `cursor`: cursor opaco devuelto como `next_cursor`.

Cada elemento identifica mensaje, fuente y captura, y contiene:
`account_id`, `position_id`, `owner_magic`, `observed_magics`, período observado,
estado del ciclo, volumen restante, resultado neto observado, tickets de deals,
causas de exclusión y `eligible_for_autonomous_metrics`.

Cada elemento agrega `details`, también expuesto por `/api/position-cycles`:
`side` (long/short o null ante reversión/ambigüedad), `symbol`, `opening_tickets`,
`volume` de entrada, `open_price` y `close_price` ponderados por volumen,
`gross_profit`, `swap`, `commission`, `fee`, `take_profit`, `stop_loss`,
`levels_basis`, `pips` y `duration_hours`. Los costos abarcan todos los deals
comerciales del ciclo, incluidas entradas. El neto conserva los cargos `fee`.
La dirección se identifica por deals de entrada, no por el tipo del cierre.

`levels_basis=exit_order` indica niveles no nulos registrados en una orden de
salida; `initial_order` señala la primera orden de entrada disponible; `unknown`
indica ausencia de evidencia. No se afirma disponer de todas las modificaciones
del TP/SL. Un cierre con niveles cero no prueba que se hayan retirado las
protecciones. `pips` permanece null hasta definir el tamaño del pip por símbolo.
Los datos se calculan sobre el mensaje de reconciliación validado que respalda
el ciclo seleccionado, mediante una consulta acotada a la página. Los filtros se
aplican a la revisión vigente antes de paginar; una observación antigua no reaparece
porque una revisión posterior haya quedado fuera del rango.

Un ciclo con intervención, mezcla de Magics o evidencia insuficiente puede
conservarse para auditoría y quedar excluido de las métricas autónomas.

Respuestas principales: `200`, `400 invalid_position_cycles_query`, `401
unauthorized`, `503 storage_unavailable`.

### `GET /v2/position-cycle-magics`

Devuelve `{"magics": [...]}` con hasta 100 Magic Numbers distintos existentes
en la proyección durable. No admite parámetros y requiere la credencial de
lectura v2.

### `GET /health`

Publica salud acotada del receptor y del almacenamiento sin requerir token. No
incluye filas históricas ni secretos.

## Receptor de telemetría v1

Se conserva durante la transición porque aporta la muestra viva de cuenta al
dashboard. También está limitado a loopback.

### `POST /v1/telemetry`

Recibe mensajes `mt5-telemetry-v1` con `Authorization: Bearer <token del EA>` y
`Content-Type: application/json`. Es idempotente por fuente, sesión, secuencia y
evento. Responde `202` al aceptar y `200` ante una repetición idéntica.

### `GET /v1/snapshot`

Requiere Bearer y un único `source_id`. Devuelve la última muestra de cuenta de
esa fuente. Puede responder `404 snapshot_unavailable`.

### `GET /v1/deals`

Requiere Bearer. Parámetros: `source_id`, `from_msc` y `to_msc` obligatorios;
`magic_number`, `limit` y `cursor` opcionales. Devuelve `deals` y
`next_cursor`. Solo está disponible cuando el receptor usa persistencia.

### `GET /v1/account-history`

Requiere Bearer. Parámetros obligatorios: `source_id`, `from_msc` y `to_msc`.
Lee capturas SQLite existentes de la fuente indicada. El rango máximo es de 366
días; devuelve hasta 480 puntos con la última observación disponible en buckets
de al menos un minuto. No preserva extremos ni rellena huecos, y no modifica la
retención existente.

### `GET /health`

Publica contadores y salud acotada sin token; nunca incluye el último payload.

La descripción histórica y las restricciones completas del collector v1 están
en el [spike de telemetría MT5](mt5-telemetry-collector-spike.md).

## Convenciones comunes

- JSON usa UTF-8 y las respuestas envían `Cache-Control: no-store`, salvo assets
  estáticos del dashboard.
- Los cursores son opacos para el consumidor: no deben fabricarse ni editarse.
- Un `401` indica credencial ausente o inválida; un `403`, identidad autenticada
  sin autorización para la fuente; un `409`, conflicto de idempotencia o
  secuencia.
- `/health` es deliberadamente mínimo y no sustituye una referencia de API.
- Los endpoints de ingesta aceptan escritura solo en el journal de telemetría;
  no ejecutan operaciones de trading.
- Ninguna credencial, cookie o ejemplo de token real debe escribirse en Git.

## Documentos relacionados

- [Contrato de telemetría v2](../architecture/telemetry-v2-contract.md)
- [Persistencia y consultas v2](telemetry-v2-persistence.md)
- [Operación del piloto v2](telemetry-v2-pilot-operation.md)
- [Operación de telemetría v1](telemetry-operation.md)
- [Arquitectura vigente](../architecture/tradinglab-architecture-v2.md)

Esta referencia se actualiza en el mismo cambio que agregue, elimine o altere
una interfaz HTTP. Si en el futuro se incorpora OpenAPI, este documento seguirá
explicando topología, seguridad y uso humano, mientras que la especificación será
la fuente de los esquemas de transporte.

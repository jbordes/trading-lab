# Contrato de telemetría v2 — propuesta

Estado: especificación revisable del ADR-0011, con validador y admisión aislados en
`src/tradinglab/telemetry/contract_v2.py` y
`src/tradinglab/telemetry/admission_v2.py`. El receptor sigue en v1. Los ejemplos
son sintéticos. No enviar estos mensajes al receptor v1 ni usarlos como
configuración.

## Sobre común y autorización

Campos exactos: `schema_version`, `collector_version`, `source_id`, `session_id`,
`sequence`, `event_id`, `captured_at`, `kind`, `payload`.

`schema_version` es `mt5-telemetry-v2`. Se conservan límites v1: UTF-8, máximo
256 KiB, claves únicas, profundidad máxima 6, cadenas hasta 512 caracteres,
identificadores hasta 128, números finitos y rechazo de campos desconocidos.
Tickets y Magic Number se transmiten como texto decimal; tickets sin signo,
Magic con signo dentro de int64. Secuencia es entero 1..int64 máximo, no booleano.
`event_id` debe ser `session_id:sequence` y satisfacer el límite de identificador;
reservar espacio para sufijo al generar la sesión. Una nueva instancia crea
sesión única y secuencia desde uno, sin reutilizar sesiones tras un reinicio.

`captured_at` es UTC ISO con Z, tomado al terminar la lectura; no representa una
instantánea atómica del servidor. `received_at` lo asigna el receptor, no el EA.
Las políticas vigentes de captura futura/desactualizada siguen siendo necesarias.

Registro externo al mensaje: credencial -> fuente -> cuenta interna y rol
(`live` o `activity`). No hay `account_id` ni rol autodeclarado en el sobre.
`payload.identity` contiene exactamente `login_masked`, `server`, `currency`, con
límites v1. Se contrasta con la provisión, pero el login enmascarado no prueba la
identidad. Cada EA conserva guardas de login/servidor/demo antes y después de leer.
Fuentes desconocidas, credenciales de otra fuente o tipos ajenos al rol se rechazan
antes de persistir; no existe registro automático desde tráfico entrante.

## Estado vivo: `live_snapshot` (rol live)

Payload exacto: `reason`, `identity`, `account`, `positions_total`, `orders_total`,
`positions`, `orders`. Reason conserva `startup`, `timer`, `trade_activity`.

Account contiene los seis números v1: `balance`, `equity`, `profit`, `margin`,
`margin_free`, `margin_level` (identidad separada). Posiciones y
órdenes conservan campos, unidades y restricciones de filas v1 definidos en
`src/tradinglab/telemetry/contract.py`; no hay `history`. Totales son enteros no
negativos y las listas tienen tickets únicos y como máximo 1000 filas cada una,
siempre sujetas al límite total de bytes. Lista más corta que el total significa
detalle truncado, no ausencia de las operaciones omitidas. Lista vacía con total
cero sí representa ausencia observada. No inferir cierres por comparar listas.

Solo este mensaje actualiza estado vivo. La proyección exige tiempos admisibles
y conserva la captura más reciente, sin rejuvenecerla por reenvío. Igual timestamp
con contenido distinto no se resuelve por orden de recepción: dentro de una
sesión prevalece secuencia; entre sesiones se conserva el estado previo y se
marca conflicto hasta una observación posterior no ambigua.

## Actividad: `activity_batch` (rol activity)

Payload exacto: `reason`, `identity`, `window`, `deals`, `orders`.
Reason: `startup`, `trade_activity`, `reconcile`, `recovery`,
`position_reconcile`.
Window contiene `from_server_msc`, `to_server_msc`, como enteros decimales en
texto: rango inclusivo, ordenado, máximo 24 horas, tiempo MT5 del broker, no UTC.
Conservar el valor original; no convertir usando un desplazamiento supuesto.

Cada colección contiene exactamente `status`, `total`, `items`:

| status | total | items | Efecto sobre cobertura |
| --- | --- | --- | --- |
| complete | entero >=0, igual a longitud | hasta 200 filas | Confirma el rango solo para esa entidad |
| truncated | entero mayor que longitud | 1..200 filas | No confirma el rango |
| error | null | vacía | Conserva evidencia anterior; no confirma el rango |

Deals conserva todos los campos v1, con `time_msc` dentro de la ventana. Incluye
operaciones monetarias y ejecuciones; no todo deal es un trade. No exige que su
orden esté en el mismo lote: una orden puede tener varias ejecuciones parciales.

Según las [propiedades oficiales MT5](https://www.mql5.com/en/docs/constants/tradingconstants/orderproperties),
órdenes históricas usan exactamente: `ticket`, `magic_number`, `symbol`,
`order_type`, `state`, `volume_initial`, `volume_current`, `price_open`,
`stop_loss`, `take_profit`, `setup_time_msc`, `done_time_msc`, `position_id`,
`position_by_id`, `comment`. Los enum MT5 se conservan numéricos: order_type 0..8,
state 0..9; el collector filtra órdenes ya presentes en historial. Volúmenes
finitos >=0, current <= initial; precios finitos, tiempos decimales >=0,
setup <= done y done dentro de la ventana. Identificadores de posición pueden
ser "0" si no hubo posición. Campos de texto aplican límites v1.

Seleccionar historial y filtrar deals por `time_msc`, órdenes por
`done_time_msc`, sobre el rango inclusivo. Convertir los límites a segundos para
HistorySelect ampliándolos hacia fuera y filtrar luego en milisegundos. Una orden
creada antes del rango y cancelada dentro debe aparecer. La validación en MT5 debe
confirmar la semántica real de selección antes de declarar cobertura completa.
`complete` se refiere al rango y tipo consultados, nunca al historial de toda la
cuenta ni a la coherencia atómica entre las dos colecciones.

`position_reconcile` es la excepción al máximo de 24 horas: representa
la selección completa que MT5 devuelve mediante `HistorySelectByPosition` para
una sola posición, aunque su ciclo dure más. Exige deals y órdenes `complete`,
al menos un deal comercial, volumen comprado y vendido neteado en cero, un único
`position_id` no nulo y la orden inicial cuyo ticket coincide con ese
identificador. Todas las órdenes deben referir la misma posición mediante
`position_id` o `position_by_id`. Este mensaje conserva evidencia durable
del ciclo, pero **no** confirma cobertura de toda la cuenta entre los extremos de
su ventana y por eso no genera un rango en `activity_coverage`.

## Heartbeat y diagnóstico

`heartbeat` está permitido para ambos roles. Payload exacto: `identity`, `status`,
`queued_messages`, `dropped_messages`. Status es `ok` o `degraded`; contadores
enteros no negativos dentro de int64, referidos a la sesión del productor.
Informa conectividad/estado del productor; no actualiza frescura de datos ni
confirma rangos de actividad. La ausencia de heartbeat no prueba que un EA de
trading esté detenido. Cadencia y presentación quedan para la implementación.

## Persistencia, reenvíos y recuperación

- Duplicado idéntico por fuente/sesión/secuencia: confirmar sin nuevo registro.
  Mismo identificador y contenido diferente: conflicto, sin sobrescribir.
- Admitir mensajes históricos fuera de orden: una secuencia baja desconocida
  no es por sí sola un motivo para perder actividad recuperable. El receptor v1
  sí tiene una política distinta; v2 necesitará una implementación explícita.
- Proyección de registros por cuenta + entidad + ticket. Guardar observaciones
  y procedencia. Reobservación posterior puede corregir la fila; un lote antiguo
  recibido tarde no revierte una corrección nueva. Mismo instante ambiguo sigue
  la regla de conflicto del estado vivo; no usar únicamente hora de recepción.
- Confirmar solo después del commit. Cobertura por cuenta/entidad/productor;
  los huecos no se ocultan tomando simplemente el mayor timestamp visto.
- Rango completo vacío confirma que la consulta no devolvió filas. No borrar
  automáticamente filas previamente vistas ni interpretar ausencias como
  tombstones; discrepancias se señalan para reconciliación. Protocolo de borrado
  de registros históricos queda fuera de esta versión propuesta.
- Fallo/truncamiento: reconsultar con solapamiento y rangos más pequeños. Si más
  de 200 registros caen en el mismo milisegundo, subdividir tiempo no alcanza:
  marcar cobertura incompleta. No se promete paginación ni recuperación completa
  de ese caso hasta definir un protocolo adicional de páginas consistente.
- Al reiniciar, recuperar rangos no confirmados desde evidencia durable. El
  mecanismo para transmitir esa cobertura al collector se define en el siguiente
  paso; nunca enviar comandos de trading. Sin cursor durable no se afirma
  recuperación ilimitada tras cortes mayores que la ventana configurada.

La implementación aislada actual autentica antes de parsear y resuelve la cuenta
desde un registro explícito de credencial, fuente, identidad MT5 y rol. Conserva
solo el hash de autorización en su directorio interno. Rechaza cruces de fuente,
rol o identidad y limita a un productor primario por cuenta/rol. Sobre contenido
validado y canonizado, un reintento exacto es duplicado y la reutilización de
fuente/sesión/secuencia con otro contenido es conflicto.

La secuencia es estricta para `live_snapshot` y `heartbeat`: una secuencia menor
desconocida se rechaza. `activity_batch` admite una secuencia menor desconocida
como recuperación fuera de orden sin bajar el máximo observado. Los saltos se
informan como diagnóstico, no como cobertura confirmada. Esta primera admisión
es atómica entre hilos pero acotada en memoria; al desalojar una sesión puede
olvidar duplicados antiguos y no sobrevive reinicios. Por eso todavía no se usa
en HTTP ni constituye idempotencia durable. SQLite deberá aplicar las mismas
reglas dentro de la transacción antes de confirmar al productor.

La [persistencia v2 aislada](../development/telemetry-v2-persistence.md) ya aplica
esas reglas dentro de una transacción SQLite y restaura evidencia verificada tras
reinicios. Permanece opt-in y separada de las bases v1: todavía no existe migración,
provisión operativa ni endpoint v2. La composición de referencia conserva ambos
flujos y sus conflictos sin presentarlos como una captura atómica.

## Composición para dashboard y compatibilidad

Conservar `live` y `activity` independientes, con captura, recepción, cobertura y
error por flujo. Fallo de actividad no bloquea equity; heartbeat no rejuvenece
datos; órdenes canceladas no aumentan cantidad de trades ni P/L. Una ejecución
parcial tampoco define por sí sola un trade cerrado: esa regla corresponde a
las métricas aprobadas por el socio.

No cambiar todavía `/api/state`, SQLite ni parser v1. Versionar y aprobar sus
adaptaciones durante implementación. V1 sigue operativo hasta habilitar v2;
elegir productores primarios explícitos, sin fallback silencioso entre ambos.

## Ejemplos y escenarios para implementación

Los [fixtures propuestos](../../tests/fixtures/telemetry_v2/README.md) permiten
revisar mensajes concretos y los resultados esperados. `parse_envelope_v2` valida
estructura y semántica de un mensaje sin I/O; reutiliza reglas escalares y de filas
v1 sin modificar su parser. Las pruebas cubren fixtures, límites, errores, rechazo
cruzado de versiones, autorización por fuente/rol, duplicados, conflictos y orden.
Las pruebas cubren además persistencia, recuperación durable y composición de
referencia. Migración, proyecciones incrementales, HTTP, collectors y contrato de
vista del dashboard siguen pendientes.

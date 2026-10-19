# Persistencia inicial MT5: mapa CSV → collector → SQLite

**Fecha:** 2026-10-20

**Estado:** pasos 1 y 2A documentales completados; diseño propuesto, sin implementación.

## Alcance y referencia

El usuario acordó comenzar con SQLite y conservar la información utilizada por
el socio en sus planillas. Este documento define el mapa inicial y las preguntas
pendientes; no aprueba fórmulas ni una reconstrucción definitiva de trades.

Referencia: `orders-scalping_1 (2).csv`, ubicado en el Escritorio y fuera de Git.
SHA-256: `71C4BA63794BE17FF3EFB3D2C0D5DC353693E11662C38BEC05B7ECFBD39F09A2`.
La primera línea es `sep=,`; la siguiente contiene 23 columnas.
Se observaron 198 registros: 185 `Closed position`, 2 `Open position`,
7 `Pending order` y 4 `Deposit`. No hubo tickets vacíos ni duplicados de la
combinación Account/Type/Ticket en esta muestra; eso no demuestra una clave
universal válida para MT5.

El `.csv.xlsx` revisado anteriormente contiene otra captura. Sus fórmulas se
describen en [la referencia provisional](workbook-metrics-reference.md).
No asumir igualdad de filas ni convertir sus fórmulas en acuerdos del socio.

## Mapa de las 23 columnas

Los nombres SQLite son conceptuales, no un esquema creado. `trades` representa
una proyección futura derivada de ejecuciones; no una tabla autoritativa de
filas importadas. Una ejecución (deal), una orden y una posición son entidades
distintas. La disponibilidad se contrastó con el fuente actual de
[TradingLabTelemetry](../../apps/mt5-telemetry-collector/TradingLabTelemetry.mq5).

| Columna CSV | Datos del collector actual | Destino lógico y definición pendiente |
|---|---|---|
| Type | Colección positions/orders; history.deals.deal_type y entry | Tipo de entidad y evento; clasificación de la fila derivada. Depósitos separados de trades. |
| Ticket | ticket de posición, orden o deal; position_id y order_id en deals | Identificadores originales como TEXT. Confirmar qué identifica Ticket en cada tipo de fila del CSV. |
| Symbol | symbol | Símbolo exacto del broker; puede estar vacío en movimientos de dinero. |
| Lots | volume; en órdenes es volumen restante | Volúmenes originales y derivados. Definir volumen de un trade con cierres parciales. |
| Buy/sell | operation_type, order_type o deal_type/entry | Dirección derivada según entidad. Una venta puede cerrar una compra; no inferir la dirección del trade solo del deal de salida. |
| Open price | positions/orders.price_open; deals.price | Precio original; reconstrucción del precio de entrada de cerradas pendiente, incluidos múltiples fills. |
| Close price | deals.price de salida | Precio de cierre derivado. price_current de una posición no es precio de cierre. |
| Open time | opened_at_msc, created_at_msc o deals.time_msc de entrada | Hora de presentación derivada del instante original; zona del servidor por validar. |
| Close time | deals.time_msc de salida | Hora derivada; nula para posiciones abiertas y pendientes. |
| Open date | Misma marca temporal que Open time | Fecha derivada; evitar almacenar fecha y hora como verdades independientes. |
| Close date | Misma marca temporal que Close time | Fecha derivada; criterio de cierre parcial pendiente. |
| Profit | deals.profit; positions.profit flotante | Realizado separado del flotante; agregar deals solo con reglas de trade aprobadas. |
| Swap | deals.swap; positions.swap | Costes históricos separados del snapshot abierto; evitar sumarlos dos veces. |
| Commission | deals.commission | Conservar por ejecución, incluidas entradas; no está en snapshots de posiciones. |
| Net profit | No es campo directo; existen profit, swap, commission y fee | Cálculo versionado. El Excel anterior suma profit+swap+commission; conservar fee separado y acordar su inclusión sin duplicar costes. |
| T/P | take_profit en posiciones/órdenes actuales | Valores observados. No se conserva actualmente el historial de órdenes ni el TP definitivo de cerradas que no observamos abiertas. |
| S/L | stop_loss en posiciones/órdenes actuales | Igual limitación histórica que T/P; distinguir configuración inicial, última observada y efectiva al cierre. |
| Pips | No disponible | Derivado pendiente de convención por símbolo y dirección. No asumir que pip equivale a point, especialmente en XAUUSD. |
| Result | No disponible | Confirmar significado y unidad con el socio; no inferirlos del título. |
| Trade duration (hours) | Marcas temporales de entradas y salidas | Duración derivada; definir inicio/final ante parciales y reversión. |
| Magic number | magic_number en posiciones, órdenes y deals | TEXT; agrupación por bot dentro del contexto de cuenta. No es clave de operación ni asignación de capital. |
| Order comment | comment en posiciones/órdenes, truncado a 256 caracteres | No se envía comentario en deals ni historial de órdenes. Ampliar captura si se requiere recuperar comentarios de cerradas tras cortes. |
| Account | source_id, login_masked, server y currency | Identidad interna estable de cuenta ligada explícitamente a la fuente; cuenta enmascarada solo para mostrar. No usarla como clave única. |

## Datos técnicos adicionales necesarios

- Conservar payload validado, versión del contrato, source_id, session_id,
  sequence, instante de captura y recepción. Las muestras de equity/balance
  pertenecen a la cuenta; no asignarlas automáticamente a cada Magic Number.
- Mantener IDs como texto y signos de costes; distinguir NULL/desconocido de cero.
  Proponer cálculo decimal explícito para precios/importes, sin asumir siempre
  dos decimales. El collector actual serializa números con ocho decimales: guardar
  su representación no recupera precisión que ya se haya perdido en origen.
- Conservar tiempos operativos crudos y su escala. No etiquetar como UTC los
  tiempos de servidor sin validar su conversión y los cambios estacionales.
- Registrar cobertura y truncamiento: una muestra parcial no permite concluir
  que una posición desaparecida se cerró ni que se recuperó todo un período.

## Persistencia e idempotencia propuestas

Separar observaciones recibidas, entidades MT5 y proyecciones de análisis.
El esquema mínimo y las migraciones se definen en el paso 2.

1. Un mensaje se identifica por source_id + session_id + sequence. Un reenvío
   idéntico no añade filas; contenido diferente con la misma identidad se rechaza.
2. Una ejecución se identifica por identidad interna de cuenta + deal ticket.
   Los tickets de órdenes y los identificadores de posiciones tienen ámbitos
   separados. El source_id no es por sí solo una clave histórica de operación.
3. Una relectura idéntica es idempotente. Cambios de valores de una entidad ya
   conocida deben conservar evidencia de revisión; no sobrescribir silenciosamente
   los datos que sustentaron un cálculo previo.
4. Confirmar recepción durable solo después del commit en SQLite. Guardar en
   transacción el lote y el avance recuperable. Si falla el guardado, no confirmar
   éxito ni avanzar la cobertura. Una caída después del commit admite reenvío.
5. Los snapshots actuales pueden actualizar una vista de estado; las observaciones
   históricas retenidas conservan su fecha. No convertir cada snapshot en un trade.

## Recuperación y límites actuales

La propuesta es releer intervalos solapados, deduplicar por IDs y marcar cobertura
completa solo cuando cada tramo se haya leído y guardado sin truncamiento.
Debe existir una reconciliación periódica para detectar diferencias tardías;
frecuencia y alcance quedan pendientes.

El collector actual relee una hora y hasta 200 deals por muestra, con una cola
volátil de 12 mensajes. Es insuficiente para recuperar caídas arbitrariamente
largas. Antes de implementar backfill hay que diseñar la consulta histórica por
tramos, su presupuesto de trabajo y su progreso durable. No agregar comandos de
trading ni asumir un canal remoto de control del EA para resolverlo.

El historial disponible en MT5 puede permitir reconstruir ejecuciones anteriores;
la cobertura depende también de lo que conserve el broker. Equity y flotante no
observados quedan como huecos, nunca como ceros ni valores interpolados reales.
Almacenar datos en el receptor tampoco garantiza captura cuando ese receptor
está apagado: hace falta definir cuánto tolera el piloto en esa situación.

## Propuestas operativas aún por acordar

- Mantener captura cada cinco segundos para el piloto; no garantiza detectar
  todos los máximos/mínimos intraperíodo. Acordar precisión necesaria de drawdown.
- Sin borrado automático inicial de operaciones/costes; medir uso de disco.
  Decidir retención de snapshots y copias de seguridad antes de operación continua.
- Servidores de pruebas apagados por decisión del usuario. Iniciar una instancia
  de recolección deliberadamente cuando se quiera almacenar; no arrancarla desde
  esta tarea documental ni vincular su vida a que el navegador esté abierto.

## Paso 2A — Esquema mínimo propuesto

Primer corte: guardar mensajes validados de forma durable, conservando todos sus
campos actuales. Tres tablas son suficientes para ese alcance. No crear todavía
una tabla de trades cerrados ni transformar cada fila del CSV en un deal.

| Tabla | Campos y tipos propuestos | Claves y propósito |
|---|---|---|
| `accounts` | `account_id TEXT`, `label TEXT`, `server TEXT`, `currency TEXT`, `created_at_utc TEXT` | PK `account_id`, identificador interno opaco. Contexto de cuenta sin login completo ni credenciales. Label, servidor y moneda no forman una clave única. |
| `sources` | `source_id TEXT`, `account_id TEXT`, `created_at_utc TEXT` | PK `source_id`; FK a `accounts.account_id`. Asociación explícita e inmutable de fuente a cuenta. |
| `telemetry_messages` | `message_id INTEGER`, `source_id TEXT`, `session_id TEXT`, `sequence TEXT`, `captured_at_utc TEXT`, `received_at_utc TEXT`, `schema_version TEXT`, `collector_version TEXT`, `payload_json TEXT`, `content_sha256 TEXT` | PK `message_id`; FK a `sources.source_id`; UNIQUE `(source_id, session_id, sequence)`. Conserva el mensaje completo validado, incluidas posiciones, órdenes, deals y cobertura. |

Reglas del esquema:

- Todos los campos anteriores son obligatorios. Validar formatos, longitudes,
  versión y límites de tamaño antes de insertar; definir las restricciones SQL
  concretas y activar integridad referencial en cada conexión durante el paso 2B.
- `sequence` se propone como texto decimal canónico porque procede de un contador
  unsigned de MQL5. No depender del límite signed de INTEGER de SQLite ni ordenar
  secuencias numéricamente mediante orden lexicográfico. Los tickets y Magic
  Numbers conservan su representación textual en el mensaje.
- Las fechas UTC técnicas usan un formato único validado. Los tiempos de deals
  del servidor permanecen crudos dentro del payload hasta resolver su conversión.
  `message_id` indica orden de inserción, no orden de operaciones ni de captura.
- Índice inicial de consulta: `(source_id, captured_at_utc, message_id)`.
  La restricción UNIQUE ya cubre la búsqueda de reenvíos por identidad de mensaje.
- `payload_json` conserva el sobre completo validado. El hash se calcula sobre una
  representación canónica de ese contenido; excluye la hora local de recepción.
  Los campos duplicados en columnas se extraen del mismo sobre, no de entradas
  independientes. Un duplicado idéntico no reemplaza la recepción original.
- Un source desconocido se rechaza hasta registrarlo explícitamente. Si cambia
  de cuenta, requiere otro source_id. Varias fuentes aprobadas pueden referenciar
  la misma cuenta, pero no autorizan ejecución concurrente duplicada del collector.
  La identidad no se deduce comparando cuentas enmascaradas. La provisión segura
  del mapping debe definirse en 2B; no registrar cuentas automáticamente del payload.
- El journal es inmutable para la ingesta: nuevos snapshots son nuevas
  observaciones. Correcciones recibidas posteriormente conservan ambas evidencias;
  la política para actualizar una proyección de deals se define después.
- SQLite vivirá bajo `_storage/`, fuera de Git. El primer corte no necesita
  tablas de usuarios, métricas, credenciales ni trabajos de ejecución de EAs.

Este diseño evita perder los campos actuales al reiniciar, pero no agrega los
campos históricos que faltan ni resuelve por sí solo recuperación y retención.
Duplicar snapshots completos puede consumir espacio: medirlo en el piloto y
acordar el plazo de retención antes de dejar captura continua prolongada.

Después se podrán crear proyecciones consultables de ejecuciones y valores de
cuenta a partir de estos mensajes, manteniendo su procedencia. Una tabla futura
de deals usará `(account_id, deal_ticket)` como identidad; la proyección de trades
esperará las reglas de cierres parciales. No hace falta aprobar esas reglas para
guardar las observaciones actuales.

## TODO para retomar: pasos cerrables

- [x] Paso 1: mapa de las 23 columnas, disponibilidad actual, límites y preguntas.
- [x] Paso 2A: propuesta mínima de tablas, claves, relaciones y límites del alcance.
- [ ] Paso 2B: acordar el esquema; definir provisión de identidad, restricciones SQL,
  transacción y confirmación durable, recuperación del proceso, tratamiento de
  revisiones en proyecciones, retención y backup. Separar aceptado de propuesto.
- [ ] Paso 3: implementar guardado durable de mensajes actuales, con pruebas de
  duplicado, conflicto, caída antes/después del commit y reinicio. Esto todavía
  no equivale a historial completo ni a reconstrucción de trades.
- [ ] Paso 4: ampliar captura de campos faltantes y recuperación histórica por
  tramos, probando truncamiento, cortes y revisión tardía.
- [ ] Paso 5: reconstrucción de trades y proyección compatible con las 23 columnas,
  después de resolver las reglas del socio. Validar con casos anonimizados.

Preguntas del socio: qué representa Ticket y Result; unidad de Pips; cierres
parciales, múltiples fills y reversión; costes/fee y depósitos; SL/TP y comentario
históricos deseados; inicio de día, zona horaria y precisión de observación.
La selección de operaciones para métricas y capital de referencia siguen en la
[guía de métricas](guia-metricas-para-el-socio.md).

Retomar por el paso 2B. Esta rama solo contiene documentación de diseño: no crea
base de datos, no cambia el collector ni configura terminales. Integración por PR
y merge humano; ninguna publicación directa a main forma parte de este paso.

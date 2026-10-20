# Persistencia inicial MT5: mapa CSV → collector → SQLite

**Fecha:** 2026-10-20

**Estado:** creación, apertura validada, registro, guardado y lectura aislada implementados.
La integración con el receptor y la activación operativa siguen pendientes.

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
  El esquema v1 mantiene el límite actual del contrato: 1 a 2^63−1, aunque
  MQL5 use un contador unsigned. Ampliarlo requiere cambiar y probar el contrato.
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

## Paso 2B.1 — Confirmación durable y reenvíos

Diseño propuesto para implementar y verificar en el paso 3. El receptor actual
confirma contra un buffer en memoria; esta sección no implica que ya persista.

Unidad de guardado: un sobre validado completo por transacción. Autenticar,
validar contrato y comprobar la fuente registrada antes de aceptar el mensaje.
La base, no la caché en memoria, determina si su identidad ya fue guardada.

| Situación | Guardado y respuesta previstos |
|---|---|
| Identidad nueva admitida | Insertar el sobre y confirmar éxito solo después de completar el commit. |
| Misma identidad y contenido canónico idéntico | Confirmar como duplicado ya guardado, sin otra fila ni cambio de la recepción original. |
| Misma identidad con contenido diferente | Rechazar como conflicto; conservar el original sin reemplazarlo. |
| Fallo de escritura o base temporalmente ocupada | No confirmar éxito; revertir la transacción si sigue activa y devolver un error controlado. Reintento acotado, sin espera infinita. |
| Caída antes del commit | No prometer guardado; el reenvío vuelve a intentar la inserción. |
| Caída después del commit, antes de entregar la respuesta | El reenvío encuentra el mensaje durable y se confirma como duplicado. |

La restricción UNIQUE debe resolver también dos solicitudes concurrentes con la
misma identidad. Tras un choque, comparar el contenido guardado: no usar un
«ignorar si existe» que oculte conflictos. El hash ayuda a comparar, pero conservar
el contenido canónico para verificar igualdad.

Comprobar duplicados durables antes de rechazar por secuencia antigua: un mensaje
ya confirmado debe poder reenviarse aunque haya mensajes posteriores. El bloque
3C rechaza secuencias antiguas desconocidas dentro de una misma fuente/sesión;
el backfill necesitará un camino explícito, sin relajar la protección contra replay.
Un salto de secuencia se registra como hueco,
no como evidencia de operaciones inexistentes ni de cobertura completa.

La respuesta de éxito conserva compatibilidad con el collector (actualmente
200 para duplicados y 202 para nuevos), pero en el futuro camino persistente
ambas exigirán evidencia de guardado. Si el commit tiene resultado incierto,
no inventar éxito: resolver consultando por identidad al reintentar. Una avería
de SQLite nunca habilita un fallback silencioso que confirme solo en memoria.

Las vistas en memoria se actualizan desde datos confirmados y deben poder
reconstruirse tras reiniciar. Su fallo no revierte un mensaje ya confirmado ni
justifica marcar datos antiguos como recientes. El primer corte no añade cursor
de backfill: el sobre conserva la cobertura declarada. Si luego se introduce un
cursor durable, su avance y los datos asociados se guardarán juntos.

Antes de implementar, concretar configuración de durabilidad SQLite, tiempos de
espera, recuperación de vistas, contrato de errores y pruebas con reinicios.
Este diseño cubre reenvíos de mensajes disponibles, no pérdida del disco ni
mensajes que desaparecieron de la cola volátil del collector. La deduplicación
se garantiza mientras se conserve su registro; la retención deberá preservar
esa garantía o definir explícitamente su ventana.

## Paso 2B.2 — Registro de cuentas y fuentes

Separación acordada: una terminal puede tener varias cuentas configuradas y
alternar entre ellas. No confundir terminal, cuenta y sesión de captura. El
collector observa la cuenta activa; no captura simultáneamente todas las cuentas
guardadas en esa terminal.

- `account_id`: identidad interna opaca y estable de una cuenta de trading,
  independiente de la terminal. No derivarla de un login enmascarado, alias,
  moneda ni Magic Number. La verificación humana considera login completo y
  servidor dentro de MT5, sin copiar el login completo a Git ni al registro de mensajes.
- `source_id`: asociación explícita de una instalación del collector en una
  terminal con una cuenta. Su vínculo con `account_id` no se reasigna. La misma
  terminal usa fuentes diferentes para cuentas diferentes; una cuenta observada
  desde otra terminal también requiere otra fuente asociada al mismo account_id.
- `session_id`: una ejecución del collector. Al reiniciarlo se crea una sesión
  nueva, sin crear otra cuenta ni reutilizar la identidad de mensajes anteriores.

Ejemplo ficticio: `terminal-pruebas-a` y `terminal-pruebas-b` son dos fuentes
de la misma terminal para cuentas diferentes. Volver a la cuenta A permite
reutilizar `terminal-pruebas-a`, con nueva sesión. No hace falta una tabla de
terminales en este corte; esta asociación se registra en el inventario operativo
local. El nombre de la fuente no sustituye la comprobación de identidad.

Procedimiento de alta con API local y comando de primera provisión:

1. El operador verifica en la terminal de pruebas la cuenta demo activa y su
   servidor. Determina si ya existe una cuenta registrada; nunca fusionar cuentas
   automáticamente por coincidencia de metadatos parciales.
2. Crear o seleccionar el account_id y registrar su alias, servidor y moneda en
   SQLite. Registrar el source_id con su cuenta, antes de admitir sus mensajes.
   Un alta repetida idéntica es idempotente; un vínculo distinto se rechaza.
3. Configurar localmente SourceId y la guarda de login/servidor esperados del
   collector. Mantener credenciales y tokens fuera de SQLite y Git. La asociación
   local de fuentes autorizadas se configura explícitamente, no desde el payload.
4. Verificar la primera muestra contra la fuente registrada y los metadatos
   esperados. Una discrepancia de servidor o moneda bloquea la admisión y requiere
   revisión; no modifica automáticamente la cuenta. Los metadatos concordantes
   son una comprobación adicional, no una prueba suficiente de identidad.

Para alternar de A a B, detener explícitamente el collector de pruebas, cambiar
la cuenta en MT5 y reconfigurar su fuente y guarda antes de reiniciarlo. No
reenviar mensajes de A etiquetados como B ni transferir la cola entre fuentes.
La cola actual es volátil: si quedan mensajes al detenerlo, señalar posible
pérdida y reconciliar posteriormente; no prometer continuidad histórica.
No tocar terminales de terceros para ejecutar este procedimiento.

La guarda actual detiene el collector si la cuenta deja de coincidir con la demo
aprobada. Se conserva: no habrá detección ni cambio automático de identidad en
este primer corte. La protección completa requiere además vincular autenticación
con fuentes permitidas en el receptor; un token compartido no demuestra qué
terminal emitió un mensaje. Ese control sigue pendiente de implementación.

No activar dos collectors concurrentes para la misma cuenta en el piloto. Un
traslado requiere detener el anterior y aprobar la nueva fuente; las observaciones
históricas mantienen su procedencia. La deduplicación futura de deals por cuenta
no elimina automáticamente snapshots duplicados de dos fuentes.

Pruebas previstas: fuente desconocida, alta repetida, intento de reasignación,
metadatos incompatibles, alternancia A → B → A sin mezcla, nueva sesión, fuente
no autorizada para el token y cuenta compartida entre terminales sin alta automática.

## Estado de recepción — definición acordada para el piloto

Acordado el 2026-10-20; pendiente de implementación. Para el intervalo actual
de cinco segundos, evaluar por fuente el tiempo desde la recepción de la última
muestra nueva válida, no desde la última consulta del navegador:

| Estado | Tiempo transcurrido |
|---|---|
| Actualizado | Menos de 20 segundos |
| Demorado | Desde 20 hasta 60 segundos, inclusive |
| Sin recepción | Más de 60 segundos |
| Sin datos todavía | Nunca se recibió una muestra válida de esa fuente |

Son umbrales iniciales ajustables; revisarlos si cambia el intervalo de captura.
La etiqueta «Actualizado» describe la recepción, no garantiza por sí sola la
actualidad de todos los datos ni la integridad del historial.

- Un reenvío duplicado o mensaje inválido no reinicia el contador. La consulta
  del dashboard tampoco convierte una observación antigua en una nueva.
- Conservar los últimos datos válidos junto a su hora y advertencia de antigüedad;
  nunca reemplazarlos por cero por falta de recepción. Sin muestra previa, mostrar
  ausencia de datos, no valores ficticios.
- Separar recepción del collector, antigüedad de captura, cobertura histórica,
  conexión MT5-broker y acceso navegador-backend. Recibir una cola atrasada no
  vuelve recientes sus capturas. Si el navegador pierde contacto con el backend,
  indicar que no puede verificar la recepción, sin atribuir el fallo al collector.
- Mercado cerrado o ausencia de operaciones no significan fallo del collector:
  puede seguir enviando muestras válidas sin cambios en las operaciones.
- En ejecución, medir intervalos con reloj monotónico; conservar fechas UTC para
  mostrar y recuperar el estado tras reinicio. No marcar datos restaurados como
  recién recibidos ni presentar una edad negativa como recepción saludable.
- Mostrar este diagnóstico de forma compacta, con detalles accesibles, sin
  desplazar el análisis de trading ni depender exclusivamente del color.

La UI actual usa umbrales de dos y diez intervalos de consulta y combina algunas
señales de conexión. Esta definición es el comportamiento objetivo para telemetry,
no una descripción de lo ya implementado ni un cambio del adaptador Python.

## TODO para retomar: pasos cerrables

### Bloque implementado: creación del esquema v1

`src/tradinglab/telemetry/sqlite_store.py` expone `create_database(Path)` para una
ruta nueva `.sqlite3` cuyo directorio ya exista. No hay CLI ni conexión al receptor.
En operación la ruta deberá estar bajo `_storage/`; las pruebas usan directorios
temporales. La función no descubre terminales, no recibe credenciales y no crea
directorios ni reemplaza archivos existentes. Si falla la creación, puede quedar
un archivo reservado: revisar manualmente, nunca borrarlo o migrarlo automáticamente.

Implementa las tres tablas STRICT, versión de esquema 1, claves foráneas,
unicidad de mensajes, índice de captura y prohibición de reasignar una fuente.
Las restricciones SQL comprueban tipos y límites básicos; fechas, identificadores,
contenido completo del payload y correspondencia con su hash requerirán validación
en la API de almacenamiento. No escribir datos de producto mediante SQL directo.

### Bloque implementado: apertura y registro local (3B)

`open_registry(Path)` abre únicamente una base existente y devuelve un registro
limitado al contexto `with`. Activa claves foráneas y synchronous FULL por conexión,
comprueba versión 1, esquema exacto (incluido el trigger de protección), integridad
básica y relaciones. Rechaza diferencias sin migrar ni reparar. La espera por bloqueo
se limita a cinco segundos. Usar un contexto por hilo; no compartir conexiones.

`register_account` y `register_source` validan sus entradas y guardan cada alta en
una transacción. Devuelven True para un alta nueva y False para una repetición
idéntica; preservan la fecha inicial. Metadatos diferentes para el mismo account_id
o reasignar un source_id generan conflicto explícito. Una fuente requiere cuenta
previamente registrada; no crea cuentas implícitamente. La fecha es un datetime
con zona provisto por el llamador, normalizado a UTC.

El esquema exacto evita aceptar bases con guardas eliminadas: una evolución futura
necesitará migración explícita. La comprobación de integridad se realiza al abrir,
no por mensaje; evaluar su coste cuando crezca el histórico. Los archivos y su
directorio deben estar bajo control del operador; no es un lector de bases SQLite
arbitrarias de terceros ni verifica la cuenta real conectada en MT5.

El registro no autoriza por token ni realiza alta operativa de cuentas reales. La API no
acepta credenciales. Tampoco fusiona cuentas con metadatos similares. El receptor
sigue usando memoria.

### Bloque implementado: mensajes durables aislados (3C)

`store_message(body: bytes, received_at: datetime)` valida el contrato existente,
exige fuente registrada y verifica servidor/moneda para snapshots. Guarda el sobre
canónico completo y su SHA-256 en una transacción; solo devuelve resultado después
del commit. Los mensajes heartbeat se conservan como tales, sin representar una
nueva captura de cuenta. El caller deberá autenticar y autorizar la fuente antes
de llamar esta API; registrar una fuente no autentica al emisor.

Un duplicado idéntico devuelve el mismo message_id y no actualiza la fecha de
recepción. Contenido diferente con igual identidad produce conflicto. Se comprueba
el duplicado antes de rechazar secuencias antiguas; las secuencias se comparan
numéricamente, aunque se guarden como texto. Se permite una nueva sesión sin mezclar
su contador con otras sesiones o fuentes. La autorización de sesiones antiguas
queda para la integración; este componente no es una protección completa de replay.

El resultado distingue inserción, duplicado y salto de secuencia en una inserción.
Un duplicado devuelve sequence_gap=False porque no agrega un hueco nuevo; no afirma
que la sesión carezca de huecos. Las secuencias conservadas permiten reconstruir
discontinuidades, pero no garantizan cobertura histórica. Las fechas técnicas en
columnas se normalizan a UTC con microsegundos, sin modificar el sobre original.

Pruebas en bases temporales cubren reenvío tras reapertura, conflictos, inputs
inválidos, identidad, límites de secuencia, fuentes/sesiones, concurrencia y fallos
inyectados antes/después del commit. No equivalen a pruebas de corte eléctrico o
muerte abrupta de proceso. No se cambia el protocolo HTTP ni se habilita captura.
### Bloque implementado: último snapshot persistido por fuente (3D)

`latest_account_snapshot(source_id)` devuelve como máximo un snapshot para una
fuente registrada, o `None` cuando aún no tiene capturas. Omite heartbeats y usa
la fecha de captura más reciente; ante empate, el orden de inserción. Así una
muestra atrasada entregada después no desplaza una captura más nueva. Las fuentes
se consultan por separado; no hay fallback hacia otra terminal.

El resultado incluye el sobre original validado, su hora de recepción original y
su `message_id`. La lectura comprueba hash y coherencia de las columnas con el
sobre. Un dato alterado causa un error explícito. No actualiza fechas, contadores
ni marcas de conexión. El consumidor futuro deberá calcular antigüedad con su
reloj, mostrar claramente que la observación fue recuperada y tratar una fecha
de captura futura como anomalía, no como frescura.

La consulta devuelve una sola observación; no reconstruye una ventana de equity,
historial completo ni estado operativo del collector. Continúa aislada del HTTP.

### Bloque implementado: vista en memoria sincronizada (3E)

`PersistedSnapshotView` mantiene una vista por `source_id`. Al crearse carga el
último snapshot confirmado desde SQLite. Después de guardar un mensaje, recarga
esa fuente antes de devolver éxito. También permite `refresh()` si otro proceso
escribió en la base. `snapshot()` devuelve una copia independiente con la hora de
captura y la hora original de recepción; repetir un mensaje o guardar un heartbeat
no actualiza esas horas. La vista no genera contadores de capturas ni afirma que
el collector esté conectado: ese diagnóstico deberá provenir del receptor activo.

Si SQLite confirmó el mensaje pero falla la recarga, la vista deja de estar lista
para lectura y la operación informa error. Un reenvío idéntico consulta el mensaje
durable, lo reconoce como duplicado y puede recuperar la vista. No sustituir esta
vista por una llamada a `TelemetryBuffer.accept`: eso volvería a contar una
observación restaurada como si acabara de llegar.

Esta clase utiliza la conexión del registro en un solo hilo y todavía no atiende
HTTP. Pruebas cubren reinicio, fuente equivocada, replay, heartbeat, cola atrasada,
copia independiente y fallo de recarga tras un commit. Próximo bloque: definir la
integración segura del receptor, con autenticación ligada a fuentes, errores HTTP
y acceso concurrente a SQLite. Resolver retención y backups antes de operación
continua.

### Bloque implementado: receptor y supervisor con SQLite opcional (3F)

El receptor acepta `--sqlite-db` junto con `--source-id`. Exige una base ya creada
bajo `_storage/` y la fuente registrada antes de abrir el puerto. En este modo,
el token autoriza solamente esa fuente. SQLite confirma el mensaje antes del HTTP
202; los reenvíos idénticos reciben HTTP 200. Una fuente distinta recibe 403 y
los conflictos/secuencias viejas 409. Los fallos de almacenamiento reciben 503.
El snapshot recuperado conserva su fecha original. `/health` incluye
`storage=sqlite`; sus contadores miden este proceso, no el archivo histórico.

`scripts/start_telemetry.py --source-id <fuente> --sqlite-db <ruta>` transmite base y fuente al hijo
receptor dentro de la supervisión del PR #18. Sin esa opción, el receptor mantiene
su buffer volátil. El archivo debe estar bajo `_storage/` del checkout que se
arranca; este paso no crea una base operativa ni configura terminales. Pruebas HTTP
locales verifican commit, reenvío, reinicio, aislamiento de fuentes y concurrencia.

La conexión compartida entre hilos se usa bajo un bloqueo del backend. Falta
aprobar backup/retención antes de encender este modo en la terminal demo.

### Bloque implementado: primera provisión local (3G)

`scripts/provision_telemetry_db.py` muestra una vista previa por defecto. Con
`--apply`, crea exclusivamente un archivo nuevo `.sqlite3` bajo `_storage/` y
registra el `account_id` interno y el `source_id` proporcionados. Valida nombres,
campos y ruta antes de escribir; si la base existe, falla sin modificarla. Nunca
lee el login completo, credenciales o tokens. La verificación de cuenta demo,
servidor y moneda dentro de MT5 corresponde al operador antes de aplicar.

Una falla inesperada después de crear el archivo puede dejar una base parcial:
revisarla manualmente, sin borrado ni reintento automático. Este paso no activa
captura ni define aún frecuencia de backups o retención. El siguiente gate es
acordar esas políticas y probar una sesión breve con la terminal de pruebas.

- [x] Paso 1: mapa de las 23 columnas, disponibilidad actual, límites y preguntas.
- [x] Paso 2A: propuesta mínima de tablas, claves, relaciones y límites del alcance.
- [x] Definición breve: estados y umbrales de recepción por fuente acordados.
- [ ] Implementar esos estados separando recepción, antigüedad y conectividad;
  probar límites de 20/60 segundos, duplicados, cola atrasada, reinicio y pérdida
  de acceso al backend. Validación visual manual por el usuario.
- [x] Paso 2B.1: propuesta de transacción, confirmación durable y reenvíos.
- [x] Paso 2B.2: separación de terminal/cuenta/fuente y procedimiento de alta propuesto.
- [x] Paso 3A: creación aislada del esquema v1 y pruebas en bases temporales.
- [x] Paso 3B: apertura validada y API de registro idempotente de cuentas/fuentes.
- [x] Paso 3C: guardado aislado de mensajes, deduplicación y fallos de commit simulados.
- [x] Paso 3D: lectura del último snapshot por fuente con procedencia y fechas originales.
- [x] Paso 3E: vista en memoria sincronizada con mensajes confirmados y recuperada al inicio.
- [x] Paso 3F: receptor HTTP y supervisor con SQLite opcional, fuente única y pruebas locales.
- [x] Paso 3G: comando de primera provisión con vista previa y creación explícita.
- [ ] Resto del paso 2B: acordar el esquema; concretar el mecanismo de alta local
  y autorización por fuente, durabilidad y errores de la integración, admisión de
  sesiones antiguas, recuperación de vistas, revisiones en proyecciones, retención y backup.
  Separar aceptado de propuesto.
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

Retomar por backup/retención y prueba operativa acotada. No se creó una
base operativa ni se cambió el collector o las terminales. Integración por PR y
merge humano; ninguna publicación directa a main forma parte de este paso.

Mejora separada del harness pendiente: permitir cerrar cambios exclusivamente
documentales con validaciones de documentos, enlaces, secretos y política de
sesiones, sin ejecutar tests de producto. Hasta cambiar la regla vigente, mantener
la validación full al cierre; no mezclar esa modificación con la persistencia.

# Revisión de diseño y rendimiento de Python y collectors

**Fecha:** 2026-11-05

**Estado:** revisión estática de Python ampliada por bloques; hallazgos abiertos
y correcciones previas diferenciados. No certifica ausencia de bugs. La revisión
MQL5 sigue siendo inicial. Incluye mediciones sintéticas y reproducciones
aisladas; las pruebas del flujo integrado y de la API remota siguen pendientes.

**Alcance:** Python en `src/`, `scripts/` y `tests/`; MQL5 solo para los dos
collectors del repositorio y sus includes.

**Base revisada:** `6d697fc`, rama
`chore/python-design-collector-performance-review`.
La ampliación Python revisa `b104525` y los cambios locales de PY04/PY07, incluidos
el benchmark y sus pruebas. PY08–PY16 tienen implementación y pruebas dirigidas
en esta rama; CI, merge humano y validación operativa integrada siguen pendientes.
**Guías consultadas:** `_storage/python_performance_guide.md` y
`_storage/mql5_performance_guide.md`; se leyeron como referencias, sin copiarlas
a Git ni convertir sus recomendaciones en obligaciones universales. En MQL5,
esta revisión se limita a rendimiento; no abre otro refactor general de diseño.

## Criterio

Se revisaron persistencia, receptores, ingesta, relay, dashboard, métricas,
configuración y herramientas operativas, además del harness. Los dos collectors
MQL5 conservan su revisión inicial. Los efectos confirmados describen el flujo
visible en código y las reproducciones indicadas; no se atribuyen impactos
cuantitativos de producción sin mediciones representativas.

Aplicar estructuras proporcionales al tamaño, scans e I/O acotados, memoria
limitada, paginación y trabajo incremental. No recomendar `pandas`, `numpy`,
Numba, cachés ni concurrencia por defecto. Preservar precisión con `Decimal`,
validación externa, idempotencia y ACK posterior al commit. SOLID, DRY y YAGNI
son criterios pragmáticos: no proponer interfaces por clase ni capas sin
necesidad demostrada. Se indica por hallazgo qué correcciones y pruebas están
realizadas. El alcance no incluye instalaciones, tests nativos ni mediciones
contra la API/SQLite remotas.

## Hallazgos Python

### PY01 — El inicio reconstruía evidencia histórica completa

- **Prioridad:** alta. **Ubicación:** `persistent_receiver_v2.py:44`,
  `sqlite_store_v2.py:1035`.
- **Estado:** corrección del arranque implementada; CI y merge humano pendientes.
- **Hallazgo de base:** la evidencia de cuenta/fuentes se reconstruía leyendo
  mensajes históricos, con trabajo y memoria proporcionales al historial. La
  ubicación describe el diseño previo; latencia no medida.
- **Cambio:** `account_registration` ahora lee `accounts` y `sources` en una
  transacción mediante DTO inmutable, sin recorrer historial. La consulta
  explícita `account_evidence` sigue verificando hashes y materializando la
  historia; streaming/paginación de esa auditoría queda como propuesta futura,
  no implementada. Esto no afirma que el arranque deje de leer el snapshot actual.
- **Evidencia dirigida:** 51 casos correctos en
  `test_telemetry_v2_sqlite`, `test_central_api` y
  `test_telemetry_v2_persistent_http`: arranque con lecturas de mensajes
  prohibidas por SQLite, con 0 y 128 registros; cuenta/fuentes y autorización
  preservadas, y hash corrupto aún rechazado por auditoría. `fast` correcto.

### PY02 — Lecturas de actividad compartían lock con el ingreso

- **Prioridad:** alta. **Ubicación:** `persistent_receiver_v2.py`, rutas
  `activity_history` y `position_cycles`.
- **Estado:** implementado; CI y merge humano pendientes.
- **Hallazgo de base:** las rutas compartían `RLock` con accept/state, por lo que
  una consulta podía retrasar ingreso/health. Esta contención en memoria se ha
  eliminado; no se promete eliminar toda contención interna de SQLite.
- **Cambio:** `activity_history`, `position_cycles`, `activity_progress` y
  `position_cycle_magics` usan lectores SQLite independientes `mode=ro` y
  `query_only`. La página y su coverage comparten una transacción snapshot por
  solicitud, no un snapshot global entre páginas. Se admiten como máximo dos
  lecturas concurrentes; admisión sin espera. Presupuesto cooperativo de 2 s,
  progreso SQL cada 1000 operaciones con chequeos antes/después del procesamiento
  Python y espera de locks SQLite de hasta 0.1 s. El código Python no se
  interrumpe instantáneamente ni ofrece límite de tiempo real.
- **Saturación/fallo:** se devuelve `V2StorageError` y HTTP 503
  `storage_unavailable` según el contrato existente, nunca una respuesta parcial.
  Cada lector cierra conexión y libera cupo incluso ante fallos; lectores ya
  admitidos pueden terminar al cerrar el receptor y nuevas consultas se rechazan.
  El ingreso conserva escritura atómica y ACK tras commit.
- **Evidencia dirigida:** 59 pruebas en `test_telemetry_v2_readers`,
  `test_telemetry_v2_sqlite`, `test_central_api` y
  `test_telemetry_v2_persistent_http`; 8 nuevas se repitieron tras el ajuste
  final. `fast` correcto; no se ejecutó `full` local.

### PY03 — Parseo de snapshot repetido en varias fronteras — resuelto

- **Prioridad:** media. **Ubicación:** `central_api.py`,
  `persisted_view.py:store_message`, `sqlite_store.py:store_message`.
- En el ingreso account-state, el API validaba el cuerpo, lo pasaba a bytes
  canónicos y las capas de vista/SQLite volvían a parsearlo antes del commit.
  Trading-events también repetía el parseo entre API, autorización y SQLite.
- **Cambio:** las capas internas reutilizan el envelope validado. Las interfaces
  públicas que reciben bytes (`store_message` y `authorize`) conservan el parseo
  completo; la API conserva autenticación, validación de contrato/Pydantic,
  autorización de productor, canonicalización, hashes, transacción y
  verificación del registro comprometido desde SQLite. La escritura v2 sigue
  contrastando cuenta, rol, fuente e identidad con la base.
- **Evidencia:** una prueba HTTP instrumenta los parseos: account-state reduce
  de tres parseos de escritura/lectura a uno de entrada más el parseo intencional
  al restaurar/verificar SQLite; trading-events reduce los parseos internos a
  cero tras el parseo HTTP. No se afirma una mejora de latencia medida.
- **Aceptación:** los tests de almacenamiento, autorización y receiver conservan
  validación, duplicados, conflictos, secuencias y restauración. La integración
  HTTP FastAPI añadida sigue pendiente de ejecución; no se incluye entre las
  comprobaciones aisladas de esta ampliación.

### PY04 — Métricas de ciclos con potencial de escalabilidad

- **Prioridad:** media; candidato de escalabilidad, no bug. **Ubicación:**
  `dashboard/telemetry_v2.py`, `cycle_performance_metrics`.
- Procesar por 100 ciclos y limitar series a 1200 son controles positivos; cada
  cálculo recorre el rango y crea acumulador por EA. Memoria estructural O(EAs ×
  capacidad de series), no O(historial). Costo de producción no medido.
- **Propuesta:** separar resumen global de desglose por EA solicitado; valorar
  agregación incremental persistida solo si se justifica. No cachear historial
  completo.
- **Aceptación:** muchas EAs/páginas conservan resultados idénticos y memoria
  acotada.
- **Medición reproducible:** `uv run python scripts/benchmark_cycle_metrics.py`
  genera ciclos cerrados sintéticos y compara la acumulación de métricas sin
  paginación con el recorrido completo del provider sobre un cliente sintético
  que entrega páginas de 100. Reporta mediana, rango observado, cantidad de
  páginas y pico de asignaciones Python (`tracemalloc`). Por ejemplo:
  `uv run python scripts/benchmark_cycle_metrics.py` (valores por defecto:
  1.000/10.000/30.000 ciclos, 1/5/20 EAs y cinco repeticiones).
- **Límite de interpretación:** el benchmark aísla acumulación y lógica de
  paginación/validación del provider; no incluye red, SQLite, JSON del receiver,
  renderizado del dashboard ni RSS total del proceso. No impone umbrales de
  tiempo en CI. Para estimar el costo real hay que contrastarlo con lecturas de
  solo consulta contra el servidor remoto, midiendo por separado latencia total,
  cantidad de páginas y espera en API/SQLite. No ejecutar esa prueba hasta
  preparar explícitamente el entorno de lectura.
- **Línea base sintética (2026-11-05):** Windows NT 10.0.20348.0, Python 3.14.7,
  cinco repeticiones por escenario. Con 20 EAs: 1.000 ciclos tardaron 11.64 ms
  en acumulación y 15.10 ms en el provider (10 páginas; pico transitorio Python
  1.67 MiB); 10.000, 152.14/169.81 ms (100 páginas; 8.67 MiB); 30.000,
  479.63/456.68 ms (300 páginas; 13.15 MiB). Los tiempos incluyen solo cálculo
  Python y paginación simulada: no representan una mejora del provider frente a
  acumulación, y el aparente menor tiempo en el último caso está dentro de la
  variación medida. Cinco muestras no permiten estimar p95 de forma útil; se
  conserva mediana y rango en la salida. El benchmark no evidencia todavía una
  necesidad de cache/SQLite materializada; el principal costo desconocido son
  los viajes reales por cada página y la consulta del receiver.

### PY05 — Envío del relay serializa streams

- **Prioridad:** media. **Ubicación:** `relay.py`, `RelayForwarder.run_once`.
- Un destino lento puede demorar streams posteriores hasta timeout; efecto
  secuencial visible, impacto remoto no medido.
- **Propuesta:** asegurar turnos entre fuentes y evaluar I/O concurrente limitado sin
  paralelizar FIFO de un stream ni cambiar ACK.
- **Aceptación:** transporte lento, ACK perdido y FIFO no causan pérdida,
  reordenamiento ni confirmación prematura.

### PY06 — Límite de registros incluye ACK confirmados — resuelto

- **Prioridad:** alta, riesgo operativo confirmado. **Ubicación:**
  `relay_queue.py`, `enqueue` y `finish`.
- La cuota `max_records` ahora cuenta solo mensajes no confirmados (`pending` y
  `rejected`); la admisión y el conteo ocurren dentro de la misma transacción
  serializada. Las filas `acked` siguen reteniendo identidad y hash, por lo que
  duplicados exactos se reconocen incluso tras reiniciar, pero no bloquean nuevas
  admisiones. `active_records` y `retained_records` hacen visible la diferencia.
- **Límite conocido:** no se agregó borrado/compactación de huellas locales. El
  ledger retenido sigue creciendo y requiere una política de retención separada
  antes de operación prolongada/producción; no se deben eliminar tombstones sin
  acordar el horizonte de deduplicación.
- **Aceptación:** comprobado que ACKs acumulados superan una cuota pequeña sin
  bloquear nuevas admisiones; la cuota sigue frenando pendientes, y duplicados
  ACKed se reconocen tras reinicio. Límites y crecimiento retenido están
  documentados.

### PY07 — Cobertura de paginación vuelve a parsear payloads — resuelto

- **Prioridad:** media. **Ubicación:** `sqlite_store_v2.py`,
  `_has_complete_pagination_chain`.
- **Hallazgo de base:** obtenía y acumulaba payloads completos con `fetchall`,
  incluidos arrays de operaciones, y los decodificaba en Python para reconstruir
  únicamente los enlaces entre páginas.
- **Cambio:** SQLite proyecta solo el objeto `pagination` y filtra también los
  totales de deals/órdenes. Python recorre el cursor y conserva solo el grafo de
  enlaces. Se mantienen los filtros de cuenta, fuente, ventana y snapshot, el
  recorrido desde el cursor inicial y el rechazo transaccional de una página
  final sin cadena durable. Sin cambio de esquema, migración ni índices nuevos.
- **Plan SQL comprobado:** en SQLite 3.50.4, `EXPLAIN QUERY PLAN` usa en ambos
  casos la clave de `sources(source_id)` y el índice existente
  `telemetry_v2_messages_source_capture` por su prefijo `source_id`. Los filtros
  JSON siguen evaluándose sobre los mensajes de esa fuente: esta corrección no
  elimina ese recorrido ni materializa una nueva proyección persistente.
- **Medición aislada:** SQLite en memoria con el esquema central real,
  400 páginas del snapshot, 1.600 mensajes de otro snapshot de la misma fuente
  y cuerpos de aproximadamente 7,3 KB. Cinco repeticiones sobre la comprobación
  anterior y la función final: mediana 33,97 → 17,69 ms; pico de asignaciones
  Python 2.968,8 → 102,4 KiB; JSON transferido a Python 2.906.765 → 66.765 bytes.
  La preparación de datos queda fuera del tiempo y del pico; son resultados
  sintéticos, sin incluir red ni flujo integrado, y no constituyen un umbral de CI.
- **Aceptación local:** 30 pruebas de almacenamiento correctas, incluidas cuatro
  nuevas que verifican lectura de metadatos compactos, tickets uint64 exactos,
  aislamiento por identidad/ventana/snapshot/totales y rollback ante huecos o
  totales incompatibles. Las pruebas integradas quedan aplazadas por decisión
  del usuario.

### PY08 — Una captura de ciclo contradictoria puede recuperar métricas antiguas

- **Prioridad:** alta, exactitud financiera. **Ubicación:**
  `sqlite_store_v2.py:position_cycles`, CTE `capture_summary`/`eligible`.
- **Hallazgo:** se eliminan las capturas con más de una variante antes de
  calcular el ranking por posición. Si la captura más reciente es ambigua,
  reaparece una captura anterior y puede seguir siendo elegible para métricas.
  El DTO del ciclo no informa ese conflicto, a diferencia del registro de
  actividad, que dispone de `conflict_at`.
- **Evidencia aislada:** SQLite temporal, una posición con una captura válida de
  PnL 9,8 y dos capturas posteriores contradictorias del mismo instante. La
  consulta devolvió la captura anterior con `eligible_for_autonomous_metrics=True`.
- **Solución:** resolver primero la revisión más reciente de la posición y su
  estado de conflicto; conservar evidencia anterior para consulta con señal
  explícita, pero excluir de métricas autónomas mientras haya ambigüedad vigente.
  Aplicar filtros de EA sin permitir que rescaten revisiones antiguas descartadas.
- **Aceptación:** un conflicto posterior nunca aporta un PnL antiguo como
  definitivo; una observación posterior no ambigua puede resolverlo. Historial,
  filtros por Magic y métricas deben compartir esa decisión.
- **Implementación local:** la última evidencia no ambigua permanece consultable
  con `conflicting_evidence` mientras exista una captura posterior contradictoria.
  La exclusión se deriva al leer: no modifica el ledger ni requiere migración.
  Los filtros por Magic se aplican después de resolver revisiones para toda la
  posición. Sin evidencia no ambigua no se elige una variante arbitraria; una
  captura posterior consistente vuelve a habilitar las métricas.
- **Validación:** 34 tests dirigidos de SQLite correctos, incluidos cuatro casos
  nuevos: conflicto y resolución tras reapertura, ausencia de evidencia anterior,
  copias idénticas y filtros por propietario. El caso de conflicto también valida
  serialización/parsing del cliente y exclusión en métricas batch y streaming con
  dobles sin red. No se ejecutó el flujo integrado ni se conectó con MT5.
  Reglas de consulta documentadas en
  [referencia de métricas](workbook-metrics-reference.md#capturas-contradictorias-de-un-ciclo).

### PY09 — El cálculo paginado no tiene un presupuesto global de ejecución

- **Prioridad:** alta, robustez. **Ubicación:**
  `dashboard/telemetry_v2.py:cycle_performance_metrics` y `http_server.py`.
- **Hallazgo:** hay timeout por request del cliente y límite de conexiones, pero
  no plazo global del cálculo. La expiración del socket del dashboard no cancela
  el trabajo Python del handler. El control actual detecta un cursor idéntico al
  inmediatamente anterior, pero no un retorno a una página anterior.
- **Evidencia aislada:** un cliente doble alternando dos páginas con cursores
  válidos siguió solicitándolas hasta que un corte de prueba detuvo la quinta
  llamada. No se dejó correr ningún bucle ilimitado.
- **Solución:** presupuesto monotónico inyectable para la operación completa,
  propagando tiempo restante a cada lectura y verificando avance estricto entre
  páginas mediante la clave temporal/posición. Acotar el trabajo interactivo y
  coordinar su plazo con el servidor; si se supera, devolver error explícito,
  nunca métricas parciales presentadas como completas.
- **Aceptación:** regresiones de cursor y agotamiento del presupuesto terminan
  de forma controlada y liberan el worker; un historial válido conserva resultados.
  Los valores operativos del presupuesto se decidirán con mediciones representativas.
- **Implementación local:** presupuesto monotónico inyectable que incluye
  cobertura, páginas, acumulación y preparación del resultado. Valor inicial:
  4 segundos, configurable con `V2HistoryProvider(metrics_budget_seconds=...)`
  dentro del rango mayor que cero y hasta 30 segundos; no es aún un valor
  calibrado con la API remota. Cada lectura recibe el tiempo restante y limita
  su timeout de I/O al menor entre ese valor y el timeout configurado del cliente.
  La lectura por bloques comprueba tiempo transcurrido, incluso si llegan bytes
  continuamente. Se exige avance estricto por `(last_event_at_msc, position_id
  numérico)` entre todos los ciclos, incluyendo páginas finales, y cursor igual
  a la clave del último ciclo. No se conserva un conjunto creciente de cursores.
- **Límite de la garantía:** es un plazo cooperativo, no una cancelación forzada
  de threads. `urllib`/socket no ofrecen aquí un deadline absoluto para cada
  fase de conexión/cabeceras; un I/O ya bloqueado puede terminar después del
  presupuesto y entonces fallar. El timeout de socket del servidor tampoco
  cancela el handler. El presupuesto inicial de 4 segundos se mantiene por
  debajo del timeout por defecto del dashboard (5 segundos), sin prometer un
  límite duro de pared. Confirmar valores y latencias al retomar el flujo remoto.
- **Validación:** 14 pruebas nuevas sin red verifican presupuesto compartido,
  propagación del tiempo restante, expiración en lectura/acumulación/preparación,
  lectura por bloques, límites de tamaño, cursores inconsistentes, páginas que
  alternan y orden numérico válido. También pasan el benchmark sintético pequeño
  y los 34 tests de SQLite. Sin servicios, MT5 ni pruebas integradas del flujo.
  El doble del benchmark ahora emite cursores con el formato real de la API.

### PY10 — La guarda de bitácoras no comprueba los commits que saldrán en el push

- **Prioridad:** alta, protocolo del harness. **Ubicación:**
  `scripts/session.py:guard_direct_session_publish`.
- **Hallazgo:** comprueba rama y `git status`, pero no el rango de commits
  salientes respecto de la rama remota. Puede aprobar un árbol con solo la
  bitácora de hoy aunque HEAD ya contenga cambios de producto sin publicar.
- **Evidencia aislada:** repositorio Git temporal con referencia remota local,
  un commit pendiente que modifica `README.md` y una bitácora de hoy sin commit.
  La guarda devolvió cero errores; el rango saliente incluía `README.md`.
- **Solución:** separar la guarda de preparación del commit y la guarda de push.
  Antes del push directo, verificar la referencia remota exacta y cada commit
  saliente, incluyendo cambios revertidos, renombres y borrados. Admitir solo
  altas/actualizaciones de bitácoras del día vigente en la rama autorizada;
  rechazar referencias ausentes o rangos que no puedan verificarse.
- **Aceptación:** commits ajenos pendientes, cambios de días previos, renombres,
  borrados y cambios ocultos por un revert bloquean la excepción. No ejecutar
  un push real para probar la guarda.
- **Implementación local:** `guard-publish --phase commit` inspecciona los cambios
  pendientes; `guard-publish` (fase `push` por defecto) exige árbol limpio y
  upstream exacto `refs/remotes/origin/<rama-estable>`. Comprueba que la referencia
  remota existe y es ancestro de HEAD, y revisa cada commit saliente con diff sin
  detección de renombres. Solo admite altas/modificaciones de archivos regulares
  no ejecutables fechados hoy y valida cada blob con las mismas reglas del archivo
  de trabajo. Rechaza merges, rangos vacíos y cambios durante la inspección.
  La excepción temporal de la rama de integración sigue vigente.
- **Operación:** no ejecuta fetch ni push; requiere actualizar `origin` antes de
  validar y publicar únicamente `HEAD:refs/heads/<rama-estable>`, sin force-push.
  El flujo queda explicado en el
  [proceso de bitácoras](../sessions/README.md#flujo-excepcional-sobre-main).
  La guarda local no sustituye una protección remota ni elimina la carrera entre
  comprobar y publicar: si cambian las referencias, archivos o fecha, se repite.
- **Validación:** 25 tests dirigidos de bitácoras correctos (16 nuevos) en
  repositorios temporales, con referencias sintéticas y sin red ni pushes.
  Cubren commits ajenos revertidos, blobs inválidos reparados después, entradas
  antiguas, renombres, borrados, modos ejecutables, merges, upstream ausente o
  incorrecto, divergencia, árbol sucio, cambios concurrentes y la rama temporal
  de integración. También pasa `check.py fast`; la suite completa queda en CI.

### PY11 — La rotación no limita el log durante una ejecución larga

- **Prioridad:** media. **Ubicación:** `operational_job.py:run_logged`.
- **Hallazgo:** `rotate_log` se ejecuta antes de iniciar el hijo y luego este
  escribe directamente en el mismo archivo hasta terminar. El límite de 5 MiB
  no se aplica durante una API que permanezca encendida mucho tiempo.
- **Evidencia aislada:** un hijo simulado escribió 5.242.881 bytes en una sola
  ejecución; el archivo superó el umbral sin generar una copia rotada.
- **Solución:** rotación durante la ejecución, mediante logging del proceso
  propietario o un supervisor que drene la salida en bloques acotados. No
  acumular stdout en RAM ni renombrar a ciegas un archivo abierto en Windows.
- **Aceptación:** una única ejecución ruidosa conserva un tamaño/cantidad de
  archivos acotados, sigue drenando la salida y no expone credenciales.
- **Implementación local:** `run_logged` ahora supervisa con `Popen` y stdout/
  stderr unidos en una tubería. Drena bloques binarios de hasta 64 KiB, divide
  escrituras según el espacio disponible y cierra cada append antes de rotar.
  Conserva el código de salida y los límites de 5 MiB más tres copias; los límites
  se pueden inyectar para pruebas. No añade hilos, buffers crecientes ni logs de
  argumentos/configuración. El caller mantiene el lock de escritor único.
- **Fallos y límites:** ante un error de drenaje/escritura o interrupción intenta
  terminar y esperar al hijo; si no termina en 5 segundos, lo mata y espera hasta
  otros 5 segundos. Cierra la tubería y propaga el error, sin continuar a ciegas.
  No trunca copias heredadas sobredimensionadas ni filtra secretos impresos por
  el hijo. La rotación por bytes puede dividir líneas o caracteres UTF-8; la
  salida se conserva como bytes, sin conversiones destructivas.
- **Validación:** 10 pruebas dirigidas correctas, siete nuevas: salida sin saltos
  mayor que la tubería y retención del tail, caso original de 5 MiB + 1, archivo
  parcial previo, hijo silencioso, rotación antes de finalizar el hijo, fallo
  del destino con cleanup/kill simulado y límites inválidos sin lanzar procesos.
  Solo procesos sintéticos en carpetas temporales; sin servicios ni MT5.
  La operación queda documentada en
  [preparación del host](remote-host-setup.md#logs-del-ejecutor-supervisado).

### PY12 — Un mantenimiento rechazado sobrescribe el estado del job activo

- **Prioridad:** media. **Ubicación:**
  `scripts/run_telemetry_maintenance.py`, manejo de excepciones.
- **Hallazgo:** si el lock está ocupado, el segundo proceso escribe `failed`
  fuera del lock sobre el estado del primero. El registro deja de representar
  al propietario y los escritores pueden competir por el mismo temporal.
- **Evidencia aislada:** manteniendo el lock real de un job sintético, una
  segunda llamada terminó con código 1 y cambió su estado `running` a `failed`.
- **Solución:** solo el propietario del lock actualiza el estado compartido.
  Registrar intentos rechazados por separado si hace falta; diferenciar lock
  ocupado de un fallo del trabajo y conservar la identidad de la ejecución.
- **Aceptación:** un intento simultáneo no modifica el estado del propietario;
  fallos auténticos posteriores a adquirir el lock sí quedan registrados.
- **Implementación local:** las escrituras de `running`, `succeeded` y `failed`
  ocurren dentro del lock. Se elimina toda actualización de estado desde el
  manejador externo. `JobAlreadyRunningError`, compatible con `RuntimeError`,
  diferencia contención de otros errores de E/S. El CLI devuelve `2` con un
  mensaje de omisión si está ocupado, y `1` ante fallos reales; no crea otro
  registro ni cambia el estado del dueño. En Windows se adquiere el lock antes
  de leer/inicializar su byte para no confundir una lectura bloqueada con un
  fallo de almacenamiento. Si registrar `failed` también falla, se conserva la
  causa original del trabajo.
- **Validación:** nueve pruebas nuevas de mantenimiento correctas, incluyendo
  contención real desde otro proceso CLI y conservación byte a byte del estado,
  ausencia de estado previo, fallo anterior al lock, fallo de backup registrado
  bajo lock, éxito/reutilización, error de E/S, doble fallo y vista previa.
  También pasan 11 pruebas operativas (una nueva sobre E/S del lock) y dos casos
  dirigidos del host: backup real de una SQLite sintética y registro del resultado
  del ejecutor. Solo directorios temporales; sin servicios ni datos operativos.
  El comportamiento queda explicado en
  [preparación del host](remote-host-setup.md#estado-del-mantenimiento-y-ejecuciones-simultáneas).

### PY13 — Una copia puede aparecer publicada sin manifest

- **Prioridad:** media. **Ubicación:** `backup.py:BackupPlan.apply`.
- **Hallazgo:** se crea el directorio final y se mueven base y manifest en dos
  pasos. Un fallo entre ambos deja un directorio con nombre definitivo y una
  base, pero sin el paquete completo. La fuente no resulta modificada.
- **Evidencia aislada:** se inyectó un fallo en el movimiento del manifest sobre
  una SQLite temporal. Quedó un directorio final con `data.sqlite3` y sin
  `manifest.json`, además del temporal incompleto.
- **Solución:** preparar y verificar ambos archivos dentro del temporal;
  publicar el paquete mediante una operación atómica de directorio, con guarda
  contra sobrescritura y durabilidad apropiada. Los fallos previos a publicar
  deben conservar exclusivamente artefactos claramente temporales.
- **Aceptación:** cualquier fallo intermedio deja el paquete anterior intacto y
  ningún paquete nuevo aparentemente definitivo pero incompleto. No requiere
  ejecutar ahora restauraciones ni copias fuera de la VPS, tareas aplazadas.
- **Implementación local:** base comprobada y manifest se completan y sincronizan
  dentro de `.tmp-telemetry-*`. Se vuelve a leer el manifest para validar lo escrito.
  Un solo renombrado de carpeta publica el paquete. Bajo un lock de publicación
  común a TradingLab se rechaza cualquier destino existente, incluso vacío o
  enlace simbólico; no se sobrescriben copias. La contención de ese lock se
  convierte en error de publicación, sin confundirse con un job omitido por PY12.
- **Durabilidad y límites:** archivos con `fsync`; macOS/Linux sincronizan además
  directorios. Windows no tiene aquí equivalente portable para esa última operación.
  Fallos anteriores a publicar dejan el paquete nuevo solo como temporal y no
  alteran los anteriores. Un fallo de sincronización posterior al renombrado puede
  dejar un paquete completo publicado y devolver error: no equivale a publicación
  parcial ni se revierte borrándolo. El directorio operativo se presupone confiable;
  el lock serializa publicadores cooperantes, no programas externos que ignoren
  el protocolo. No se implementa limpieza automática ni restauración.
- **Validación:** 12 tests de backup correctos, ocho nuevos sobre paquete completo
  antes del único rename, fallo de manifest, fallo de rename, destinos ya existentes,
  contención, manifest no verificado y fallos de sincronización antes/después de
  publicar. También pasan nueve tests de mantenimiento y el caso dirigido del CLI
  con una SQLite temporal real. Sin copias de datos operativos ni servicios.
  Reglas de operación en
  [preparación del host](remote-host-setup.md#publicación-de-las-copias-sqlite).

### PY14 — El control de Origin no representa HTTPS terminado en el proxy

- **Prioridad:** media, preparación del host remoto. **Ubicación:**
  `central_api.py:safe_headers` y `scripts/central_api.py`.
- **Hallazgo:** el proceso usa `proxy_headers=False` y compara Origin con el
  esquema interno de la petición. Cuando el proxy recibe HTTPS y entrega HTTP
  a loopback, un Origin HTTPS legítimo no coincide. Afecta a peticiones del
  navegador, incluida la consola OpenAPI; el relay normalmente no envía Origin.
- **Evidencia aislada:** middleware ASGI en memoria, sin lifespan ni base: Host
  permitido, backend HTTP y Origin HTTP devolvieron 200 para `/docs`; con el
  Origin HTTPS del mismo host devolvió 403. Un origen ajeno también se rechazó.
- **Solución:** configurar los orígenes públicos exactos y validar esquema,
  host y puerto de forma explícita. Conservar protección contra orígenes ajenos
  y no confiar globalmente en cabeceras de proxy aportadas por clientes.
- **Aceptación:** HTTPS público y loopback autorizados funcionan con su
  configuración correspondiente; orígenes ajenos y valores ambiguos se rechazan.
- **Implementación local:** `CentralSettings.public_origins` y el flag repetible
  `--public-origin` autorizan orígenes HTTPS exactos asociados a `allowed_hosts`.
  El launcher manual con `--tailscale-host` añade el FQDN y su origen HTTPS/443.
  Loopback conserva same-origin; los hosts públicos no autorizan implícitamente
  un Origin HTTP ni HTTPS. Se normaliza el puerto por defecto (443/80), pero se
  rechazan representaciones ambiguas, duplicados semánticos en configuración,
  cabeceras Origin/Host repetidas, orígenes `null` o vacíos, rutas, credenciales,
  listas y comodines. Se mantienen bind loopback, Bearer, TrustedHost y
  `proxy_headers=False`; no se agrega CORS ni confianza en `Forwarded`.
- **Validación:** 11 tests nuevos correctos, con ASGI en memoria sin lifespan,
  SQLite ni sockets, más tres casos dirigidos existentes de límites/autenticación,
  Host sin origen público implícito y propagación del launcher. Cubren HTTPS
  sobre backend HTTP, Host reescrito a loopback, puertos, entradas malformadas,
  duplicados, intento de spoofing por headers de proxy y ausencia de bypass de
  autenticación. No se inició una API ni se configuró Tailscale. La prueba real
  de HTTPS/Swagger sigue pendiente; la propagación a tareas programadas queda
  implementada y documentada en PY15. Operación actualizada en
  [API central](central-api-operation.md#arranque-explícito) y
  [host remoto](remote-host-setup.md#9-conectividad-privada-con-tailscale).

### PY15 — El arranque programado no conserva el host público permitido

- **Prioridad:** media, despliegue remoto. **Ubicación:** `windows_tasks.py`,
  `scripts/run_central_api_job.py` y `scripts/run_remote_host.py`.
- **Hallazgo confirmado por código:** el arranque manual acepta
  `--tailscale-host`, pero la tarea y su wrapper solo propagan `--data-dir`.
  No existe otra ruta en ese arranque para añadir el FQDN a `allowed_hosts`.
  Solicitudes que lleguen con ese Host serán rechazadas; no se afirma haber
  comprobado cómo reenviará Host un despliegue concreto de Tailscale.
- **Solución:** una configuración pública y validada compartida por arranque
  manual y programado, o propagación explícita del FQDN por sus argumentos
  declarativos. Mantener bind loopback, validación del hostname y ausencia de tokens en argv.
- **Aceptación:** el comando generado conserva el mismo host autorizado que el
  arranque manual; sin host adicional se mantiene el comportamiento local.
- **Implementación local:** el instalador, `task_plan` y el wrapper del job
  aceptan `--tailscale-host` opcional y validado con el mismo parser del launcher
  manual. La tarea conserva el argumento y el wrapper lo pasa a `run_remote_host`,
  que ya configura Host y Origin HTTPS por PY14. La vista previa muestra el host
  y el origen sin instalar nada. El mantenimiento no recibe este flag; sin él
  se conservan los argumentos locales. No se cambian bind, permisos ni tokens.
- **Validación:** seis tests de tareas correctos (cinco nuevos), más tres casos
  dirigidos del host (dos nuevos): plan/XML con rutas con espacios y escape,
  rechazo de hosts inválidos, vista previa sin comandos externos y propagación
  job → launcher → CLI central con origen HTTPS. El caso previo sin host sigue
  pasando. No se registraron ni modificaron tareas, ni se lanzó la API.
  La prueba operativa real queda pendiente. Una tarea instalada requiere revisión
  humana para actualizar sus argumentos; el instalador no la sobrescribe.
  Instrucciones en [preparación del host](remote-host-setup.md#6-windows).

### PY16 — La inspección de la base central solo resume account-state

- **Prioridad:** media, observabilidad. **Ubicación:**
  `inspection.py:_summarize` y `scripts/inspect_telemetry_db.py`.
- **Hallazgo:** enumera todas las fuentes de la base unificada, pero calcula
  mensajes, sesiones, deals y Magics exclusivamente desde `telemetry_messages`.
  La actividad durable de `telemetry_v2_messages`/`activity_observations` no se
  refleja; la salida no deja claro ese alcance restringido.
- **Evidencia aislada:** base central sintética con un mensaje de actividad y
  su deal persistido; el resumen devolvió `message_count=0`.
- **Solución:** mostrar totales y contadores por contrato, o identificar
  inequívocamente una inspección limitada a account-state. Para el resumen
  central, unir identidades de deals por cuenta/ticket sin sumarlos dos veces
  cuando aparecen en ambos canales; conservar consultas de solo lectura y no
  volcar payloads ni datos sensibles.
- **Aceptación:** una base con solo actividad muestra esa evidencia; una con
  ambos canales informa su alcance y deduplicación de forma comprensible.
- **Implementación local:** totales de mensajes, sesiones por fuente y rango de
  capturas incluyen ambos contratos. El resumen desglosa account-state y
  trading-events (live snapshots, activity batches y heartbeats). Los deals
  históricos se unen por cuenta/ticket entre snapshots y Activity; las órdenes
  históricas de Activity se deduplican por la misma identidad. Los Magics incluyen
  Live y Activity sin imprimir filas, tickets, cuentas ni payloads. No se suman
  dos veces posiciones/órdenes actuales: su conteo anterior queda explícitamente
  limitado a account-state por fuente. El rango se llama capturas registradas,
  no cobertura completa. Se conserva la transacción única de solo lectura y no
  se modifica SQLite ni se migra el esquema.
- **Validación:** 12 tests dirigidos correctos, seis nuevos: actividad sola,
  mezcla de contratos con Live/heartbeat, deduplicación de revisiones sin mezclar
  cuentas ni tickets uint64 contiguos, órdenes canceladas sin deals, desglose de
  heartbeats y salida CLI sin registros privados. Incluyen controles de lectura
  sin cambios en el archivo, base vacía y plausibilidad del último snapshot.
  Solo SQLite sintética; no se inspeccionaron datos operativos. Alcance y uso en
  [operación de telemetría](telemetry-operation.md#inspección-segura-de-la-base).

## Hallazgos MQL5

### MQ01 — Relectura de historial durante paginación Activity

- **Prioridad:** media-alta. **Ubicación:** `BuildPagedActivityPayload` y
  `ConsiderPageKey`.
- Cada continuación invoca `HistorySelect`; cada página vuelve a recorrer la
  ventana completa, repartiendo ese escaneo entre timers. La inserción ordenada
  opera con K ≤ 200. Para P páginas y N registros en la ventana, el peor caso
  de selección crece O(P × N × K),
  memoria O(K). El código detecta ventanas densas y divide/pagina; no se afirma
  que procese sin límite en una sola página ni que el historial venga ordenado.
- **Propuesta:** reducir relectura/top-K o estudiar cursor/snapshot seguro; heap
  solo si aporta. Conservar fingerprint, cadena, orden tiempo-entidad-ticket y
  límites.
- **Aceptación:** historial denso y mutación no alteran orden, continuidad ni
  detección de cambios.

### MQ02 — `CycleBudgetMs` no limita el ciclo completo

- **Prioridad:** media. **Ubicación:** ciclo Activity y timer Telemetry.
- El presupuesto cooperativo limita el bucle de escaneo, no necesariamente
  `HistorySelect`, serialización de página, reconciliación de posiciones o
  `WebRequest`; el timer Telemetry puede hacer dos requests. `25 ms` no garantiza
  duración total del callback; medición por fase pendiente.
- **Propuesta:** etapas acotadas, contabilizar trabajo y timeout total; evitar
  red/disco/historial en `OnTradeTransaction`.
- **Aceptación:** límites por fase y recuperación observables, sin bloquear
  callback de trading ni cambiar semántica.

## Fortalezas y exclusiones

- Callback de trading mínimo, colas acotadas, outbox durable y ACK tras commit.
- Reloj/transporte inyectables; Welford, deque de 20 y series acotadas.
- `deepcopy` protege encapsulamiento de snapshots; no retirarlo sin DTO inmutable
  equivalente y pruebas.
- Logger con 32 incidentes, 1 MiB/día, rate limit y retención de 14 días.
- No se abren hallazgos sobre `OnCalculate`, `CopyBuffer` o handles: estos
  collectors no los usan.

## Cobertura de la ampliación Python

La revisión estática por bloques del Python vigente queda realizada. No es una
verificación formal de cada posible entrada ni sustituye las pruebas integradas.
Se contrastaron rutas de ejecución, fronteras y pruebas relevantes, con búsqueda
transversal de lecturas masivas, efectos, procesos externos y errores.

| Bloque | Alcance examinado | Resultado |
|---|---|---|
| Dashboard | `auth`, `service`, `web`, `snapshot`, clientes `telemetry*` y CLI | Sesiones acotadas; PY08/PY09 y mejoras de cohesión abajo |
| Dominio financiero | `position_cycles`, `trade_details`, `workbook_v1` y su uso por el provider | Reglas conservadoras y Decimal; PY08 afecta la selección persistida |
| API y contratos | `central_api`, `api_models`, `contract*`, `http_contracts_v2`, admisión y adaptadores HTTP auxiliares | Autorización separada y errores saneados; PY14 y frontera validada a formalizar |
| Persistencia | Esquema central, registros SQLite, receivers, vista y composición de evidencia | PY01/PY02/PY03/PY07 previos; PY08 y PY16 nuevos |
| Relay | Ingreso, outbox, transporte, ACK y configuración | PY06 corregido; PY05 pendiente de medición remota; ACK inválido conserva el mensaje |
| Configuración y bootstrap | `local_secrets`, `relay_config`, `remote_host`, creación y arranque del host | Validación y secretos fuera de argv; PY14/PY15 y mejoras acotadas abajo |
| Operación | Backup, inspección, jobs, tareas Windows y sus CLI | PY11/PY12/PY13/PY15/PY16 |
| Diagnóstico MT5 | `incubation/diagnostic`, CLI y publicación de evidencia | Identidad explícita y archivos exclusivos; se revisó código sin ejecutar MT5 |
| Harness | `check`, `change`, `ci_scope`, `session` y cobertura de soporte pertinente | Clasificación conservadora sin auto-reintentos; PY10 |

### SOLID, DRY, YAGNI y encapsulamiento

- **Separación y dependencias:** dominio financiero sin red/SQLite, interfaces
  pequeñas para fuentes y transporte, y composición desde CLI son decisiones
  adecuadas. No se justifica un contenedor de dependencias, más servicios ni
  una jerarquía de patrones por cada función.
- **Cohesión mejorable:** `web.py` y `central_api.py` concentran muchas rutas y
  validaciones. Extraer parsers y presentadores puros cuando se modifiquen esas
  rutas, reutilizando `http_contracts_v2` donde las reglas realmente coincidan.
  No convertir contratos distintos en una abstracción genérica solo por DRY.
- **Frontera validada:** FastAPI llama `_accept_validated` y los receivers llaman
  métodos privados de otras capas. Formalizar una entrada interna pública,
  tipada y explícita para envelopes ya validados, manteniendo las entradas de
  bytes seguras. `frozen=True` no vuelve inmutable el diccionario `payload`;
  conservar copias defensivas o reemplazarlas por DTO inmutable equivalente,
  con una prueba de aislamiento. No retirar `deepcopy` por criterio estético.
- **Fórmulas batch/streaming:** son dos formas de retener resultados con
  necesidades diferentes. Mantener pruebas de equivalencia y una versión de
  fórmula compartida; no sustituir Decimal por float/vectorización ni agregar
  NumPy/Pandas a este cálculo sin necesidad medida.
- **Configuración:** acotar la lectura de archivos locales pequeños de secretos,
  normalizar errores de JSON excesivamente anidado en `read_host_config` y
  evitar duplicar listas de nombres de credenciales entre bootstrap y CLI.
  Son mejoras de robustez/mantenimiento para entradas locales controladas,
  no una exposición remota demostrada.
- **Menor privilegio:** el dashboard usa credenciales de lectura en sus clientes,
  pero su loader admite también nombres de ingesta. Preferir un archivo solo
  de lectura y una allowlist específica al reorganizar configuración; no
  compartir `.env.central` completo. El generador de tokens existente usa
  `secrets`; no se necesita introducir JWT o hashing de contraseñas para este
  mecanismo actual de tokens opacos.
- **Rendimiento:** estructuras dict/set/deque y series limitadas son apropiadas.
  Las copias de snapshots y la compresión gzip repetida de assets son candidatos
  menores para medir si hay síntomas, no motivos para cachear historia ni abrir
  otro refactor ahora. Los límites de salida no sustituyen un presupuesto global
  de trabajo: PY09 merece atención antes de optimizaciones de sintaxis.

### Evidencia de esta ampliación

- Ocho reproducciones aisladas: conflicto de ciclo, cursores alternantes,
  guarda de push en Git temporal, log de un hijo simulado, intento simultáneo
  de mantenimiento, fallo de publicación de backup, inspección de una base
  solo de actividad y middleware ASGI con HTTPS público/HTTP interno.
- 22 pruebas unitarias existentes correctas: 3 de autenticación, 8 de ciclos de
  posición, 6 de detalles y 5 de fórmulas batch/streaming. No se añadieron tests
  de producto por esta tarea de revisión ni se ejecutó `full`.
- Los datos, repositorios y procesos simulados de las reproducciones son
  temporales. No se leyeron archivos de credenciales reales, ni se iniciaron
  servicios operativos, ni se conectó con MT5. El caso ASGI no usa lifespan,
  SQLite ni sockets; verifica únicamente el middleware y `/docs`.
- PY15 se confirma por inspección del encadenamiento de argumentos; queda
  pendiente comprobar el despliegue real cuando se retomen esas pruebas.

## Siguiente paso y tareas aplazadas

1. La entrega agrupa benchmark, correcciones y documentación en commits por
   responsabilidad dentro del PR de esta revisión, hacia
   `feature/remote-data-platform`. Verificar CI y mantener merge humano.
2. Confirmar en CI las correcciones Python ya implementadas, también en macOS/Linux.
   Las mejoras de estilo o cohesión no urgentes pueden acompañar cambios futuros;
   no son motivo para una reescritura general.
3. PY01/PY02/PY03 y PY06–PY16 ya están implementados; PR/CI y merge humano
   siguen pendientes. El benchmark PY04 y las correcciones desde PY07 se incluyen
   en esta misma entrega. No se declara
   el flujo operativo validado solo por haber cerrado estas correcciones locales.
4. PY04 cuenta con línea base sintética local; contrastar el costo con la API y
   SQLite reales cuando se retomen las pruebas integradas. Evaluar PY05 entonces,
   con conectividad remota y mediciones representativas. La prueba HTTP
   instrumentada de PY03 también permanece pendiente.
5. Al final, retomar MQ01/MQ02, la revisión de collectors y las pruebas manuales
   MQL5 y del flujo completo. No se adelantan como parte de esta revisión Python.

### Pendientes operativos acordados tras la revisión

Orden de validación: compilar y ejecutar las pruebas nativas de collectors,
probar el flujo completo en el entorno local actual y, después, validar la
instalación real en Mac o Linux. No adelantar el traslado de datos ni la
configuración de servicios/red como parte de la compilación.

Compilación aislada del 2026-11-05: Telemetry `0.3.0`, Activity `activity-0.8.0`
y los cuatro scripts nativos compilaron con cero errores y cero advertencias,
usando exclusivamente MetaEditor RoboForex `5.0.0.6230`, destino `X64 Regular`.
Código de referencia: `6c6f464`. Artefactos, logs y registro de hashes local:
`_storage/collector-builds/20261105-223601/` en la raíz del workspace.
No se sustituyeron los collectors existentes. El usuario confirmó la carpeta de
Juampi `284E06169E93AFCBDA6CBFE3E3CC0639`; se copiaron solo los cuatro scripts
en `MQL5/Scripts/TradingLabTests_20261105_223601`, verificando sus hashes.
El usuario ejecutó las cuatro pruebas y reportó `0 failure(s)` entre 23:08 y
23:09 del 2026-11-05 según Expertos. `encoding_failed` fue un fallo inyectado
por la prueba Activity, no una incidencia del EA instalado. Se preservaron los
dos collectors anteriores con hashes en `previous-installed-juampi/` dentro del
build local, sin leer configuraciones privadas ni modificar EAs de trading.
La instalación de los collectors nuevos y la validación del flujo local siguen
pendientes. Sus logs JSONL se revisarán durante ese corte supervisado.

- **Relay y concurrencia:** conservar por ahora el worker síncrono. Los 250 ms
  son una pausa posterior al ciclo, no una frecuencia garantizada. Antes de
  ampliarlo, observar backlog y retraso por fuente; evaluar drenaje acotado y
  concurrencia entre fuentes independientes, manteniendo un envío por fuente.
  Agrupación HTTP y prioridad de estado reciente frente a backfill requieren
  definir ACKs parciales, idempotencia y orden; no adelantar mensajes de una
  misma fuente a ciegas.
- **Retención de la outbox:** PY06 ya excluye los ACKed de la cuota de 100.000
  mensajes activos. Las huellas confirmadas siguen creciendo físicamente.
  Antes de operación prolongada, acordar horizonte de reenvío/deduplicación,
  conservación de controles de secuencia y tratamiento de Activity fuera de
  orden. Separar retención lógica de compactación física. Nunca podar pendientes
  o rechazados automáticamente ni depender solo de la deduplicación central.
- **Bootstrap y operación persistente:** Tailscale, reglas de acceso, servicios
  y migraciones siguen siendo acciones explícitas y supervisadas. Windows tiene
  tareas opcionales; definir y probar persistencia en Mac/Linux después del
  piloto. CI y wrappers portables no certifican una instalación real.
- **Traslado o arranque vacío:** decidir por separado si se conservan datos de
  prueba y cómo se recupera el historial. Una base nueva no obliga a los EAs a
  reenviar todo; coordinar identidades, cursores, outbox y backfill sin borrados
  ni cambios de destino implícitos. Probar primero captura/recuperación local,
  luego conectividad remota y por último el arranque persistente.

La garantía de retención de cada snapshot Telemetry también queda como decisión
futura: definir primero si se requieren todas las muestras durante interrupciones;
no se implementa una outbox durable dentro del EA en esta revisión.

### Ajustes pendientes detectados en la instalación local

- El puerto predeterminado de `TradingLabTelemetry.IngestUrl` se corrigió de
  `8766` a `8776` en la rama de progresión de cuenta, Telemetry `0.3.1`. Compilado
  sin errores/advertencias; instalación pendiente. La instancia del piloto se
  había corregido manualmente. No se cambian instancias activas automáticamente.
- Renombrar en una transición futura la fuente configurada
  `juampi-demo-activity-v2` a un identificador descriptivo sin `v2`. Es un
  `SourceId` operativo, no el default genérico del código ni una versión de API.
  Coordinar EA, topología del relay, registro de fuentes en la base y referencias
  de configuración/documentación vigentes. El identificador participa en el hash
  de los cursores de MT5 y en los bindings de la outbox: no hacer reemplazo ciego,
  no reutilizar la cola con otra identidad ni borrar cursores. Definir continuidad
  histórica y validar deduplicación antes de aplicar el cambio. Durante la prueba
  actual se conserva el identificador existente.

Referencias oficiales MQL5:

- [`OnTradeTransaction`](https://www.mql5.com/en/docs/event_handlers/ontradetransaction):
  cola de eventos de transacción con capacidad 1024.
- [`OnTimer`](https://www.mql5.com/en/docs/event_handlers/ontimer): eventos pueden
  coalescer si hay uno pendiente o en ejecución.
- [`WebRequest`](https://www.mql5.com/en/docs/network/webrequest): síncrono y no
  disponible en Strategy Tester.
- [`ArrayBsearch`](https://www.mql5.com/en/docs/array/arraybsearch): nearest
  devuelve el índice más próximo si no encuentra el valor; comprobar igualdad
  antes de usarlo como búsqueda de pertenencia.

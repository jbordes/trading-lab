# Revisión inicial de diseño y rendimiento de collectors

**Fecha:** 2026-11-05

**Estado:** revisión estática inicial y parcial; no es una auditoría completa ni
incluye benchmarks.

**Alcance:** Python en `src/`, `scripts/` y `tests/`; MQL5 solo para los dos
collectors del repositorio y sus includes.

**Base revisada:** `6d697fc`, rama
`chore/python-design-collector-performance-review`.
**Guías consultadas:** `_storage/python_performance_guide.md` y
`_storage/mql5_performance_guide.md`; se leyeron como referencias, sin copiarlas
a Git ni convertir sus recomendaciones en obligaciones universales. En MQL5,
esta revisión se limita a rendimiento; no abre otro refactor general de diseño.

## Criterio

Se revisaron parcialmente persistencia, receptores, ingesta, relay y rutas de
métricas, además de los dos collectors MQL5. Los efectos confirmados describen
el flujo visible en código; no se midieron latencias ni se atribuyen impactos
cuantitativos sin benchmark.

Aplicar estructuras proporcionales al tamaño, scans e I/O acotados, memoria
limitada, paginación y trabajo incremental. No recomendar `pandas`, `numpy`,
Numba, cachés ni concurrencia por defecto. Preservar precisión con `Decimal`,
validación externa, idempotencia y ACK posterior al commit. SOLID, DRY y YAGNI
son criterios pragmáticos: no proponer interfaces por clase ni capas sin
necesidad demostrada. Este documento propone evaluación; no implementa fixes,
instalaciones, tests nativos ni benchmarks.

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
  HTTP FastAPI añadida queda pendiente de ejecutar en un entorno con sus
  dependencias instaladas.

### PY04 — Métricas de ciclos con potencial de escalabilidad

- **Prioridad:** media; candidato de escalabilidad, no bug. **Ubicación:**
  `dashboard/telemetry_v2.py`, `cycle_performance_metrics`.
- Procesar por 100 ciclos y limitar series a 1200 son controles positivos; cada
  cálculo recorre el rango y crea acumulador por EA. Memoria estructural O(EAs ×
  capacidad de series), no O(historial). Costo temporal no medido.
- **Propuesta:** separar resumen global de desglose por EA solicitado; valorar
  agregación incremental persistida solo si se justifica. No cachear historial
  completo.
- **Aceptación:** muchas EAs/páginas conservan resultados idénticos y memoria
  acotada.

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

### PY07 — Cobertura de paginación vuelve a parsear payloads

- **Prioridad:** media. **Ubicación:** `sqlite_store_v2.py`,
  `_has_complete_pagination_chain`.
- Filtra JSON y construye grafo con sets/dicts, estructuras adecuadas; vuelve a
  leer payloads para decidir cobertura. No se ha comprobado plan SQL concreto.
- **Propuesta:** evaluar proyección compacta/indexable; usar `EXPLAIN` en fixture
  antes de afirmar un plan o agregar índices.
- **Aceptación:** cadena incompleta nunca se declara completa; completa mantiene
  resultado.

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

## Cobertura y siguiente revisión

Persistencia, receptores, ingesta, relay y rutas de métricas tienen revisión
parcial, no método por método. Pendiente revisión completa de autenticación y
servicio web del dashboard, métricas de ciclos y detalle de operaciones,
configuración/secretos, backup, jobs, bootstrap, CLI y harness/tests.

Orden actualizado tras la decisión de aplazar la revisión de collectors y
pruebas manuales hasta el final:

1. PY01, PY02, PY03 y PY06 están implementados en la rama de revisión; PR/CI y
   merge humano siguen pendientes.
2. Continuar con PY04 y PY07 mediante cambios pequeños, pruebas afectadas y sin
   agregar cache ni agregación persistida sin evidencia.
3. Evaluar PY05 cuando haya conectividad remota y mediciones representativas.
4. Al final, retomar MQ01/MQ02 y las pruebas manuales MQL5.

La garantía de retención de cada snapshot Telemetry también queda como decisión
futura: definir primero si se requieren todas las muestras durante interrupciones;
no se implementa una outbox durable dentro del EA en esta revisión.

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

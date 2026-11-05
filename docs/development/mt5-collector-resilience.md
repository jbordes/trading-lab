# Collectors MT5: recuperación y trabajo acotado

Estado: en Juampi se instalaron bajo supervisión Telemetry `0.2.1` y Activity
`activity-0.7.1`; los cuatro scripts nativos actualizados pasaron con cero fallos.
Se verificaron ACK central, logging JSONL y pruebas operacionales EA→relay para
401/403 el 2026-11-05. Siguen pendientes la desconexión del broker y la prueba
nativa con historial denso. Por decisión del usuario, esta última queda fuera del
alcance y de los criterios de cierre de este PR; se retomará en una tarea futura.
El usuario considera suficientes por ahora las pruebas realizadas. La carga
sintética local está descrita abajo; no es una prueba end-to-end ni un SLO.

Rama: `feature/mt5-collector-resilience`, desde `fix/relay-multiple-listeners`.
Runtime instalado: Telemetry `0.2.1`, Activity `activity-0.7.1`. Se preservaron
con hashes verificados los binarios previos en
`_storage/collector-releases/2026-11-05-before-logging`; el ZIP antiguo del socio
permanece intacto. No se modificaron EAs de trading, inputs ni cursores.
Contratos v1/v2, rutas, identidades y claves de cursor existentes se conservan.
No requiere migrar SQLite ni cambiar API, base de datos o tokens.

## Estados y recuperación

- Broker desconectado o lectura de identidad no disponible: esperar sin matar
  el timer. No capturar, enviar ni avanzar cursores. Al reconectar se exige otra
  vez la cuenta demo y servidor autorizados antes de continuar.
- Arranque sin conexión: el timer puede esperar; Activity inicializa la
  recuperación cuando dispone de identidad aprobada y tiempo de servidor válido.
- Cuenta/servidor diferentes o modo no demo: parada permanente y revisión humana.
- HTTP 401/403: acceso bloqueado con sondeo cada 60 segundos. Activity conserva
  el mismo cuerpo/identidad y cursor; reanuda al recibir 200/202, sin recargar EA.
- Red, 408/429 y 5xx: backoff 2..60 segundos. Otros rechazos, incluidos 400/409,
  requieren revisión; no se reintenta indefinidamente un mensaje inválido.
- Telemetry conserva una FIFO volátil de 12 muestras. El acceso bloqueado no
  descarta inmediatamente la cabeza, pero la captura sigue y un desborde puede
  reemplazar muestras antiguas. Los descartes se cuentan y sus logs se limitan.
  Las muestras vivas no tienen la misma garantía histórica que Activity.
- Activity mantiene el cursor anterior hasta completar lote, páginas y evidencia
  de posición. Se conserva el flush durable; no se elimina para ahorrar E/S.

## Recursos y responsabilidades

`TradingLabCollectorCommon.mqh` contiene validación y escape JSON, identificadores,
tiempos, política de identidad y transporte/backoff con estado privado. El escape
incluye caracteres de control. Los tokens locales se validan como ASCII imprimible
sin espacios, 24..512 caracteres, sin el placeholder inicial.

`TradingLabActivityState.mqh` agrupa lote pendiente, paginación, preparación y
escaneo. Los collectors permanecen separados: compartir helpers no iguala sus
políticas de retención. No se añadieron DLL, hilos, SQLite ni red al callback de
transacciones; los hints son una cola fija de 128 entradas mínimas.

Activity:

- Máximo 200 candidatos de posición, sin redimensionar el array por candidato.
  Solo se añaden candidatos de los registros emitidos.
- Las ventanas densas se reducen una vez por timer, comprobando conteos antes de
  serializar el historial completo. No se publica el sentinel interno de división.
- Las páginas se preparan mediante escaneo reanudable: por defecto hasta 500
  registros por ciclo (`MaxHistoryRowsPerCycle`, permitido 10..2000) y presupuesto
  cooperativo de 25 ms (`CycleBudgetMs`, permitido 1..100). Conserva como máximo
  `MaxItemsPerCollection` claves. Si cambian los conteos seleccionados, reinicia
  el escaneo; el fingerprint entre páginas sigue detectando cambios de selección.
- Reconcilia hasta dos candidatos por ciclo, cediendo también por presupuesto.
- Entre páginas confirmadas se alternan los carriles reciente e histórico cuando
  ambos tienen trabajo. Nunca se cambia el lote en vuelo para conseguir prioridad.
- Drena hints antes de reintentar y permite heartbeat entre unidades de
  reconciliación. Un envío pendiente aún bloquea otros envíos del mismo EA.

Telemetry mantiene su cadencia de snapshots. El historial v1 usa una muestra
cacheada y se relee por defecto cada 60 segundos (`HistoryIntervalSeconds`) o ante
actividad de trading/arranque. La ventana histórica conserva sus tiempos reales;
no se presenta esa muestra histórica como si se hubiese seleccionado de nuevo.

Estos límites acotan el trabajo propio, no garantizan un límite duro para toda
la llamada nativa `HistorySelect`, su memoria interna, la serialización o
`WebRequest`. Esta última sigue siendo síncrona y con timeout; bloquea el hilo
del collector, no directamente los hilos de los otros EAs. No se afirma un
consumo óptimo ni una mejora porcentual sin una prueba controlada de carga.

## Compilación y pruebas

### Prueba operacional supervisada de 401/403 (EA → relay)

La utilidad `scripts/collector_access_probe.py` sustituye temporalmente ambos
listeners del relay, solo en loopback, sin abrir bases, leer archivos de secretos,
guardar mensajes ni responder ACK. No es un relay ni sirve `/health`. Su salida
solo muestra hora UTC, ruta fija y código HTTP; no contiene headers ni payloads.

1. Solo en Juampi demo, detener el relay con Ctrl+C. Mantener MT5, collectors,
   API y dashboard abiertos. No modificar inputs, tokens, cursores ni cola.
2. Desde la raíz de esta rama, ejecutar:

   ```text
   uv run python scripts/collector_access_probe.py --status 401 --seconds 180
   ```

3. Esperar un rechazo de cada ruta y un segundo intento de cada una unos 60 s
   después de su primer rechazo. La llegada inicial de Activity depende del
   siguiente lote o heartbeat. Si no alcanza el plazo, repetir el escenario;
   la ausencia de tráfico no demuestra un rechazo ni recuperación.
4. Parar la utilidad con Ctrl+C antes de iniciar el relay original, con su misma
   cola y configuración. También se detiene automáticamente a los 180 s; no
   reinicia el relay. Observar la recuperación hasta al menos 90 s después.
5. Esperar `receiver_access_blocked` y después `RESOLVED`, sin recargar EAs.
   Activity debe conservar el lote/identidad pendiente y no adelantar su cursor
   hasta confirmación. Telemetry puede descartar snapshots al llenar su FIFO;
   no exigir continuidad de todas las muestras vivas.
6. Tras confirmar recuperación y ACK central, repetir con `--status 403`.

La prueba valida la reacción del collector al código HTTP, no las reglas reales
de autenticación/autorización ni la frontera relay → API. No dar por validada la
inmutabilidad del cursor/lote solo por el log de recuperación: contrastar identidad
y cobertura con evidencia del receptor, sin exponer secretos ni cuerpos en logs.
Las pruebas nativas cubren las invariantes internas. Registrar por separado cada
código, rutas observadas, recuperación, descartes y cualquier evidencia faltante.
No detener MT5: eso prueba reinicio, no desconexión del broker con el EA activo.

### Resultado operacional 401/403 — 2026-11-05

En Juampi el usuario confirmó `RESOLVED` tras restaurar el relay en ambos
escenarios. Las observaciones UTC registradas fueron:

| Escenario | Telemetry v1 | Activity v2 |
| --- | --- | --- |
| HTTP 401 | 00:09:47, 00:10:47, 00:11:47 | 00:08:59, 00:10:09, 00:11:09 |
| HTTP 403 | 00:16:57, 00:17:57, 00:18:57 | 00:17:09, 00:18:09, 00:19:09 |

Son marcas de los rechazos observados, no una auditoría completa de cursor,
deduplicación o cobertura. No se afirma aquí que la inmutabilidad del cursor o la
deduplicación hayan quedado demostradas operacionalmente; los tests nativos
cubren las invariantes internas. La desconexión real del broker sigue pendiente.

El cierre del probe se corrigió para llamar `server_close()` desde el context
manager. Pasaron cinco tests del probe, incluidos cierre, timeout, Ctrl+C y fallo
de bind parcial.

### Carga sintética del relay local — 2026-11-05

Comando reproducible desde la raíz del checkout:

```powershell
.venv\Scripts\python.exe tests/manual/activity_load_probe.py
```

La prueba usó `TestClient`, no sockets HTTP reales ni MT5. Generó 20 ventanas con
100 deals y 100 órdenes cada una, más 1.000 reconciliaciones de posición: 1.020
mensajes en total, cinco EAs, 2.000 deals, 2.000 órdenes y 1.000 ciclos cerrados.
La cola persistió y reabrió; después de un ACK perdido tras el commit central,
reintentó y repitió todos los mensajes. Los conteos paginados no tuvieron
duplicados y quedaron cero pendientes.

Tiempo total: 34.685 s; 7.301 s de preparación y encolado; 24.799 s de reenvío y
replay. La outbox ocupó 3.526.656 bytes después de los ACK. Las bases temporales
aisladas usaron fixtures limpios y se limpiaron al terminar; no se tocaron datos
operativos. No es un SLO, una medición de RAM, una prueba nativa con historial
denso ni una carga end-to-end con sockets o MT5.

En esta VPS el compilador autorizado es únicamente
`C:\Program Files\MetaTrader 5- Roboforex\metaeditor64.exe`. Cualquier otra
instalación requiere consentimiento explícito. Compilar fuentes del workspace
no autoriza instalar o ejecutar collectors ni scripts en una terminal.

Pruebas nativas, sin red ni trading en su ejecución:

- `tests/mql5/collector_common_test.mq5`: estados, backoff, identidad y JSON.
- `tests/mql5/telemetry_outbox_test.mq5`: FIFO real, ACK, desbordes, recuperación
  de acceso y datos inválidos.
- `tests/mql5/activity_collector_test.mq5`: cuerpo/cursor inmutables ante rechazo,
  ACK y flush, heartbeat sin avance, página densa reanudable, alternancia de
  carriles y evidencia de posición. Accesos de plataforma sustituidos por dobles.

Compilar no equivale a ejecutar estas pruebas. Antes de instalar, ejecutarlas
de forma supervisada en la terminal de pruebas y exigir `0 failure(s)` para cada
script. Después verificar desconexión/reconexión del receptor, ausencia de cambios
en trading, continuidad de cursores y tiempos de procesamiento con historial denso.
Las pruebas Python dirigidas protegen también límites y helpers de solo lectura;
no sustituyen una ejecución MQL5 ni un benchmark operacional.

## Instalación supervisada y validación operacional

### Incidencia detectada en la prueba manual del 2026-11-04

Los tres scripts originales finalizaron con cero fallos; sin embargo, Activity
falló al arrancar con `StringToCharArray=0`, error MQL5 `4009`
(`ERR_NOTINITIALIZED_STRING`), sin enviar HTTP. El estado agrupado no inicializaba
explícitamente las cadenas del lote y de paginación. El timer podía interpretar
el cuerpo inicial como pendiente. El test anterior asignaba un cuerpo de fixture
antes de probar el envío y no cubría el arranque con estado intacto.

Se añadieron constructores explícitos, una regresión nativa del estado inicial y
un resultado local de codificación separado de HTTP: detiene sin avanzar cursor
ni atribuir el fallo al receptor. Activity y el test actualizado compilan sin
errores ni advertencias. El operador ejecutó la regresión actualizada con cero
fallos y volvió a adjuntar Activity a las 23:21 (Europe/Madrid). La consulta de
solo lectura confirmó cinco mensajes v2 nuevos, todos con ACK central, sin cola
pendiente ni rechazos. Esto valida el arranque y envío, no sustituye las pruebas
de desconexión, pérdida de ACK ni carga. Los binarios anteriores se preservaron fuera de
Git, con hashes verificados, para el socio y rollback. No confundirlos con los
binarios nuevos inicialmente compilados ni con este fix.

El relay incorpora diagnósticos de códigos fijos para distinguir validación y
framing, sin retener cuerpos, cabeceras ni valores de errores no confiables.
No se relajó validación ni autorización para tratar esta incidencia.

### Corte supervisado del relay

El operador realizó el corte breve acordado. Activity registró reintentos del
mismo lote; Telemetry registró un retorno `1001`, etiquetado incorrectamente como
HTTP. Tras restablecer el relay se verificaron mensajes v1 y v2 nuevos con ACK
central, cero pendientes y cero rechazos. El heartbeat de Activity indicó ambos
carriles sin bloquear, cero hints descartados y solape de cursores de 5 segundos.
La cobertura persistida alrededor del corte permanecía continua hasta el último
rango confirmado (00:31:51 del broker), sin lotes incompletos. Esto no prueba la
conservación de todos los snapshots intermedios de Telemetry ni simula pérdida de
ACK, cambios de cuenta o desconexión del broker.

El cambio preparado incorpora logging local acotado para distinguir retornos de
transporte y registrar errores locales de WebRequest. El código `1001` no se
etiqueta como HTTP. Los fallos de logging no detienen la captura; ante error de
E/S se reintenta con intervalo mínimo de 60 segundos. La escritura es síncrona,
pequeña y limitada en frecuencia, no tiene una garantía dura de latencia del
disco. `OnTradeTransaction` no realiza E/S de logging.

El logger agrupa por código en una tabla en memoria de 32 entradas: cada código
se registra al aparecer y luego como máximo una vez por minuto; al cerrar la
incidencia registra un resumen final. Los campos JSON son `time_utc`, `level`,
`collector`, `source_id`, `version`, `code`, `detail` (máximo 384 caracteres),
`sequence`, `transport_status`, `local_error`, `occurrences`, `suppressed` y
`elapsed_ms`. Solo registra `WARN`, `ERROR` y `RESOLVED` en el cierre; no registra
INFO ni eventos healthy de inicio/parada. Los Expertos registran únicamente
errores críticos y un aviso si falla el sink o se agota la cuota.

La ruta por terminal es `MQL5\Files\TradingLab\logs\`, con nombres
`<telemetry|activity>-<SourceId>-YYYYMMDD.jsonl`; `:` de SourceId se sustituye
por `~` y la fecha es UTC. No usa `FILE_COMMON`. Cada archivo tiene máximo 1 MiB
por día y fuente; al excederlo suspende escrituras hasta el siguiente día UTC y
avisa una vez. La retención es de 14 días y solo elimina archivos propios con
fecha exacta; el cleanup examina como máximo 64 entradas al primer log del día.
No borra cursores, bases ni archivos ajenos.
La carpeta y el archivo se crean al primer warning o error, no por cada snapshot
ni durante un arranque saludable. Un apagado abrupto puede perder el resumen de
avisos todavía suprimidos; los logs son diagnóstico best-effort, no un ledger de
trading ni un reemplazo del outbox y la reconciliación.

La prueba nueva `tests/mql5/collector_logger_test.mq5` usa dobles de filesystem,
reloj y `Print`, sin acciones reales, y cubre agrupación JSON, rate limit,
recuperación, cuota, rotación, retención propia y fallos de E/S. El usuario
ejecutó los cuatro scripts nativos actualizados con cero fallos. Los collectors y
los cuatro scripts compilaron con 0 errores y 0 warnings usando RoboForex. Las
pruebas Python de logging comprueban integración y guardas de fuente; no ejecutan
MQL5.

### Aceptación operacional del logging (2026-11-05)

Tras ejecutar los cuatro scripts actualizados con cero fallos, se instalaron bajo
supervisión en Juampi los dos `.ex5`, los tres headers (`TradingLabCollectorCommon.mqh`,
`TradingLabActivityState.mqh` y `TradingLabCollectorLog.mqh`) y los dos `.mq5`.
Los hashes de los archivos instalados se verificaron. Las consultas de solo
lectura a la API y su base confirmaron ACK central con las versiones nuevas.
No se tocaron EAs de trading, inputs ni cursores.

En el corte breve del relay, Telemetry escribió en su archivo JSONL del día UTC
`20261104` un `WARN` a `2026-11-04T23:07:59Z` y `RESOLVED` a
`2026-11-04T23:09:12Z`: cinco ocurrencias, cuatro suprimidas, 72.985 s de
duración, secuencia inicial 21 y resuelta 25. También registró un único
`snapshot_dropped` con `reason=retry_limit` (`occurrences=1`), conforme a la
política vigente; no fue un desborde y no se oculta ni se interpreta como prueba
de recuperación de todos los snapshots.

Activity escribió `WARN` a `2026-11-04T23:08:01Z` y `RESOLVED` a
`2026-11-04T23:09:29Z`: cinco ocurrencias, cuatro suprimidas, 87.984 s y la misma
secuencia 3 en ambos registros. Los archivos están en
`MQL5/Files/TradingLab/logs/` con nombres por collector, SourceId y fecha UTC;
las horas UTC del 4 de noviembre corresponden al 5 de noviembre en Madrid.

Tras restablecer el relay, la salud indicó cola, pendientes, rechazos y errores
en cero; los datos v1/v2 volvieron a recibir ACK central. Esto valida el corte
breve y los eventos de logging observados, no todos los snapshots de Telemetry,
ni las pruebas de carga, 401/403 o desconexión del broker. Mantener inputs,
tokens, SourceIds y cursores; no borrar variables `TL2.ACT.*`, recrear la base ni
reiniciar EAs de trading para este cambio. Registrar versión y hashes siguiendo
[la operación de collectors](mt5-collector-operations.md).

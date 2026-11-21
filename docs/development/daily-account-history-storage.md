# Persistencia del histórico diario de cuenta

Estado: implementado en rama y probado con bases temporales. No migrado ni
activado en servicios operativos. Dirección: [ADR-0023](../adr/0023-daily-observed-account-history.md).

## Esquema y garantías

La única SQLite central pasa de `user_version=7` a `8`. Las instalaciones
nuevas mediante bootstrap o `create_central_db.py` crean directamente esquema 8.
Los contratos y endpoints no cambian de nombre por este cambio de esquema.
Antes de desplegar el esquema 8 se añadió también `compacted_broker_day` a
`telemetry_messages`: `NULL` identifica contenido original; una fecha identifica
una muestra cuyo contenido fue compactado. La restricción SQL exige entonces
`payload_json='null'`. Se conservan las demás columnas y el hash del contenido
original, no el hash de ese marcador. No se trata de un mensaje wire nuevo.

`account_daily_observations` añade una fila por `(account_id, broker_day)`:

| Datos | Significado |
| --- | --- |
| `source_id`, `close_message_id` | Fuente snapshot de la cuenta y mensaje original del cierre observado |
| `first_captured_at_utc`, `close_captured_at_utc` | Primera y última captura del día, en UTC |
| `close_broker_time` | Fecha/hora real del broker de la captura final; no medianoche supuesta |
| `balance`, `equity`, `floating_pnl` | Últimos valores observados, decimales almacenados como texto |
| `min_balance`, `max_balance`, `min_equity`, `max_equity` | Extremos de las capturas disponibles, no extremos exactos del mercado |

La consolidación (`persist_daily_account_history`) recibe una cuenta, un día
cerrado y la fecha actual del broker proporcionada por el llamador. Verifica
esquema, fuente, hashes y metadatos; lee secuencialmente las capturas candidatas,
sin cargar un día entero en memoria. Usa el índice existente de fuente/UTC y el
margen de plausibilidad del contrato (14 horas y 2 segundos) para acotar la
búsqueda. Ese margen no convierte relojes ni deduce offsets históricos.

Solo las capturas con `server_time_msc` válido pueden asignarse a un día del
broker. Sin capturas válidas no se inserta un punto ficticio. El día actual no
puede cerrarse. Las llegadas tardías recalculan el día de forma idempotente;
los cierres contradictorios o datos corruptos abortan sin sustituir el resumen.

Lectura y actualización transcurren en una transacción `BEGIN IMMEDIATE` con
plazo cooperativo de tres segundos y espera de bloqueo de 100 ms. Un fallo
revierte el cambio. No hay jobs nuevos activos ni segunda base de negocio.

## Migración supervisada

**No ejecutar todavía en el piloto por rutina.** Primero coordinar el corte,
detener los servicios que usan la base y realizar una copia consistente y
verificada con las herramientas de backup del proyecto. Conservar esa copia
sin sobrescribirla: es el mecanismo de vuelta atrás; no hay downgrade automático.

Desde el repositorio, con su entorno preparado:

```text
uv run python scripts/migrate_daily_account_history.py --db RUTA/central.sqlite3
```

Por defecto es una inspección de solo lectura: valida versión, estructura e
integridad e informa el paso 7 → 8, sin crear tablas. Para aplicar tras la
aprobación del corte y el backup:

```text
uv run python scripts/migrate_daily_account_history.py --db RUTA/central.sqlite3 --apply
```

Solo admite el esquema 7 exacto o el 8 ya actualizado; rechaza estructuras
desconocidas y rutas inexistentes. DDL, versión y verificación final forman una
única transacción: una excepción revierte tabla y versión. No modifica cuentas,
fuentes, mensajes, tokens ni cursores. Repetir sobre esquema 8 es un no-op.

**Compatibilidad:** el nuevo código exige esquema 8 al abrir la base. El piloto
que sigue ejecutándose con esquema 7 no debe reiniciarse con este código hasta
completar el corte aprobado. Reiniciar no sustituye a migrar.

## Retención implementada, todavía sin activar

Se conservan muestras completas del día actual y de los seis anteriores según
la fecha del broker. Para días más antiguos, `compact_account_samples` consolida
el día y compacta como máximo 1000 contenidos por transacción. Mantiene:

- El mensaje original del cierre diario, protegido por su referencia única.
- Las identidades, secuencias, tiempos de captura/recepción, versiones y hashes
  originales, para reconocer reenvíos y rechazar identidades reutilizadas.
- El resumen diario, incluidos primera captura y extremos ya consolidados,
  aunque lleguen muestras atrasadas después de compactar las anteriores.
- Las capturas sin hora del broker verificable y las que tienen historial
  embebido, incluso vacío. No se borra evidencia histórica por inferencia.
- El último estado de cuenta; la compactación no obliga a esperar un dato nuevo.

El ACK de un reenvío conocido sigue siendo idempotente. El cuerpo original no se
recrea ni se vuelve a insertar; una identidad conocida con otro hash sigue
produciendo conflicto. Las lecturas de muestras y referencias financieras no
interpretan el marcador compacto como si fuera un snapshot válido.

Los lectores conservan acceso al cierre original diario. El inspector cuenta
también las identidades compactadas como snapshots recibidos, no como fallos.
La compactación no modifica tablas de órdenes, deals, cobertura o ciclos.

La operación tiene vista previa de solo lectura y debe aplicarse únicamente con
aprobación y un backup consistente. Ejemplo genérico, desde el repositorio:

```text
uv run python scripts/compact_account_samples.py --db RUTA/central.sqlite3 --account-id CUENTA --broker-day 2026-10-15 --current-broker-day 2026-11-06
```

`--current-broker-day` debe ser la fecha actual verificada del broker, no la
fecha local del servidor ni un valor futuro de conveniencia. La ejecución no
consulta MT5 para verificarla. Por defecto no se modifica nada. Tras revisar
cuenta, fecha y vista previa, `--apply` autoriza ese lote; `--max-messages` permite
reducir su tamaño (1–1000). Si `more_pending` es `true`, quedan lotes del mismo día.

Consolidación y compactación ocurren bajo la misma transacción y plazo cooperativo
de tres segundos. Un error revierte ambas. El código no crea tareas programadas,
no reinicia servicios, no migra implícitamente y no ejecuta `VACUUM`. Un día que
exceda el presupuesto aborta sin avanzar; no se declara compactado ni se entra en
un reintento infinito. Deberá revisarse el presupuesto o procesamiento incremental
antes de habilitar automatismos para historiales de esa densidad.

`payload_bytes_releasable` mide la reducción de contenido, no cuánto se encoge el
archivo en disco. SQLite puede reutilizar las páginas liberadas; las identidades
ligeras siguen creciendo con los mensajes recibidos. No se promete tamaño total
constante ni se elimina su deduplicación sin una política separada.

## Consulta unificada y gráfico

Implementados en rama: `GET /api/accounts/evolution?source_id=SOURCE&from_msc=START&to_msc=END`,
con permiso de lectura de cuenta y rango UTC inclusivo/exclusivo. La respuesta
`daily_close_and_recent` combina los cierres guardados con muestras del último
día observado todavía no representado por un cierre. Cada punto declara
`resolution: daily|recent`, hora real UTC y fecha/hora del broker cuando existe.
No devuelve dos balances alternativos ni equipara PnL con equity.

Los puntos diarios se contrastan con el mensaje original de cierre. Las muestras
recientes se reducen con búsquedas indexadas, conservando como máximo 480 puntos
totales y un presupuesto cooperativo de tres segundos. El índice parcial
`telemetry_messages_uncompacted_capture` evita recorrer identidades compactadas
para encontrar cuerpos recientes. Forma parte del esquema 8 aún no desplegado
y de la misma migración explícita desde 7.

`recent_basis` identifica `broker_day`, `last_24h_unassigned` o `none`. La segunda
opción es una compatibilidad explícita con capturas sin reloj del broker; no
inventa su fecha. `unconsolidated_history` avisa de observaciones antiguas aún
pendientes de consolidar. La lectura no escribe ni ejecuta trabajos implícitos,
no extrapola valores y no promete cobertura continua en días sin muestras.

El dashboard usa `/api/account-evolution` mediante su sesión autenticada y el
cliente central de solo lectura. Desaparece el selector de reconstrucciones;
mantiene balance/equity en el mismo gráfico ECharts y rangos de 1 a 365 días.
En períodos abiertos agrega las nuevas capturas recibidas y refresca la consulta
como máximo cada 30 segundos. Las peticiones en segundo plano conservan la curva
y su zoom. El tooltip distingue cierre diario/captura reciente y hora del
broker/local, sin nuevos paneles grandes. Las rutas históricas de diagnóstico
`history` y `progression` permanecen separadas y ya no alimentan el gráfico principal.

Todo esto sigue pendiente de migración/activación supervisada, consolidación de
los primeros días, actualización del collector y revisión visual humana. Los
servicios en ejecución no se reiniciaron con este código.

## Mantenimiento diario integrado

El job existente `scripts/run_telemetry_maintenance.py` puede ejecutar copia,
consolidación y retención sin API, relay, dashboard ni acceso directo a MT5.
Trabaja sobre la SQLite local del host central; no accede al archivo por red.
La ausencia de la API puede impedir recibir nuevas capturas, pero no procesar
las que ya están guardadas.

Por compatibilidad, sin `--daily-account-id` mantiene el comportamiento de
backup únicamente. La vista previa de la modalidad diaria es:

```text
uv run python scripts/run_telemetry_maintenance.py --storage-root RUTA_DATOS --database central.sqlite3 --daily-account-id CUENTA
```

No crea copia, estado ni lock y no modifica datos. Para aplicar tras revisar la
vista previa y aprobar el corte, añadir `--apply`. Ese modo toma el lock existente,
crea primero una copia SQLite consistente y verificada y solo después ejecuta
trabajo diario. Si la copia falla, no consolida ni compacta. Solo el propietario
del lock publica el estado final.

La referencia de día procede de una captura íntegra con `server_time_msc`, no de
la fecha local del host. Se resta un margen de cinco minutos antes de cerrar el
día anterior. Nunca se adelanta un reloj del broker con el tiempo del servidor.
Si la referencia supera quince minutos, se procesa únicamente hasta su frontera
observada y se avisa `partial/stale_broker_clock`; no se afirma estar al día.
Sin referencia utilizable se difiere el trabajo (`deferred`), sin inventar fechas.
Las capturas del collector anterior sin ese campo siguen conservadas.

El esquema 8 todavía no desplegado incorpora `observed_broker_day` virtual y un
índice parcial para localizar días de capturas originales sin recorrer todos los
cuerpos ni las identidades compactadas. Cada resumen conserva
`last_processed_message_id`: una llegada tardía reabre su procesamiento aunque
su hora sea anterior al cierre, y repetir el job no lo procesa indefinidamente.
Estos elementos se crean tanto en el bootstrap limpio como en la migración 7 → 8.

Límites por defecto: hasta catorce días, treinta y dos lotes de mil contenidos y
sesenta segundos cooperativos de trabajo diario. `--daily-max-days` (1–31),
`--daily-max-batches` (1–128) y `--daily-budget-seconds` (1–300) permiten ajustar
el lote. El tiempo de copia es independiente de ese presupuesto. Cada unidad
confirmada queda durable; alcanzar un límite termina con trabajo pendiente,
sin bucle de espera o reintento. Una unidad demasiado densa puede fallar dentro
de su presupuesto de tres segundos: se conserva lo ya confirmado y se requiere
revisión operativa, no un relanzamiento automático ilimitado.

`operations/maintenance-status.json` puede terminar en `succeeded`, `partial`,
`deferred` o `failed`. Códigos: `0` vista previa/éxito, `1` fallo, `2` otro job
activo, `3` trabajo parcial o diferido. La copia verificada permanece disponible
incluso si falla un paso posterior; las copias no se eliminan automáticamente.

### Programación sin instalar nada por sorpresa

La entrada independiente `scripts/configure_telemetry_maintenance.py` prepara
**solo mantenimiento**, con base, cuenta y horario explícitos: Windows Task
Scheduler, cron en Linux y launchd en Mac (cron opcional). El procedimiento
completo, alcance y restricciones están en el
[manual de mantenimiento automático](automatic-maintenance.md).

El generador Windows combinado existente admite `--daily-account-id CUENTA` en
`scripts/configure_telemetry_windows_tasks.py`. Lo añade solo a la tarea de
mantenimiento a las 03:30 locales, no a la API. Por defecto sigue siendo vista
previa; no se reemplazan tareas existentes. El plan mantiene `IgnoreNew` y no
agrega reintentos automáticos del mantenimiento. Su `InteractiveToken` requiere
sesión de Windows iniciada, aunque TradingLab no tenga ventanas abiertas.

En los tres sistemas se programa la misma entrada Python con rutas absolutas
a `.venv`, al script y al data-dir; no hace falta resolver dependencias ni tokens
en cada ejecución. La instalación real de los schedulers queda para el ensayo
operativo supervisado. Desarrollar el instalador no registra tareas ni activa
compactaciones por sí solo.

## Validación local de este paso

El 2026-11-06 pasaron diez casos nuevos de almacenamiento/migración y los ocho
casos de la política diaria. Se verificaron reenvíos, llegadas tardías, cambio
de día, ausencia de reloj, integridad, conservación de mensajes y rollback.
El gate `scripts/check.py full` terminó correctamente: 53 tests de harness y
466 de producto, más formato, lint y comprobaciones del repositorio.

Durante la validación se actualizaron el inventario de tablas y el test del
fallo de almacenamiento de la API: este último usaba una fuente no registrada y
una frontera de inyección anterior, de modo que no alcanzaba el fallo pretendido.
También se corrigió el arranque independiente de los tests de progresión.
No se ejecutaron nuevas pruebas manuales de UI ni pruebas nativas de MT5, ni se
migró la base en uso o reiniciaron servicios.

Paso de retención, misma fecha: diez casos nuevos verificaron vista previa,
ventana de siete fechas, lotes y repetición, extremos tras llegadas tardías,
conservación de cierres/estado actual, historial embebido, ausencia de reloj,
rollback y confirmaciones/conflictos por HTTP después de compactar. El gate
completo volvió a pasar con 53 tests de harness y 476 de producto. La base
operativa, los collectors y los servicios permanecieron intactos.

Paso de consulta unificada, misma fecha: once tests nuevos verificaron composición
sin duplicados, invariancia tras compactar, datos pendientes sin escrituras,
ausencia de reloj del broker, ventanas vacías y borde exclusivo, corrupción,
límite de puntos con 600 capturas, autorización, errores y validación del cliente.
La sintaxis JavaScript pasó `node --check`. El gate completo pasó con 53 tests
de harness y 487 de producto. La revisión visual humana y activación siguen
pendientes; estas comprobaciones no sustituyen el ensayo operativo en MT5.

Paso de mantenimiento, misma fecha: diez tests del coordinador verificaron
repetición, llegadas tardías, reloj ausente/atrasado, margen de medianoche,
límites de días/lotes/tiempo y ejecución del comando real con backup previo,
usando únicamente bases temporales. Cuatro casos añadidos al job comprueban
orden copia/trabajo, fallo de copia, estado parcial y vista previa sin efectos;
otro comprueba la opción declarativa Windows. El gate completo terminó con
53 tests de harness y 502 de producto aprobados. Se protegió el cálculo de la
columna virtual frente a JSON inválido para preservar su rechazo por integridad.
No se instalaron schedulers ni se migraron datos operativos.

## Activación supervisada del backend del piloto

El 2026-11-06, después de las validaciones anteriores y con aprobación humana,
se detuvieron exclusivamente API, relay y dashboard del piloto Juampi. Se creó
una copia SQLite consistente del esquema 7, con integridad y hash verificados,
y se aplicó la migración a 8. Los recuentos de todas las tablas preexistentes
se conservaron; el esquema resultante, integridad y claves foráneas pasaron.
Los tres servicios reiniciaron con los mismos archivos privados, fuentes y
base, sin modificar MT5 ni sus EAs. El relay volvió a recibir ACK central y
quedó sin pendientes ni errores.

La lectura autenticada API → dashboard devolvió 479 puntos recientes, dentro
del límite de 480. La vista previa del mantenimiento quedó correctamente
`deferred / broker_clock_unavailable`: el Telemetry 0.3.0 aún instalado no
publica el reloj necesario. No se compactaron muestras ni se inventaron fechas
del broker. La sustitución supervisada por Telemetry 0.3.1, su prueba nativa y
la validación visual humana siguen pendientes; Activity permanece sin cambios.
No se instalaron tareas programadas.

Evidencias locales, fuera de Git: `_storage/daily-activation-20261106T191300719728Z.json`
y copia previa en
`_storage/backups/central-unified-pilot-20261106T191303305336Z-fe1c2f7203f5/`.

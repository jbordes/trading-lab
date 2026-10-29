# Persistencia y composición aisladas de telemetría v2

**Estado:** activo como piloto local opt-in; la migración a esquema 4 está
implementada en código pero todavía no fue aplicada a la base de Juampi.

## Objetivo y límites

Este incremento convierte las reglas de admisión v2 en evidencia durable y permite
componer una cuenta sin mezclar estado vivo con actividad histórica. No migra ni
modifica bases v1 ni instala collectors. `create_v2_database` solo crea un archivo
nuevo solicitado explícitamente y nunca reemplaza uno existente; la migración v2
es una acción operativa separada y con guarda explícita.

El esquema vive en `src/tradinglab/telemetry/sqlite_store_v2.py`, usa
`PRAGMA user_version = 4` y se abre únicamente si coincide exactamente con el
esquema esperado. Una base v1 no se acepta como v2. La migración admitida es solo
de v2 esquema 3 a 4, exige una copia nueva verificada y no se ejecuta al abrir el
receptor.

## Identidades y seguridad

SQLite conserva cuentas internas, identidad MT5 enmascarada y dos fuentes con rol
`live` o `activity`. Existe como máximo un productor primario por cuenta y rol;
cuenta y rol de una fuente son inmutables. Los tokens nunca se guardan en la base.
La autenticación permanece en `V2ProducerDirectory` y la escritura durable vuelve
a comprobar cuenta, fuente, rol e identidad sobre el mensaje revalidado.

## Escritura transaccional

Cada mensaje se canoniza y guarda con hash SHA-256, captura, recepción y procedencia.
La transacción `BEGIN IMMEDIATE` decide de manera atómica:

- reintento idéntico: devuelve `duplicate` sin cambiar la recepción original;
- misma fuente/sesión/secuencia con otro contenido: conflicto y rollback;
- `live_snapshot` o `heartbeat` desconocido por debajo del máximo: rechazo;
- `activity_batch` histórico desconocido: aceptación fuera de orden;
- salto hacia delante: aceptación con cantidad de secuencias faltantes como
  diagnóstico, nunca como cobertura.

Las pruebas cubren concurrencia y fallos antes o después de un commit. Si la
confirmación fue ambigua, reabrir y reenviar produce exactamente una fila.

## Lectura y composición por cuenta

`account_evidence` lee fuentes y mensajes dentro de una única transacción y antes
de devolverlos verifica contrato, hash, columnas, identidad y rol. La composición
pura de `composition_v2.py` produce:

- estado vivo más reciente admisible, independiente de heartbeat;
- diagnóstico de ambos flujos y heartbeat por rol;
- órdenes y deals históricos por ticket, sin mezclarlos entre sí;
- correcciones por tiempo de observación, sin retroceder por orden de llegada;
- cobertura unida solo desde colecciones `complete`;
- estados `error` y `truncated` sin extender cobertura;
- conflictos entre sesiones, conservando la última evidencia no ambigua;
- rechazo de capturas futuras para estado y cobertura.

La composición no afirma que ambos flujos formen una fotografía atómica. Una orden
cancelada sigue siendo actividad, no un trade ni P/L. Las fórmulas de métricas y
agrupación de ejecuciones continúan dependiendo del contrato acordado con el socio.

## Historial consultable

Cada `activity_batch` admitido proyecta sus observaciones y su cobertura dentro de
la misma transacción que el mensaje original. Los reintentos idénticos no duplican
la proyección. Deals y órdenes permanecen separados; las colecciones `truncated` o
`error` se conservan pero no afirman cobertura completa.

`activity_page` consulta por cuenta, tipo, período y Magic Number mediante
paginación keyset de hasta 100 filas. SQLite resuelve correcciones por instante de
captura y conserva la última observación no ambigua si dos sesiones discrepan. La
consulta no llama a `account_evidence` ni reconstruye el historial completo en
RAM. `coverage_report` une solamente intervalos `complete` y cuenta lotes
incompletos superpuestos.

## Ciclos de posición durables

Un mensaje `position_reconcile` proyecta, en la misma transacción, una observación
append-only del ciclo identificado por `account_id + position_id`. Conserva Magic
propietario y observados, deals, resultado neto, volumen remanente, clasificación
y motivos de exclusión. `position_cycles` resuelve la última observación no ambigua
por posición y permite filtrar por Magic propietario sin cargar mensajes ni el
historial completo en memoria. Los deals y el mensaje original siguen siendo la
evidencia auditable; la proyección es reconstruible.

El esquema 4 no convierte automáticamente rangos históricos en ciclos. Solo usa
evidencia `position_reconcile`, porque una ventana temporal equilibrada no prueba
por sí sola que contenga la vida completa de una posición.

La composición completa sigue siendo la referencia semántica para diagnóstico, no
el camino de refresco del dashboard. Una caché futura deberá ser acotada,
descartable y reconstruible desde SQLite.

Para inspeccionar una página local sin abrir una API de lectura ni reutilizar las
credenciales del collector:

```text
uv run python scripts/inspect_telemetry_v2_history.py --sqlite-db <ruta> \
  --account-id <id> --entity deal --from-msc <inicio> --to-msc <fin>
```

El comando abre la base en modo solo lectura e informa la página, el cursor
siguiente y la cobertura.

El receptor también expone `GET /v2/activity` solo en loopback. Exige
`TRADINGLAB_TELEMETRY_READ_TOKEN`, distinta de las credenciales `live` y
`activity`, y autentica antes de analizar los parámetros. Admite entidad `deal` u
`order`, período, Magic Number, límite y cursor. La respuesta combina una página
resuelta con cobertura completa e indicador de lotes incompletos. El endpoint de
salud continúa sin revelar cuenta ni requerir credenciales.

`GET /v2/position-cycles` reutiliza esa credencial de lectura y devuelve una
página acotada de ciclos reconciliados. Admite `owner_magic`, `limit` y cursor
keyset; autentica antes de validar parámetros. Cada fila conserva procedencia,
clasificación, resultado observado, Magic relacionados, exclusiones y elegibilidad.
No calcula métricas ni devuelve posiciones inferidas desde rangos incompletos.

El adaptador `LoopbackV2HistoryClient` valida estrictamente las respuestas antes
de convertir deals, órdenes o ciclos a modelos del dashboard. Deals y órdenes se
exponen mediante `/api/deals` y `/api/orders`; solo los deals continúan alimentando
las métricas provisionales de `/api/metrics`. Los ciclos se exponen de manera
acotada por `/api/position-cycles`, pero todavía no alteran esas fórmulas ni tienen
una vista visual. El navegador solo accede mediante la sesión autenticada del
dashboard; nunca recibe la credencial interna de lectura ni las de los collectors.

## Próximos pasos seguros

1. La provisión piloto aislada y la migración v2 de esquema 3 a 4 están
   implementadas con vista previa, copia verificada y aplicación explícita.
2. Las proyecciones paginadas de actividad ya están implementadas y validadas con
   datos sintéticos. Falta medirlas con volumen y operaciones reales anonimizadas.
3. El receptor v2 opt-in ya expone `/v2/telemetry` solo en loopback, con
   credenciales separadas en variables de entorno y sin modificar el receptor v1.
   Falta conectarlo a collectors v2. La lectura autenticada y el adaptador del
   dashboard ya están implementados de forma opt-in.
4. Validar observaciones `position_reconcile` reales en demo y contrastarlas con
   MT5 antes de consumir ciclos en métricas.
5. La consulta interna de ciclos, su cliente validado y el proxy autenticado del
   dashboard están implementados. Falta validar evidencia real y aprobar el
   contrato de métricas/vista antes de presentarlos o calcular rendimiento.

## Operación piloto

La provisión se revisa primero sin crear archivos:

```text
uv run python scripts/provision_telemetry_v2_db.py [metadatos y fuentes]
```

`--apply` crea una base nueva bajo `_storage/`; nunca abre ni migra una base v1.
El receptor requiere esa ruta y la cuenta interna mediante `--sqlite-db` y
`--account-id`. Lee credenciales ASCII distintas, de al menos 24 caracteres,
desde `TRADINGLAB_TELEMETRY_LIVE_TOKEN` y
`TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN`; la lectura usa además
`TRADINGLAB_TELEMETRY_READ_TOKEN`. Las tres deben ser distintas y se conservan
solo en memoria:

```text
uv run python scripts/telemetry_receiver_v2.py --sqlite-db <ruta> --account-id <id>
```

La ingesta vive en `http://127.0.0.1:8777/v2/telemetry` por defecto y salud en
`/health`. La consulta vive en `/v2/activity`. Este procedimiento prepara el
backend; no instala collectors ni genera actividad por sí solo.

Para actualizar una base v2 existente, detener primero el supervisor y revisar la
vista previa. El nombre de copia debe ser nuevo:

```text
uv run python scripts/migrate_telemetry_v2_db.py \
  --filename piloto-v2.sqlite3 \
  --backup-filename piloto-v2-before-schema-4.sqlite3
```

Solo después de revisar rutas se repite con `--apply`. El comando rechaza otra
versión, un esquema alterado o una copia ya existente; crea la copia mediante la
API de backup de SQLite, verifica integridad, migra atómicamente y reproyecta los
`position_reconcile` que ya estuvieran guardados. No restaura automáticamente: la
copia queda disponible para una recuperación humana si la validación posterior
fallara.

Durante la transición, el dashboard puede mantener estado vivo desde v1 y tomar
el historial recuperado desde v2:

```text
uv run python scripts/live_dashboard.py --telemetry \
  --telemetry-source <live-v1> --telemetry-port 8776 \
  --history-v2 --history-v2-source <activity-v2> --history-v2-port 8777 \
  --broker-utc-offset-minutes <offset_broker>
```

Además del token normal del dashboard y el token v1, ese proceso recibe
`TRADINGLAB_TELEMETRY_READ_TOKEN`. Rechaza reutilizar cualquiera de ellos. Sin
`--history-v2`, el comportamiento previo no cambia.

El piloto Juampi agrupa ambos receptores y el dashboard en un único supervisor.
Los parámetros y chequeos manuales están en
[Operación del piloto v2](telemetry-v2-pilot-operation.md).

# Manual de instalación y operación de los collectors MT5

**Versión documentada:** Telemetry `0.2.1` y Activity `activity-0.7.1`

**Validación supervisada:** Juampi, 2026-11-05

**Alcance:** terminales MT5 demo locales previamente aprobadas. Esta guía no
autoriza cuentas reales ni amplía la guarda de seguridad de los EAs.

## 1. Qué hacen los collectors

Los dos Expert Advisors (EAs) leen datos del terminal MT5 y los envían al relay
local. Son de solo lectura: no crean, modifican ni cierran órdenes. La captura se
refiere a la cuenta completa, no solo al símbolo o período del gráfico donde se
adjunte el EA.

- **Telemetry v1** publica snapshots vivos de cuenta, posiciones y órdenes, más
  una ventana reciente de operaciones. Mantiene una FIFO volátil de hasta 12
  snapshots durante interrupciones.
- **Activity v2** recorre el historial del broker por ventanas y conserva cursores
  confirmados. Incluye recuperación profunda del período configurado y una vía
  reciente para actividad nueva. La fecha de inicio es obligatoria.

No adjunte más de un EA del mismo rol y `SourceId` a la cuenta. No use la misma
fuente para Telemetry y Activity. El símbolo y timeframe del gráfico no filtran
la cuenta; duplicar collectors puede producir duplicados y conflictos de fuente.

## 2. Arquitectura del piloto

```text
Telemetry v1 ─┐
              ├─> Relay local :8776/:8777 ─> FastAPI :8781 ─> central.sqlite3 (schema 6)
Activity v2 ──┘                                       └─> Dashboard :8775 ─> navegador
```

El relay mantiene una única cola local para sus dos listeners y reenvía al API.
FastAPI recibe y sirve las lecturas; el dashboard consulta la API. El dashboard
no lee SQLite por red. La cola del relay tampoco es la base histórica. El piloto
local anterior usaba archivos v1/v2 independientes; el bootstrap remoto crea el
archivo unificado central/esquema 6. Cada componente debe usar los recursos
provisionados para su topología; no se debe crear una cola o base nueva al arrancar.

Los puertos de loopback de este flujo son:

| Servicio | Puerto | Uso |
| --- | ---: | --- |
| Relay, listener v1 | 8776 | Ingesta local de Telemetry |
| Relay, listener v2 | 8777 | Ingesta local de Activity |
| FastAPI | 8781 | Ingesta central y lecturas autenticadas |
| Dashboard | 8775 | Interfaz web local |

Los EAs apuntan al relay. El destino central del relay apunta a FastAPI. No
configure el relay para reenviar a sus propios puertos `8776` o `8777`: eso
crearía un bucle. Si se parte de
[`telemetry-relay.example.json`](telemetry-relay.example.json)
o de otra topología anterior, revise ambos `target` y adáptelos a
`http://127.0.0.1:8781/v1/telemetry` y
`http://127.0.0.1:8781/v2/telemetry`, respectivamente. No edite el ejemplo
compartido para configurar el piloto; use la topología local provisionada.

## 3. Antes de empezar

Este procedimiento presupone que la topología completa ya está preparada:

- La cuenta demo y sus fuentes v1/v2 están provisionadas en los receptores y en
  las bases correspondientes. Los roles de productor son `live` para Telemetry
  y `activity` para Activity.
- La identidad MT5 aprobada contiene el login y servidor esperados. Compruebe
  ambos directamente en la terminal demo con el operador responsable.
- FastAPI, relay y dashboard usan los archivos, bases, secretos y cola existentes
  de ese piloto. La API y el dashboard no provisionan fuentes ni migran bases al
  arrancar.
- La configuración del relay asocia cada `SourceId`, cuenta, rol y token local
  con su destino central autorizado. Los productores no se autoprovisionan.
- Se revisó el commit de las fuentes que se instalarán y su compatibilidad con la
  API, el relay y las bases actuales.

Si falta cualquiera de estos elementos, deténgase y siga las guías de preparación:

- [Arranque conjunto de dashboard y API central](central-api-dashboard.md)
- [Operación local de la API central](central-api-operation.md)
- [Relay con outbox durable](durable-telemetry-relay.md)
- [Creación de la base SQLite v5](create-sqlite-v5.md)

La creación de bases, la migración, la actualización de targets de una outbox y
la instalación en terminales son operaciones distintas. No reutilice una cola o
base de otro piloto y no cambie un target operativo sin un corte planificado.

### 3.1 Demo y guarda de identidad

La versión instalada solo acepta una cuenta demo cuyo login y servidor coinciden
con `ExpectedDemoLogin` y `ExpectedDemoServer`. Estos inputs deben corresponder a
la identidad demo confirmada por el operador. No son un almacén de credenciales
del broker: nunca introduzca una contraseña de trading.

Si la terminal cambia a otra cuenta, servidor o modo, el EA se detendrá o
rechazará la configuración. No sortee la guarda cambiando inputs a una cuenta no
aprobada. Esta guía no declara preparada una cuenta real.

### 3.2 Tokens y archivos de configuración

Hay credenciales distintas en cada frontera. Los nombres locales de ejemplo para
los productores son:

| Uso | Referencia de variable |
| --- | --- |
| Token local de Telemetry EA al relay | `RELAY_LIVE_LOCAL_TOKEN` |
| Token local de Activity EA al relay | `RELAY_ACTIVITY_LOCAL_TOKEN` |
| Token central del relay para ingesta v1 | `RELAY_LIVE_CENTRAL_TOKEN`, alineado con `CENTRAL_V1_INGEST` |
| Token central del relay para ingesta v2 Activity | `RELAY_ACTIVITY_CENTRAL_TOKEN`, alineado con `CENTRAL_V2_ACTIVITY` |
| Token de lectura del dashboard/API | `CENTRAL_V1_READ` y `CENTRAL_V2_READ` |
| Token humano de login al dashboard | `TRADINGLAB_DASHBOARD_TOKEN` |

Los tokens locales de Telemetry y Activity son distintos. Los tokens centrales,
los tokens de lectura y el token humano también son distintos de los tokens de los
EAs. Consulte la configuración privada existente del piloto: los nombres de
variables pueden variar con la topología y las referencias de esta tabla no
reemplazan esa configuración.

Para compatibilidad con el relay y la API, utilice tokens de 24 a 256 caracteres
ASCII imprimibles sin espacios, provistos por el responsable del piloto. Si ya
están configurados, consérvelos; no genere otros por reinstalar los EAs.

No publique ni copie valores reales de tokens. No los escriba en Git, logs,
comandos, argumentos, capturas, issues ni presets compartidos. Los archivos `.env`
reales contienen secretos: no los abra para copiarlos al manual, no los versione
ni comparta. Los archivos `.set` de MT5 pueden contener el token del EA y deben
tratarse como secretos; no exportarlos ni publicarlos.

### 3.3 Identidad de las fuentes

Cada rol debe tener su fuente única, ya registrada y configurada igual en el
relay, API y base. Por ejemplo, `demo-terminal-01` para Telemetry y
`demo-activity-01` para Activity son nombres ilustrativos: primero deben ser
provisionados en el piloto. No suponga que escribir un nuevo `SourceId` lo
registra automáticamente. Un `SourceId` identifica la fuente; no concede permiso.

## 4. Preparar los servicios locales

Arranque los servicios en este orden, usando el checkout y archivos locales que
ya se usan para el piloto:

1. **FastAPI**, con `central.sqlite3` en esquema global 6, identidades
   provisionadas, credenciales centrales y puerto `8781`.
2. **Relay**, con la misma outbox y topología provisionadas, sus secretos locales
   y centrales, y ambos listeners `8776` y `8777`. Su topología debe apuntar a
   FastAPI en `8781`, no a los listeners del propio relay.
3. **Dashboard**, conectado a FastAPI en `8781`, con los dos `SourceId` ya
   registrados y el token humano separado.

Los comandos completos con flags de esta instalación están en
[arranque conjunto](central-api-dashboard.md). Allí se muestran rutas ilustrativas;
reemplace rutas por las del piloto local sin crear archivos operativos nuevos.
La configuración local de credenciales vive fuera de Git. El relay requiere su
archivo de cola y configuración existentes; FastAPI requiere sus bases existentes.

No genere, inicialice, recree ni migre una base o una cola como parte del arranque
normal. No cambie destinos centrales de la outbox sin plan. Un ACK local del relay
significa que el mensaje entró en la cola durable; el ACK central llega después y
es una confirmación distinta.

## 5. Compilar los collectors

Compile las fuentes revisadas en el checkout, sin instalarlas ni ejecutarlas como
parte de esta etapa. La carpeta fuente es `apps/mt5-telemetry-collector/` e incluye:

- `TradingLabTelemetry.mq5`
- `TradingLabActivity.mq5`
- `TradingLabCollectorCommon.mqh`
- `TradingLabActivityState.mqh`
- `TradingLabCollectorLog.mqh`

Los tres headers deben estar junto a los dos fuentes durante la compilación.

1. En MT5 demo, seleccione **Archivo > Abrir carpeta de datos** y confirme que es
   la terminal objetivo. No deduzca la ruta por el nombre de una ventana.
2. En esta VPS, abra explícitamente el MetaEditor autorizado:
   `C:\Program Files\MetaTrader 5- Roboforex\metaeditor64.exe`.
   No abra MetaEditor con F4 desde Juampi ni use autodetección de otra instalación.
   El uso de otra instalación MT5 requiere consentimiento explícito.
3. En MetaEditor, use **Archivo > Abrir** para abrir cada `.mq5` en el checkout
   revisado. Compile con F7.
4. Exija cero errores y cero warnings para ambos archivos. Verifique que cada
   `.ex5` se produjo junto al fuente de trabajo seleccionado.
5. Mantenga los `.ex5` fuera de Git. La compilación por sí sola no instala el EA
   en ninguna terminal.

La versión `0.2.1`/`activity-0.7.1` se validó en Juampi el 5 de noviembre de 2026.
No use un ZIP antiguo preparado para otra persona como sustituto de esta versión:
ese ZIP no representa los binarios de este manual ni garantiza su logging.

### 5.1 Pruebas nativas al cambiar de versión

La versión documentada ya superó estas pruebas; repítalas si cambia el código o
el build a instalar. La validación completa del código corresponde al gate del
PR en GitHub, no a ejecutar toda la suite Python en cada instalación.

1. En el MetaEditor autorizado, abra y compile los cuatro scripts en
   `tests/mql5/` del checkout: `collector_common_test.mq5`,
   `telemetry_outbox_test.mq5`, `activity_collector_test.mq5` y
   `collector_logger_test.mq5`. Mantenga la estructura del repositorio: sus
   includes son relativos. Exija cero errores y advertencias.
2. En la carpeta de datos de la terminal demo, cree
   `MQL5/Scripts/TradingLabTests` y copie allí solo los cuatro `.ex5` resultantes.
3. Actualice **Scripts** en el Navegador de MT5 y ejecútelos uno por uno sobre un
   gráfico vacío, sin EA de trading. No requieren tokens, DLLs ni permisos de
   comercio; los accesos de plataforma y filesystem relevantes se simulan.
4. En **Expertos**, cada script debe terminar con `0 failure(s)`. Algunos provocan
   errores deliberados, como `encoding_failed`; lo decisivo es el resumen final.
   Si hay fallos, no instale los collectors nuevos.

## 6. Instalar los binarios en la terminal demo

Instale únicamente los dos `.ex5` compilados y revisados en el paso anterior.
Copiar los `.mq5` y `.mqh` es opcional: hágalo solo si necesita mantener las
fuentes junto a los binarios y copie los dos `.mq5` y los tres `.mqh` como grupo.
No compile de nuevo desde una copia parcial ni use F4 para compilar desde una
instalación distinta.

1. Antes de reemplazar una versión existente, retire solo los dos collectors de
   sus gráficos y verifique que dejaron de ejecutarse. No cierre otros EAs.
2. Preserve los `.ex5` previos y su SHA-256 en el almacenamiento operativo
   autorizado. Conserve la configuración necesaria en forma privada; no incluya
   tokens en el registro de hashes ni en documentación compartida.
3. En la terminal MT5 objetivo, abra **Archivo > Abrir carpeta de datos**.
4. Bajo `MQL5/Experts/`, cree o use la carpeta `TradingLab`.
5. Copie allí los dos `.ex5` del mismo build. Si conserva fuentes, copie los dos
   `.mq5` y los tres `.mqh`; no compile esa copia.
6. En MT5, en el navegador de **Asesores Expertos**, elija **Actualizar** y
   confirme que aparecen ambos collectors de `TradingLab`.

No sustituya ni reinicie EAs de trading. No cambie su configuración global de
Algo Trading para resolver permisos del collector. No borre variables globales
`TL2.ACT.*`, no reinicie cursores y no recree la base. El rollback requiere los
binarios previos preservados y una instalación supervisada.

## 7. Permitir WebRequest y configurar los inputs

En MT5 abra **Herramientas > Opciones > Asesores Expertos**. Autorice exactamente
estos dos listeners loopback en esa terminal:

- `http://127.0.0.1:8776`
- `http://127.0.0.1:8777`

Los EAs no necesitan dominios externos, DLLs ni permiso para operar. No habilite
el trading automático para el collector ni modifique el ajuste global si otros
EAs lo usan. Mantenga las URLs de cada EA en loopback.

Use un gráfico nuevo y vacío para cada collector: uno para Telemetry y otro para
Activity. No arrastre un collector encima de un EA de trading activo; MT5 puede
reemplazar el EA que ya ocupa ese gráfico. El símbolo y timeframe elegidos no
reducen la captura: se observa la cuenta MT5 completa.

### 7.1 Telemetry v1

| Input | Valor piloto o default | Descripción |
| --- | --- | --- |
| `IngestUrl` | Cambiar al puerto actual `http://127.0.0.1:8776/v1/telemetry` | La fuente trae default `8766`; el piloto actual usa `8776`. Cambie el input, no el código. |
| `Token` | Token local privado para v1 | Debe coincidir con el relay y ser distinto del token Activity. |
| `SourceId` | Fuente live v1 provisionada | Ejemplo de default: `demo-terminal-01`; no asumir que ya existe en el relay. |
| `IntervalSeconds` | 5 | Intervalo de snapshots; rango permitido 2–60. |
| `RequestTimeoutMs` | 500 | Timeout HTTP; debe estar entre 500 y un cuarto del intervalo en milisegundos. |
| `MaxItemsPerSnapshot` | 200 | Máximo de elementos por colección; rango 1–500. |
| `HistoryLookbackSeconds` | 3600 | Ventana reciente de historial; rango 60–86400. |
| `HistoryIntervalSeconds` | 60 | Relectura del historial; desde el intervalo del EA hasta 3600 segundos. |
| `MaxDealsPerSnapshot` | 200 | Máximo de deals seleccionados por snapshot; rango 1–200. |
| `ExpectedDemoLogin` | Login de la demo aprobada | Obligatorio y exacto; no es contraseña. |
| `ExpectedDemoServer` | Servidor de la demo aprobada | Obligatorio y exacto. |

El input URL de ejemplo puede mostrar `8766`, pero el piloto utiliza `8776`.
Verifique siempre que la URL termine en `/v1/telemetry` y coincida con la fuente
provisionada del relay.

### 7.2 Activity v2

| Input | Valor piloto o default | Descripción |
| --- | --- | --- |
| `IngestUrl` | `http://127.0.0.1:8777/v2/telemetry` | Listener v2 del relay. |
| `Token` | Token local privado de Activity | Distinto del token local de Telemetry. |
| `SourceId` | Fuente Activity v2 provisionada | Default ilustrativo: `demo-activity-01`. |
| `IntervalSeconds` | 10 | Ciclo del EA; rango 2–300. |
| `RequestTimeoutMs` | 1000 | Timeout; al menos 500 ms y no mayor a la mitad del intervalo. |
| `HistoryStartServerTime` | Fecha/hora de servidor MT5 aprobada | Obligatoria, mayor que cero; fija el inicio histórico. |
| `WindowSeconds` | 21600 (6 horas) | Ventana normal; rango 60–86400. |
| `MinimumWindowSeconds` | 60 | Mínimo para dividir ventanas densas. |
| `OverlapSeconds` | 5 | Solape entre rangos; menor que la ventana mínima. |
| `MaxItemsPerCollection` | 200 | Límite de elementos por colección; rango 1–200. |
| `RecentLookbackSeconds` | 3600 | Lookback de actividad reciente. |
| `RecentCadenceSeconds` | 60 | Cadencia reciente; no menor que el intervalo del EA. |
| `HeartbeatSeconds` | 60 | Cadencia de heartbeat; no menor que el intervalo. |
| `EnableDeepRecovery` | `true` | Habilita recuperación histórica desde el inicio. |
| `MaxHistoryRowsPerCycle` | 500 | Filas por ciclo; rango 10–2000. |
| `CycleBudgetMs` | 25 | Presupuesto cooperativo; rango 1–100 ms. |
| `ExpectedDemoLogin` | Login de la demo aprobada | Obligatorio y exacto; no es contraseña. |
| `ExpectedDemoServer` | Servidor de la demo aprobada | Obligatorio y exacto. |

`HistoryStartServerTime` usa tiempo de servidor MT5, no se debe inferir desde la
hora local del PC. Seleccione una fecha anterior a la cobertura requerida y
confírmela con quien opera el piloto. El valor cero hace que el EA falle de forma
segura. Cambiar la fecha no retrocede un cursor ya confirmado ni vuelve a leer
automáticamente períodos previos. Para ampliar o rehacer cobertura, solicite una
revisión antes de cambiar fuentes o cursores. No borre `TL2.ACT.*` para forzar un
backfill.

Deje los demás límites en sus defaults salvo que exista un plan de carga y
validación. No optimice ventanas o presupuestos a ciegas.

## 8. Adjuntar los EAs

1. Confirme que API, relay y dashboard están disponibles en sus puertos de
   loopback y que las fuentes corresponden a la demo elegida.
2. Abra dos gráficos nuevos vacíos en la terminal demo aprobada.
3. Adjunte `TradingLabTelemetry` a un gráfico y configure inputs v1.
4. Adjunte `TradingLabActivity` al otro gráfico y configure inputs v2, incluida
   una fecha histórica de inicio válida.
5. Verifique visualmente `SourceId`, URL, login y servidor antes de confirmar cada
   diálogo. No guarde ni comparta un preset `.set` con tokens.
6. Compruebe la pestaña **Expertos**. Los collectors no emiten mensajes de inicio
   sano; silencio por sí solo no es un error. Los errores críticos y fallos del
   sink sí producen aviso.

Una URL, token, rol o identidad incorrectos deben causar rechazo o ausencia de
captura. No debilite las guardas ni cambie a otra cuenta para conseguir actividad.

## 9. Comprobar captura y persistencia

Valide cada etapa por separado:

1. **EA a relay:** consulte `/health` en `http://127.0.0.1:8776/health` y
   `http://127.0.0.1:8777/health`. Ambos listeners muestran la misma cola. Un ACK
   al EA significa aceptación local, no persistencia central.
2. **Relay a API:** observe el estado y la antigüedad de la última confirmación
   central. Una cola vacía no demuestra por sí sola cobertura completa.
3. **API y base:** use las lecturas autenticadas de la API y confirme el `SourceId`,
   versión, timestamp y datos esperados. No inspeccione ni publique filas con
   login completo, tokens o payloads.
4. **Dashboard:** abra `http://127.0.0.1:8775/dashboard` e inicie sesión con el
   token humano, nunca con el token de un EA. Compare valores visibles con MT5 y
   la fuente aprobada. El dashboard consulta FastAPI, no la base directamente.
5. Consulte progreso v2 para distinguir historial confirmado de trabajo pendiente.
   El ACK de un lote no significa que se haya completado toda la historia.

La conexión API/relay/dashboard y la recepción central fueron verificadas para
estas versiones en Juampi. Un operador debe volver a comprobar su propio estado
local. No registre login, balance, posiciones completas ni capturas de pantalla
que revelen información de cuenta en Git.

### 9.1 Indicador «Datos parciales»

El indicador puede describir un período solicitado que aún no está completo o el
borde vivo de los datos. No equivale por sí mismo a desconexión ni a pérdida de
historial. Revise el rango seleccionado, el progreso de Activity y el último
timestamp recibido; compare, si procede, con el mismo período terminado el día
anterior. No confunda retraso de captura con un hueco confirmado. Si hay un hueco
real, conserve evidencia no sensible y solicite revisión antes de alterar cursores.

## 10. Logs locales del collector

Los archivos de diagnóstico viven en la carpeta de datos de la terminal MT5:

```text
<carpeta-de-datos-MT5>/MQL5/Files/TradingLab/logs/
```

El directorio y el archivo diario se crean al primer warning o error, no al inicio
sano ni por cada snapshot. Los nombres son:

```text
telemetry-<SourceId>-YYYYMMDD.jsonl
activity-<SourceId>-YYYYMMDD.jsonl
```

La fecha del nombre y `time_utc` son UTC; `:` en `SourceId` se convierte en `~`.
Por eso el día UTC puede diferir del día local de Madrid.

Ejemplo reducido y sintético de un corte y su recuperación:

```json
{"time_utc":"2026-11-05T10:00:00Z","level":"WARN","code":"receiver_unavailable","sequence":"3","occurrences":"1"}
{"time_utc":"2026-11-05T10:01:00Z","level":"RESOLVED","code":"receiver_unavailable","sequence":"3","occurrences":"5","suppressed":"4"}
```

Los niveles son `WARN`, `ERROR` y `RESOLVED` al cerrar una incidencia. No hay
eventos `INFO` ni mensajes healthy de inicio/parada. Cada registro incluye hora,
nivel, collector, fuente y versión, código, detalle limitado, secuencia, estado
de transporte, error local, ocurrencias, suprimidos y duración. No contiene
tokens, headers, credenciales ni payloads. Un valor como `1001` es un estado de
transporte, no un código HTTP.

Por código, el primer evento se registra y después se limita a uno por minuto;
el logger mantiene hasta 32 códigos en memoria y resume al cerrar. Cada fuente y
día tiene un máximo de 1 MiB. Al alcanzar la cuota suspende escritura hasta el
siguiente día UTC y avisa una vez. La retención es de 14 días y solo elimina
archivos propios con fecha válida; al iniciar la limpieza diaria examina hasta 64
entradas. No usa `FILE_COMMON` y no borra cursores, bases ni archivos ajenos.

El logging es best-effort. Un error de escritura, permiso o cuota genera un aviso
en Expertos y no detiene la captura. No hay E/S de logging en
`OnTradeTransaction`. El registro no es un ledger de trading: una caída abrupta
puede perder el resumen todavía suprimido.

Para observar el archivo, sustituya el marcador por la ruta local confirmada en
**Archivo > Abrir carpeta de datos**:

```powershell
Get-Content -LiteralPath '<carpeta-de-datos-MT5>\MQL5\Files\TradingLab\logs\<archivo>.jsonl' -Tail 20 -Wait
```

Use el visor local; no copie los logs a Git, tickets o capturas compartidas sin
revisar que no incluyan identificadores sensibles.

## 11. Corte breve del relay y recuperación

Esta prueba valida el comportamiento ante una pausa corta; no prueba todos los
casos de desconexión, carga o interrupción larga.

1. Confirme ACK central normal y que ambos collectors están activos.
2. Detenga solo el proceso relay con `Ctrl+C`. No detenga API, dashboard, MT5 ni
   los collectors; no los quite de los gráficos.
3. Espere alrededor de 30 segundos. Activity debe conservar el lote pendiente y
   reintentar. Telemetry puede acumular snapshots en su FIFO volátil de hasta 12.
4. Reinicie el relay con el mismo comando, archivo de configuración, outbox y
   secretos que antes. No inicialice otra cola.
5. Espere a que el backoff permita nuevos intentos (hasta 90 segundos) y revise
   los health checks, ACK central y datos v1/v2.
6. Compruebe en ambos JSONL el `WARN` y su `RESOLVED`; en Activity la secuencia del
   lote pendiente debe mantenerse entre ambos eventos. En Expertos no debe haber
   ruido de inicios o estados saludables.

Activity conserva el cursor y puede reconciliar rangos históricos. Telemetry
mantiene muestras vivas en una FIFO de 12; su política de reintento puede agotar
los intentos y descartar una muestra (`snapshot_dropped`). Por tanto, la prueba
no garantiza recuperar todos los snapshots intermedios. En la validación
supervisada de Juampi ambos flujos volvieron a recibir ACK central y la cola,
pendientes, rechazos y errores terminaron en cero; Activity no quedó bloqueado.
No extrapole ese resultado a 401/403, desconexión del broker, carga ni a todas las
muestras de Telemetry.

## 12. Diagnóstico

| Señal | Qué revisar |
| --- | --- |
| No hay mensajes sanos en Expertos | Es normal: no se registran eventos de inicio ni healthy. Compruebe el gráfico y los logs solo si aparece una incidencia. |
| No existe archivo JSONL | Se crea al primer warning/error; ausencia de archivo durante operación sana es normal. |
| `401` recibido por el EA | El collector vuelve a sondear cada 60 s. Revise la referencia del token local del productor, sin copiar valores ni rotarlo a ciegas. |
| `403` recibido por el EA | También vuelve a sondear cada 60 s. Revise rol, identidad demo, fuente provisionada y reglas del relay. No saltee la guarda. |
| Mensajes `rejected` en la cola del relay | Un rechazo permanente de la API central, incluido 401/403, bloquea ese stream: no es el sondeo automático del EA. Revise la frontera central y siga el procedimiento supervisado de rehabilitación de la [outbox](durable-telemetry-relay.md). |
| `400` | Requiere investigar el contrato y la configuración. Un error local como MQL5 `4009` puede ocurrir antes de que exista solicitud HTTP; no lo atribuya al relay. |
| `1001` | Es estado de transporte, no HTTP. Compare logs y etapa del flujo; no adivine una causa. |
| `5203` | Es otro error local de transporte. No lo interprete como respuesta HTTP ni cambie credenciales sin evidencia. |
| Puerto ocupado o respuestas duplicadas | Verifique qué procesos usan `8776`, `8777` y `8781`; no arranque un segundo relay sobre la misma outbox. |
| Cola local aceptada, sin ACK central | Revise relay→API, targets centrales, servicio API y credenciales de esa frontera. No reinicie collectors para resolver la cola. |
| «Datos parciales» | Revise período, progreso y última captura. Puede ser período incompleto o borde vivo, no necesariamente desconexión o hueco real. |
| No cambia el historial al editar fecha de inicio | El cursor confirmado no retrocede automáticamente. No borre `TL2.ACT.*`; pida revisión para backfill o ampliación. |

No pegue tokens, `Authorization`, cuerpos HTTP, credenciales del broker ni `.env`
en solicitudes de ayuda. Comparta códigos y estados redactados.

## 13. Actualizar o volver atrás

Antes de sustituir un build, confirme que el nuevo commit es compatible con la
API, el relay, el contrato y las fuentes registradas. Para actualizar:

1. Preserve los dos `.ex5` actuales y sus hashes en almacenamiento local autorizado.
2. Retire solo los collectors de sus dos gráficos. No cierre la terminal y no
   deshabilite globalmente Algo Trading.
3. Instale los dos `.ex5` nuevos desde el mismo build con los pasos de la sección 6.
4. Mantenga los mismos inputs, tokens, `SourceId`, cuenta y servidor aprobados.
5. No toque los EAs de trading, la base, la outbox ni cursores. Repita las
   verificaciones de salud, ACK y dashboard.

Para rollback, retire los dos collectors y restaure únicamente los binarios
previos preservados, verificando sus hashes. Mantenga configuración y cursores.
No restaure un ZIP de otra persona como si fuera la versión documentada; los
binarios antiguos no incluyen necesariamente estas capacidades de logging. No
borre `TL2.ACT.*`, no reinicialice la base ni cambie targets centrales durante el
rollback. Si no puede verificar el origen de los binarios, deténgase y solicite
una compilación revisada.

## 14. Lista de cierre

- [ ] Cuenta demo, login y servidor coinciden con la identidad aprobada.
- [ ] Fuentes v1 y v2, roles y destinos ya estaban provisionados.
- [ ] Tres headers estuvieron junto a ambos fuentes durante la compilación.
- [ ] MetaEditor correcto produjo ambos binarios con cero errores y cero warnings.
- [ ] Solo se instalaron los dos `.ex5` del mismo build en la terminal objetivo.
- [ ] Se autorizaron solo los dos destinos loopback del relay.
- [ ] Cada collector ocupa su propio gráfico nuevo; no se reemplazó ningún EA.
- [ ] Se preservaron configuración y binarios anteriores; no se tocaron cursores.
- [ ] Relay→API confirmó datos y el dashboard mostró las fuentes previstas.
- [ ] El corte breve se ejecutó solo si estaba aprobado y se revisaron WARN/RESOLVED.
- [ ] No se compartieron secretos, presets sensibles, payloads ni cuentas reales.
- [ ] Se mantienen pendientes las pruebas separadas de 401/403, broker y carga.

## Referencias operativas

Esta guía es el procedimiento para instalar y operar los collectors. Para detalle
de diseño y evidencia de robustez consulte
[recuperación y trabajo acotado](mt5-collector-resilience.md). Para arranque y
pruebas integradas consulte [API, relay y dashboard](central-api-dashboard.md),
[operación de API](central-api-operation.md) y
[operación de outbox](durable-telemetry-relay.md). Para una base nueva consulte
[creación SQLite v5](create-sqlite-v5.md); no aplique esa guía como paso de rutina
en un piloto ya provisionado.

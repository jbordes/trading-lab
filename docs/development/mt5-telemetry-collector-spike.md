# Spike de colector de telemetría MT5

**Fecha:** 2026-10-16

**Estado:** piloto demo integrado aprobado; adoptado como fuente operativa primaria

**Decisiones:** [ADR-0003](../adr/0003-mt5-push-telemetry-spike.md) y
[ADR-0004](../adr/0004-mt5-collector-primary-source.md)

## Objetivo

Mantener un collector MQL5 propio como fuente operativa identificada por terminal,
sin ejecutar operaciones y con pocos segundos de demora. La API Python queda como
herramienta auxiliar para diagnóstico o reconciliación aislada. Este componente
no implementa métricas de riesgo.

```text
Terminal demo MT5
    |
    | POST /v1/telemetry + Bearer token
    v
receptor 127.0.0.1:8766
    |
    | GET /v1/snapshot?source_id=<id> + mismo Bearer token
    v
adaptador servidor del dashboard + buffer acotado en memoria + /health
```

Para el arranque cotidiano y la recuperación del piloto Juampi (8776/8775),
seguir [la guía operativa](telemetry-operation.md). El comando conjunto sustituye
la dependencia del supervisor temporal del piloto.

El receptor es un proceso separado. El servidor del dashboard continúa
rechazando `POST`; su adaptador servidor conoce el token local, pero nunca lo
entrega al navegador.

El receptor responde mediante HTTP/1.1 y cierra explícitamente cada conexión.
Durante el piloto del 2026-10-17, MT5 aceptaba el cuerpo enviado a un receptor
HTTP/1.0 pero devolvía los códigos internos 1001/1003 en lugar de 200/202. Eso
impedía al collector confirmar el envío y mantenía la cola atrasada. Una respuesta
mínima HTTP/1.1 en el mismo endpoint confirmó la compatibilidad necesaria.

## Contrato `mt5-telemetry-v1`

Cada mensaje contiene:

- versión del schema y del colector;
- `source_id` no sensible;
- `session_id` nuevo por inicio del EA;
- secuencia positiva y `event_id` idempotente;
- instante UTC;
- tipo `heartbeat` o `account_snapshot`;
- payload validado y acotado.

El snapshot conserva identificadores MT5 como texto, enmascara el login e incluye
estado de cuenta, cantidad total y muestra limitada de posiciones y órdenes. La
diferencia entre el total y la muestra hace visible cualquier truncamiento.

Una repetición idéntica es idempotente. Reutilizar una secuencia o `event_id` con
otro contenido se rechaza. Los saltos de secuencia se aceptan, pero quedan
contabilizados para el diagnóstico.

## Seguridad del spike

- Bind fijo a `127.0.0.1`.
- Endpoint de ingestión único y autenticado.
- Token leído desde `TRADINGLAB_TELEMETRY_TOKEN`; nunca por argumentos o Git.
- Cuerpo máximo de 256 KiB, JSON UTF-8 y schema estricto.
- Sin persistencia, logs de payload, eco del token ni comandos de respuesta.
- Fuente `.mq5` sin imports, DLLs o funciones de trading.
- Guarda automática del harness para llamadas MQL5 prohibidas.
- El `.ex5` resultante permanece ignorado por Git.

La guarda textual reduce accidentes, pero no reemplaza revisión humana ni la
compilación desde la fuente versionada.

## Ejecución local

Preparar el entorno y definir un token efímero de al menos 24 caracteres fuera
del repositorio. Luego ejecutar:

```text
uv run python scripts/telemetry_receiver.py --port 8766
```

El estado diagnóstico queda disponible en:

```text
http://127.0.0.1:8766/health
```

`GET /v1/snapshot?source_id=<id>` requiere el mismo Bearer token y exactamente un
identificador válido. Devuelve solamente la última muestra de cuenta de esa
fuente; mensajes posteriores de otro collector no la desplazan. El token protege
el receptor completo y `source_id` selecciona datos, no concede autorización. No
expone un listado histórico completo y la memoria se pierde al detener el proceso.

## Fuente MQL5

`apps/mt5-telemetry-collector/TradingLabTelemetry.mq5`:

- valida que el endpoint sea loopback;
- usa un temporizador entre 2 y 60 segundos;
- marca actividad mediante `OnTradeTransaction`;
- envía el snapshot reconciliado en el siguiente tick del temporizador;
- captura antes de enviar, con una FIFO volátil de hasta 12 snapshots;
- reintenta el mismo mensaje ante errores transitorios, sin frenar nuevas muestras;
- ignora el cuerpo de respuesta y nunca recibe instrucciones;
- limita posiciones y órdenes por snapshot.

Desde la corrección 5 envía una ventana acotada de deals históricos. No envía
velas ni reconstruye muestras intermedias de equity; esos incrementos dependen
de lo observado en la comparación.

### Recuperación de envíos (corrección 1)

Cada tick captura una muestra nueva, incluso durante una caída del receptor.
La cola retiene hasta 12 mensajes de un máximo de 256 KiB UTF-8 cada uno; no es
almacenamiento durable. Al llenarse descarta el más antiguo para conservar datos
recientes. Los descartes registran secuencia, motivo y contador, nunca payloads.
El receptor contabiliza los huecos cuando recibe una secuencia posterior; no
puede detectar una cola perdida al final de una sesión sin más mensajes.

Los errores de transporte, HTTP 408, 429 y 5xx tienen hasta cinco intentos por
mensaje, con esperas de 2, 4, 8, 16, 32 y hasta 60 segundos entre oportunidades
de envío (redondeadas al siguiente tick). Otros rechazos descartan el mensaje.
La espera pertenece al endpoint y no se reinicia al desbordar la cola, evitando
martillar un receptor caído o con token incorrecto. HTTP 200/202 avanza la cola.
Los reintentos conservan contenido, secuencia y timestamp originales.

Tras recuperarse se permiten hasta dos envíos por tick para drenar el atraso.
`RequestTimeoutMs` vale 500 ms por defecto y no puede superar un cuarto del
intervalo: los dos envíos consumen nominalmente hasta medio intervalo. No se
garantiza tiempo real ni muestreo sin jitter: [WebRequest es sincrónica](https://www.mql5.com/en/docs/network/webrequest).
Una caída prolongada, un cierre o reinicio pierden muestras; no se reconstruyen
valores de equity inexistentes. En el cierre normal se registran los descartes.

La prueba nativa `tests/mql5/telemetry_outbox_test.mq5` usa la lógica real de la
cola con reloj y respuestas HTTP simuladas, sin red ni lecturas de cuenta en su
ejecución. El 2026-10-17 se compiló con 0 errores y 0 warnings y se ejecutó como
script en la terminal aislada MT5-Juampi, con el resultado
`TradingLab outbox tests: 0 failure(s)`. Los checks Python verifican el orden
captura/envío y el receptor; esta prueba determinista no sustituye la desconexión
real ni la comparación del piloto demo.

## Resultado nativo y pruebas manuales pendientes

### Valores numéricos inválidos (corrección 2)

La captura usa [MathIsValidNumber](https://www.mql5.com/en/docs/math/mathisvalidnumber)
para detectar NaN e infinitos en los campos numéricos de cuenta, posiciones y
órdenes. Si alguno es inválido, descarta el snapshot completo **antes** de entrar
en la cola: nunca lo convierte en cero ni publica una muestra parcial.
El motivo `invalid_numeric` se registra junto con la secuencia y el contador de
descartes, sin valores financieros. La siguiente captura parte de un estado de
validación nuevo; los ceros auténticos y valores negativos finitos se conservan.

El hueco será visible al receptor cuando llegue una secuencia posterior. El
placeholder interno `null` jamás se publica. Esta guarda detecta no-finitos;
no detecta un fallo de lectura que MT5 represente como un cero finito ni valida
rangos económicos. No modifica todavía el contrato del receptor (punto 3).

La prueba nativa incluye NaN, ambos infinitos, ceros, valores negativos,
rechazo sin desplazar muestras válidas y recuperación de la siguiente muestra.
Estas aserciones quedaron aprobadas en la ejecución aislada del 2026-10-17.

### Validación del receptor (corrección 3)

`mt5-telemetry-v1` exige ahora todos los campos que emite el collector actual;
no admite filas parciales ni campos desconocidos. No cambia el formato emitido
por MQL5, pero clientes de prueba con filas abreviadas deben completarlas.

- Comunes a posiciones y órdenes: `ticket`, `magic_number`, `symbol`, `volume`,
  `price_open`, `price_current`, `stop_loss`, `take_profit` y `comment`.
- Posiciones: además `position_id`, `operation_type`, `profit`, `swap` y
  `opened_at_msc`.
- Órdenes: además `order_type` y `created_at_msc`.
- Tickets: texto decimal positivo de hasta uint64, sin duplicados dentro de cada
  colección. Magic Number: texto decimal int64, incluido cero y signo negativo,
  coherente con la serialización del getter `long` usado por el collector.
  Position ID: decimal positivo int64. Tiempos en milisegundos: decimal int64 no
  negativo. No se convierten estos identificadores a float.
- Importes y precios: números finitos, no booleanos ni cadenas. El volumen no
  puede ser negativo. Los precios y el P/L no reciben límites económicos nuevos.
- Tipo de posición: entero 0/1; tipo de orden: entero 0..8, según las propiedades
  de [posiciones](https://www.mql5.com/en/docs/constants/tradingconstants/positionproperties)
  y [órdenes](https://www.mql5.com/en/docs/constants/tradingconstants/orderproperties).
- Símbolo: texto no vacío de hasta 128 caracteres; comentario: hasta 256,
  permitiendo vacío. `captured_at`: ISO UTC con segundos y fracción opcional de
  hasta seis dígitos; conserva precisión al normalizar.

JSON con claves repetidas, profundidad excesiva, Unicode inválido o números
desmesurados se rechaza mediante errores de validación. La frontera HTTP devuelve
400 `invalid_message` sin devolver valores ni claves recibidos. Un rechazo no
modifica el buffer y no impide aceptar mensajes válidos posteriores.

Autorizaciones no ASCII o repetidas reciben 401; Content-Length repetido o
Transfer-Encoding reciben 400 antes de leer el cuerpo. El token configurado debe
ser ASCII imprimible sin espacios ni controles. Los límites de conexiones,
tiempo de red y retención se describen en la corrección 6.

### Guardas del piloto (corrección 4)

El collector exige configurar localmente `ExpectedDemoLogin` (>0) y
`ExpectedDemoServer` (nombre exacto); los valores por defecto impiden iniciar.
No versionar esa configuración ni incluir el login completo en logs. La cuenta
debe estar conectada y tener `ACCOUNT_TRADE_MODE_DEMO`; un nombre de servidor con
la palabra «demo» no basta. Se rechazan cuentas reales y de concurso, según las
[propiedades de cuenta de MT5](https://www.mql5.com/en/docs/constants/environment_state/accountinformation).

La identidad autorizada se comprueba al iniciar, antes y después de construir
cada muestra y antes de cada envío. Desconexión, error al consultar la identidad
o cambio de login/servidor activa una parada: cancela el temporizador, descarta
la cola con motivo `pilot_guard` y no reanuda desde el siguiente tick. El operador
debe revisar y volver a adjuntar el EA; si MT5 lo reinicializa automáticamente,
la nueva cuenta también debe coincidir con la configuración explícita. No se
autoriza automáticamente otra demo ni se modifica la cuenta o sus operaciones.
La identidad no es una lectura transaccional: estas comprobaciones reducen la
ventana de cambio durante captura, pero requieren validación real en el piloto.

La URL admite exclusivamente `http://127.0.0.1:<puerto>/v1/telemetry`, con puerto
decimal 1..65535 sin ceros iniciales. Rechaza dominios, `localhost`, credenciales
en URL, rutas distintas, query, fragmentos, espacios, controles y escapes.
Esto valida el destino configurado, no constituye aislamiento de red del
terminal. Usar únicamente nuestro receptor local, que no emite redirecciones;
no se ha comprobado el comportamiento interno de WebRequest ante redirecciones
o proxies. No sustituirlo por un servicio local de terceros sin esa evaluación.

Las pruebas nativas incluyen URLs ambiguas, cuentas reales/de concurso,
desconexión y cambios de login/servidor. Sus escenarios simulados quedaron
aprobados en la ejecución aislada del 2026-10-17. Los cambios reales de cuenta
y desconexión continúan pendientes en un terminal de pruebas aislado, nunca en
la terminal que esté ejecutando los bots del socio.

### Historial reciente y reconciliación (corrección 5)

El collector 0.1.1 añade `history` al snapshot. El receptor actualizado mantiene
compatibilidad con snapshots previos sin ese campo (`unavailable`); un receptor
anterior debe actualizarse antes de usar este collector.

En cada captura se relee la ventana completa con `HistorySelect`, incluso si no
llegó ningún callback de transacción. Por defecto cubre 3600 segundos; se permite
configurar `HistoryLookbackSeconds` entre 60 y 86400 y `MaxDealsPerSnapshot` entre
1 y 200. Al superar el límite, se toma el tramo final de la lista de MT5 y se
informa `truncated` con el total seleccionado. No hay paginación ni promesa de
recuperar todas las ejecuciones de ventanas saturadas.

Se preservan ticket, orden, posición, Magic Number, tipo, entrada/salida/reversión,
tiempo en milisegundos, símbolo, volumen, precio, P/L, comisión, swap y fee.
También se admiten asientos no comerciales: no se infiere que cada deal sea un
trade completo. Los datos provienen de las [propiedades de deals](https://www.mql5.com/en/docs/constants/tradingconstants/dealproperties).

`from_server_seconds`, `to_server_seconds` y `time_msc` mantienen la escala del
servidor de MT5: [HistorySelect usa tiempo del servidor](https://www.mql5.com/en/docs/trading/historyselect).
No se rotulan como UTC ni se inventa una conversión. `captured_at` sigue en UTC.
La zona y cambios horarios del broker requieren validación antes de calcular
métricas que crucen ambas escalas.

El contrato distingue `complete` (todos los elementos seleccionados), `truncated`
y `error` (fallo de lectura o dato no finito). `complete` no certifica sincronía
del broker ni completitud de toda la vida de la cuenta. Un error de historial
envía la cuenta junto con `history.status=error`, sin filas históricas parciales
ni ceros sustitutos; no se presenta como ventana vacía correcta.

`TelemetryBuffer.recent_deals(source_id, magic_number=...)` proyecta la última
ventana recibida, sin concatenar solapamientos ni sumar P/L. Tickets repetidos
dentro de una ventana se rechazan; una nueva ventana reemplaza la anterior y
refleja correcciones/eliminaciones disponibles en el broker. El estado de una
ventana truncada sigue siendo incompleto, incluso tras filtrar por Magic Number.
Un `source_id` corresponde a una sola cuenta aprobada, con un solo collector;
asignar otro ID al cambiar de cuenta. No es un catálogo histórico multicuenta.

Releer recupera deals perdidos por callbacks o envíos **mientras permanezcan en
la ventana y entren en el límite**. Reiniciar el receptor pierde su memoria y la
siguiente muestra la repuebla. Al detenerse la guarda de cuenta hay que revisar
y reactivar manualmente el EA. Una caída más larga que la ventana, truncamiento
o descarte por tamaño máximo de mensaje puede dejar información irrecuperable
en este piloto. La consulta de MT5 es sincrónica: medir su coste antes de ampliar
la ventana o frecuencia. No hay almacenamiento durable, watermark persistente,
reconstrucción de equity ni emparejamiento de trades.

La primera integración con el dashboard proyecta únicamente cuenta y operaciones
actuales. No publica todavía los deals de esta ventana porque sus timestamps
conservan la escala del servidor MT5 hasta validar su zona horaria.

`/health` publica solo estado y cantidad retenida de historial, nunca sus filas.
Las pruebas Python cubren entrada/salida entre muestras, solapamientos, tickets
con igual milisegundo, reinicios, correcciones, filtros, límites y errores; la
prueba nativa con historial simulado fue ejecutada correctamente en MT5-Juampi
el 2026-10-17.

### Consulta durable de deals

Cuando el receptor se inicia con la SQLite v1 provisionada, expone una lectura
autenticada adicional:

```text
GET /v1/deals?account_id=<cuenta>&from_msc=<incluido>&to_msc=<excluido>&magic_number=<magic>&limit=50&cursor=<cursor>
```

`account_id`, `from_msc` y `to_msc` son obligatorios. `magic_number`, `limit`
(1..100) y `cursor` son opcionales. La respuesta ordena los deals del más nuevo
al más antiguo y entrega `next_cursor` cuando existe otra página. El período usa
por ahora los milisegundos informados por MT5: no se los presenta todavía como
UTC porque la zona horaria del servidor sigue pendiente de validación.

La identidad durable es `cuenta + ticket`. Las ventanas solapadas no duplican
filas y la observación con captura más reciente representa una corrección. Antes
de devolver cada deal se vuelven a verificar el hash, el contrato y las columnas
del mensaje que lo contiene. El receptor de fuente única solo permite consultar
la cuenta asociada a esa fuente; otra cuenta responde como no disponible.

La consulta usa paginación por clave y nunca carga el journal completo en Python,
pero SQLite todavía debe recorrer el JSON persistido para deduplicar. Es el corte
inicial deliberado del ADR-0012. Se medirá con volumen representativo antes de
crear tablas derivadas, índices o una migración. Esta API expone deals MT5, no
trades reconstruidos, y aún no calcula cobertura, métricas ni rankings por EA.

El endpoint no existe en el receptor puramente en memoria. Continúa ligado a
loopback y requiere el Bearer token del receptor; el navegador no recibe esa
credencial.

### Recursos del receptor (corrección 6)

Por defecto se atienden hasta **8 conexiones simultáneas**, con un plazo de red
de **5 segundos** por conexión y una cola de escucha configurada en 8. El exceso
se cierra sin crear un worker ni esperar a leer su petición; no se promete una
respuesta HTTP 503. El collector lo trata como fallo de transporte reintentable.

Cada conexión admitida tiene timeout de socket y un temporizador absoluto que
interrumpe su socket: enviar bytes lentamente no renueva ese plazo. Cubre espera
de cabeceras, cuerpo y envío de respuesta; no interrumpe código Python que ya
esté calculando o esperando el lock. Se usa un worker y un temporizador por
conexión admitida; ambos se liberan al terminar. El cierre del servidor interrumpe
también las conexiones activas. En Windows una lectura ya bloqueada puede tardar
hasta un timeout de socket adicional en liberar el worker, aunque el peer ya vea
el cierre; no se promete que el hilo termine exactamente al vencer el plazo.
No es aislamiento de CPU ni defensa contra una
inundación local sostenida; el receptor continúa limitado a loopback.

El buffer conserva hasta **500 mensajes y 16 MiB de JSON canónico**, aplicando
ambos límites y desalojando primero los mensajes más antiguos. Un mensaje que
supere el presupuesto configurado se rechaza sin cambiar el buffer. Es un
presupuesto de contenido serializado, no un límite de RAM del proceso: objetos
Python, índices y peticiones en curso consumen memoria adicional acotada por sus
respectivos límites. El máximo HTTP sigue siendo 256 KiB por cuerpo.

Los índices de duplicados, event IDs y últimas secuencias se conservan únicamente
mientras haya mensajes retenidos de su ámbito. Por tanto las sesiones retenidas
no pueden superar el número de mensajes. Un reintento antiguo de una sesión aún
retenida puede ser rechazado como obsoleto; una sesión completamente desalojada
se considera desconocida y puede volver a aceptarse. **No hay protección durable
contra replay**, tampoco tras reiniciar el proceso. Los contadores no sustituyen
un historial autoritativo. Las copias defensivas evitan que un consumidor cambie
el contenido retenido o amplíe la memoria por una referencia compartida.

Configuración opcional del receptor:

```text
uv run python scripts/telemetry_receiver.py --max-connections 8 --request-timeout 5 --max-messages 500 --max-retained-mib 16
```

Rangos: 1..32 conexiones, 0.05..30 segundos, 1..10000 mensajes y 1..64 MiB por CLI.
`/health` informa conexiones activas/rechazadas/expiradas, sesiones retenidas y
bytes canónicos, sin copiar ni exponer el último payload. Un socket que agota su
timeout de inactividad puede cerrarse antes del temporizador absoluto y no sumar
al contador de expiraciones de este último.

Desde el ADR-0005, el adaptador del dashboard consulta este `/health` (sin token)
en cada poll y publica en `/api/state` un resumen acotado como `source_health`:
aceptados, duplicados, secuencias faltantes, retenidos, sesiones y
`history_status`. Los contadores siguen siendo globales del receptor desde su
inicio; la interfaz los rotula así.

Las pruebas locales cubren cuerpos y cabeceras incompletos, saturación, vencimiento
absoluto controlado, cierre, fallo al crear worker, churn de sesiones, presupuesto
por bytes y semántica de replay tras desalojo. No acceden a MT5.

### Procedimiento supervisado

El procedimiento operativo completo, incluida la coexistencia multterminal,
actualización, rollback, retiro y evidencia mínima, está en
[Operación supervisada del collector MT5](mt5-collector-operations.md). La lista
siguiente conserva el alcance específico del piloto:

1. Revisar la fuente y compilarla con MetaEditor sin warnings.
2. Iniciar el receptor con un token efímero.
3. Autorizar únicamente `http://127.0.0.1:8766` en una terminal demo.
4. Configurar localmente `ExpectedDemoLogin` y `ExpectedDemoServer` de la demo
   autorizada y adjuntar el EA a un solo gráfico.
5. Ejecutar el dashboard con la fuente de telemetría y el `source_id` esperado.
6. Validar cuenta, posiciones, órdenes, Magic Numbers, costes, timestamps y
   latencia contra el terminal o una captura Python aislada.
7. Interrumpir el receptor durante más de 12 intervalos: comprobar descartes
   `queue_full`, reanudarlo y verificar avance, drenaje e idempotencia. Repetir con
   token incorrecto y restaurarlo: no debe quedar atascado en un mensaje rechazado.
8. Reiniciar el EA y comprobar la nueva sesión.
9. Retirar el EA y revocar/eliminar el token de prueba.

## Gate de promoción operativa

La topología ya fue decidida por ADR-0004. No se usará una cuenta real ni se
diseñará un endpoint remoto hasta documentar:

- corrección y completitud del contrato del collector con operaciones reales;
- latencia y comportamiento prolongado del collector;
- comportamiento ante desconexiones;
- consumo del terminal y tamaño de payload;
- frecuencia necesaria para cuenta, operaciones, riesgo y velas;
- necesidad de persistencia y política de retención.

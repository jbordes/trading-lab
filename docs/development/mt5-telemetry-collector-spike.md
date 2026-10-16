# Spike de colector de telemetría MT5

**Fecha:** 2026-10-16

**Estado:** infraestructura local implementada y fuente compilada; prueba demo pendiente

**Decisión:** [ADR-0003](../adr/0003-mt5-push-telemetry-spike.md)

## Objetivo

Comprobar si un colector MQL5 propio complementa la API Python cuando el terminal
está en otra VPS o se necesita reaccionar a actividad con menor demora. El spike
no reemplaza la fuente Python ni implementa métricas de riesgo.

```text
Terminal demo MT5
    |
    | POST /v1/telemetry + Bearer token
    v
receptor 127.0.0.1:8766
    |
    v
buffer acotado en memoria + /health
```

El receptor es un proceso separado. El servidor del dashboard continúa
rechazando `POST` y no conoce el token de ingestión.

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

No expone un listado histórico completo y se pierde al detener el proceso.

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
ejecución. Compilarla no equivale a ejecutarla: en una terminal de pruebas aislada,
ejecutarla como script y exigir `TradingLab outbox tests: 0 failure(s)`.
Los checks Python verifican el orden captura/envío y el receptor; la prueba
nativa y la desconexión real del piloto son validaciones diferentes.

## Prueba manual pendiente

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
Su ejecución en MT5 sigue pendiente; compilar no demuestra esas aserciones.

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
ser ASCII imprimible sin espacios ni controles. Esto no añade límites de hilos,
timeout de lectura ni retención de sesiones: siguen pendientes del punto 6.

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
desconexión y cambios de login/servidor. Están compiladas; su ejecución y los
cambios reales de cuenta quedan pendientes de un terminal de pruebas aislado,
nunca de la terminal que esté ejecutando los bots del socio.

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
reconstrucción de equity, emparejamiento de trades ni cambio de UI/dashboard.

`/health` publica solo estado y cantidad retenida de historial, nunca sus filas.
Las pruebas Python cubren entrada/salida entre muestras, solapamientos, tickets
con igual milisegundo, reinicios, correcciones, filtros, límites y errores; la
prueba nativa usa un historial simulado y sigue pendiente de ejecución en MT5.

### Procedimiento supervisado

1. Revisar la fuente y compilarla con MetaEditor sin warnings.
2. Iniciar el receptor con un token efímero.
3. Autorizar únicamente `http://127.0.0.1:8766` en una terminal demo.
4. Configurar localmente `ExpectedDemoLogin` y `ExpectedDemoServer` de la demo
   autorizada y adjuntar el EA a un solo gráfico.
5. Ejecutar simultáneamente el dashboard con fuente Python.
6. Comparar cuenta, posiciones, órdenes, Magic Numbers, timestamps y latencia.
7. Interrumpir el receptor durante más de 12 intervalos: comprobar descartes
   `queue_full`, reanudarlo y verificar avance, drenaje e idempotencia. Repetir con
   token incorrecto y restaurarlo: no debe quedar atascado en un mensaje rechazado.
8. Reiniciar el EA y comprobar la nueva sesión.
9. Retirar el EA y revocar/eliminar el token de prueba.

## Gate de decisión

No se diseñará un endpoint remoto hasta documentar:

- brechas reales de la API Python;
- latencia y completitud de ambos mecanismos;
- comportamiento ante desconexiones;
- consumo del terminal y tamaño de payload;
- frecuencia necesaria para cuenta, operaciones, riesgo y velas;
- necesidad de persistencia y política de retención.

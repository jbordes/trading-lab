# Collectors MT5: recuperación y trabajo acotado

Estado: implementación preparada; pendiente validación nativa y operacional
humana antes de sustituir los EAs instalados. No se modificó la terminal.

Rama: `feature/mt5-collector-resilience`, desde `fix/relay-multiple-listeners`.
Versiones: Telemetry `0.2.0`, Activity `activity-0.7.0`. Contratos v1/v2, rutas,
identidades y claves de cursor existentes se conservan. No requiere migrar SQLite.

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

## Instalación futura, no ejecutada

Requiere aprobación humana. Copiar juntos ambos `.mq5` y los dos `.mqh` al
directorio autorizado, compilar y recargar únicamente collectors, conservando
inputs, tokens, SourceIds y cursores. No borrar variables `TL2.ACT.*`, recrear la
base ni reiniciar EAs de trading para aplicar este refactor. Registrar versión y
hashes siguiendo [la operación de collectors](mt5-collector-operations.md).

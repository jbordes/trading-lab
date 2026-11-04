# Relay con outbox durable: primera entrega local

Estado: implementación optativa para prueba aislada; sin activación en MT5 ni
despliegue en la Mac. Nace de `feature/clean-sqlite-v5` (PR 57).

## Responsabilidades

Los EAs envían al relay en loopback. Solo después del commit local responde
202 (nuevo) o 200 (duplicado). Un worker reenvía el mensaje al receptor central
correspondiente v1/v2. Guarda el sobre canónico completo: identidad, captura y
payload originales; no rejuvenece tiempos ni genera otra secuencia al reintentar.

La outbox es una base SQLite propia, esquema 1; no es la base histórica SQLite
v5 ni requiere migrarla. El cuerpo se conserva hasta el ACK central válido y
luego se libera. La huella y la identidad permanecen para deduplicar reenvíos
del EA, incluso después de un reinicio. No se guardan tokens en la base.

El mismo commit local guarda cuerpo y metadatos. Si el proceso cae antes de
confirmar al EA, el EA puede repetir. Si el receptor central confirma en disco
pero se pierde el ACK, el relay repite el mensaje y valida el 200 de duplicado.

El relay autentica fuente, cuenta y rol antes de encolar. V1 conserva identidad
de cuenta en snapshots; sus heartbeats no incluyen esa identidad y se autorizan
por credencial/fuente. No se autoprovisionan productores.

## Preparación aislada

Usar un directorio local privado existente y rutas absolutas, fuera de carpetas
sincronizadas o de red. Los ejemplos de rutas deben reemplazarse en cada equipo.

```text
uv run python scripts/telemetry_relay.py --queue "C:\TradingLabData\relay.sqlite3" --init-queue
```

El comando crea una cola nueva verificada y termina. No sobrescribe un destino.
En la Mac la ruta equivalente podría ser `/Users/tu_usuario/TradingLabData/relay.sqlite3`.
La cola permanecerá en la VPS cuando la API central esté en la Mac.

Copiar y adaptar [la topología de ejemplo](telemetry-relay.example.json) a un
archivo local. Define las identidades y targets; las credenciales se referencian
por nombre de variable. V1 utiliza rol live; v2 admite live/activity según fuente.
Configurar credenciales distintas para cada productor y frontera. El token local
debe coincidir con el EA; el central, con el receptor de destino.

Se admiten variables del proceso o un archivo local ignorado `.env.relay` con
asignaciones `RELAY_...=valor`, una por línea y sin comillas. No versionarlo ni
compartirlo. La topología no admite tokens literales. Para arrancar:

```text
uv run python scripts/telemetry_relay.py --queue "C:\TradingLabData\relay.sqlite3" --config "C:\TradingLabData\relay.json" --secrets-file .env.relay --port 8780
```

El listener queda en `127.0.0.1:8780` y admite ambas rutas POST, `/v1/telemetry`
y `/v2/telemetry`. `GET /health` informa estados, errores acotados, bytes de
cuerpos pendientes, antigüedad del más antiguo y última confirmación central
(Unix UTC en segundos, o null). No expone cuerpos ni tokens.

Una sola instancia puede usar la misma outbox gracias al lock del sistema
operativo. Se mantiene tras fallos y reinicios; no se necesitan conexiones MT5
desde Python. El archivo lock puede permanecer al cerrar, sin retener el bloqueo.

## Orden, límites y errores

- Se envía primero el pendiente más antiguo de cada fuente/version. Un rechazo
  bloquea esa fuente; otras fuentes continúan. Un ciclo envía hasta un mensaje
  por fuente y se repite cada 250 ms, además de la duración de los envíos.
- Se acepta actividad histórica v2 fuera de secuencia; los flujos de estado vivo
  y heartbeat rechazan secuencias antiguas desconocidas, conservando duplicados.
- Timeout, 5xx y 408/429 reintentan con backoff persistido de 1 a 256 segundos.
  Errores 3xx/4xx restantes requieren revisión y quedan rechazados, sin descartar
  el mensaje. No se siguen redirects ni proxies de entorno. HTTPS valida certificados;
  HTTP se permite solo con `127.0.0.1` para pruebas.
- Un 200/202 sin el cuerpo JSON esperado conserva el pendiente. Un ACK local
  describe admisión local; nunca implica cobertura ni persistencia central.
- Por defecto: 64 MiB de cuerpos pendientes y 100.000 registros totales, incluyendo
  huellas ya confirmadas. Al alcanzar un límite, rechaza mensajes nuevos con 503;
  los duplicados siguen siendo reconocibles. `--max-mib` y `--max-records` ajustan
  límites. Son límites lógicos; el archivo incluye índices, páginas libres y
  metadatos adicionales. No constituye una cuota rígida del filesystem.
- La compactación/retención de huellas requiere otra política. Esta entrega no
  borra huellas automáticamente; al agotar el total hay que revisar capacidad
  antes de extender límites. No borrar la outbox para desbloquear una captura real.

La combinación cuenta/rol/identidad/target queda vinculada al stream en la cola.
Se pueden rotar tokens manteniendo esa vinculación; cambiar el host exige un
corte planificado de pendientes, no una reasignación silenciosa.

Tras corregir una causa de rechazo, detener el relay y revisar (vista previa):

```text
uv run python scripts/telemetry_relay.py --queue "C:\TradingLabData\relay.sqlite3" --retry-stream v2:synthetic-activity
```

Agregar `--apply` para rehabilitar esos mensajes y arrancar de nuevo. Mantiene
identidad y contenido; no omite un 409 ni cambia la operación que lo produjo.

## Compatibilidad con el sistema actual

El relay no sirve las lecturas `/v1/snapshot` o `/v2/activity` del dashboard.
El backend histórico sigue consultándose en los receptores de destino.
No cambiar puertos de los receptores actuales ni EAs hasta aprobar un piloto.
El receptor central v1 puede separar lectura usando `TRADINGLAB_V1_READ_TOKEN` al
ejecutar `scripts/telemetry_receiver.py`; el token de ingesta deja entonces de
autorizar lecturas y el token de lectura no autoriza ingesta. Si no se configura,
se conserva la compatibilidad anterior de token único. El supervisor del piloto
no añade un nuevo prompt ni cambia los tokens existentes en este incremento.

Los receptores SQLite admiten mensajes con capturas antiguas; sus proyecciones
conservan la captura original y no infieren frescura del ACK. El modo memoria v1
no es un destino válido para garantías durables: usar siempre receptor SQLite.

## Pendientes antes de activar en la Mac

- Preparar servicios macOS y transporte privado HTTPS/Tailscale.
- Conectar las lecturas del dashboard al backend remoto y sus credenciales.
- Confirmar configuración persistente de receptores y permisos del directorio.
- Observar capacidad y atraso del piloto; definir retención de huellas y manejo
  de crecimiento, así como objetivos operativos antes de una cuenta real.
- La prioridad interna entre backfill y actividad reciente de una misma fuente
  sigue a cargo de Activity: el relay preserva su orden y no lo reordena.

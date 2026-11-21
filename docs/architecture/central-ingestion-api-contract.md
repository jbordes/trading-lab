# Contrato de la API central de ingesta

Estado: contrato descriptivo en la rama actual, pendiente de integración. El despliegue conectado
a la Mac y la migración de datos siguen pendientes.

## Fronteras y compatibilidad

Los EAs publican por loopback en la VPS. Un relay persiste mensajes pendientes
y los envía a la API central. API y SQLite viven en el mismo host. Los contratos
descriptivos usan `POST /api/account-state` y `POST /api/trading-events` con
formatos `mt5-account-state-v1` y `mt5-trading-events-v1`; la API usa esquema
SQLite global 7.

El contrato de estado de cuenta aporta el snapshot y el contrato de eventos de
trading aporta live, actividad y ciclos. Ambos se persisten en un único archivo
SQLite central con fuentes separadas por rol bajo esquema global 7. La API
descriptiva no versiona la base. No hay aliases HTTP para las rutas anteriores,
ni runtimes desplegables de los receptores aislados
([ADR-0021](../adr/0021-descriptive-central-api-contract.md)).

## Identidad y permisos

La asociación credencial → productor → fuente → cuenta se provisiona fuera de
la ingesta. Ningún mensaje registra una cuenta automáticamente. Los roles
`snapshot`, `live` y `activity` restringen tipos de mensaje; lectura usa
credencial independiente.
El relay tendrá credenciales centrales distintas de las locales de los EAs.
Las credenciales se envían solo en Authorization, nunca en URL ni ejemplos reales.

V1 permite una credencial de lectura independiente configurada explícitamente;
mantiene token compartido como compatibilidad cuando no se indica. Antes de
exponer v1 por el transporte central se debe activar el modo separado.

No se publican DELETE/PATCH de datos ni comandos de trading. Provisión y migración
siguen siendo CLI administrativas con aprobación humana.

## Confirmaciones, reintentos e integridad

La API central confirmará solo tras commit durable: 202 para mensaje aceptado y
200 para duplicado idéntico. V2 conserva `status`, `sequence_gap`, `out_of_order`;
v1 conserva `status`, `sequence_gap`. Un código sin cuerpo válido no es confirmación.
El cliente valida la respuesta del único envío en curso contra su contrato.

El relay conserva bytes y la identidad original (fuente, sesión, secuencia,
event_id). No inventa una identidad nueva al reintentar. Confirmar al EA exige
commit local; eliminar el pendiente exige ACK central durable. Persistencia del
pendiente y confirmación local deben quedar coordinadas para evitar una ventana
de pérdida. Un reinicio tras commit central pero antes del ACK produce un reenvío
idempotente. Un ACK perdido no autoriza avanzar una ventana no confirmada.

Los conflictos 409 no se reintentan indefinidamente: se conservan para revisión.
Timeout, corte y 503 admiten backoff acotado; 400/401/403/413/415 requieren corregir
mensaje, autorización o configuración. La cola será acotada en disco; al llenarse
dejará de confirmar nuevos mensajes y mostrará el bloqueo. No descartará pendientes
silenciosamente. El procesamiento mantendrá orden por fuente/sesión y prioridad
para actividad reciente sin eliminar recuperación profunda.

La recuperación histórica central deberá admitir mensajes antiguos legítimos.
Antes del relay hay que revisar las guardas de frescura y secuencia existentes:
reenviar una captura antigua no la convierte en estado vivo reciente. No se
promete que el receptor local actual admita cualquier backlog remoto sin ajustes.

## Límites y observabilidad

Se conserva el máximo de 256 KiB y el límite configurado menor, JSON estricto,
timeout y conexiones acotadas. El transporte central incorporará límites por
productor y permisos de red. No se cambia la escucha loopback en este paso.
Registrar profundidad/bytes de cola, último ACK central, edad del pendiente más
antiguo y causa de bloqueo; no confundir heartbeat, conectividad y cobertura.

Las rutas de lectura descriptivas son `/api/accounts/health`, `/api/accounts/snapshot`,
`/api/accounts/deals`, `/api/accounts/history`, `/api/trading/activity`,
`/api/trading/activity-progress`, `/api/trading/position-cycle-magics` y
`/api/trading/position-cycles`. `/health`, `/docs` y `/openapi.json` no cambian.
La credencial se separa en `CENTRAL_SNAPSHOT_INGEST`, `CENTRAL_ACCOUNT_READ`,
`CENTRAL_LIVE_INGEST`, `CENTRAL_ACTIVITY_INGEST` y `CENTRAL_TRADING_READ`.
Las claves de host son `snapshot_source_id`, `live_source_id` y
`activity_source_id`. Para el procedimiento de transición, consulte la
[guía de cutover](../development/descriptive-api-cutover.md).

Las lecturas conservan paginación y filtros del [catálogo vigente](../development/api-reference.md).
No inferir ausencia de operaciones por fallos de red ni cobertura completa por
conteos iguales. Conservar tiempos originales MT5 y captura UTC por separado.

## Documentación accesible

Cada receptor ofrece `/docs` y `/docs.json` con rutas, permisos, parámetros,
errores y ejemplos. El catálogo solo describe capacidades implementadas del
receptor servido. No lee SQLite ni refleja headers, tokens o configuración real.
Se sirve sin JavaScript/CDN, sin guardar credenciales ni ejecutar escrituras.

## Entregables y cierre de este paso

Este contrato formaliza las fronteras y la referencia HTTP navegable. El bootstrap
de la base central con esquema 7, el relay durable y las credenciales separadas
están descritos en sus guías operativas. Permanecen pendientes el traslado entre
hosts, HTTPS, el servicio macOS y las pruebas de cortes entre máquinas. No
constituye aprobación de despliegue remoto.

Evolución: el [relay optativo](../development/durable-telemetry-relay.md) implementa
outbox, reintentos y ACK local/central con tests SQLite. La activación remota y
las lecturas del dashboard permanecen pendientes.

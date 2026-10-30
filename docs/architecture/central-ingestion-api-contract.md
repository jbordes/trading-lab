# Contrato de la API central de ingesta

Estado: contrato objetivo aprobado para el programa remoto; transporte y
despliegue pendientes. Las rutas y mensajes locales ya existen.

## Fronteras y compatibilidad

Los EAs publican por loopback en la VPS. Un relay persistirá mensajes pendientes
y los enviará por HTTPS a la API central. API y SQLite viven en el mismo host.
Se mantienen `POST /v1/telemetry` y `POST /v2/telemetry` con sus sobres actuales;
la versión HTTP no equivale a la versión 5 del esquema SQLite.

V1 continúa aportando estado vivo y v2 actividad y ciclos. No se fusionan bases
ni se fuerza una conversión v1/v2 en este incremento. El despliegue deberá
resolver ambos receptores y sus lecturas para mantener completo el dashboard.

## Identidad y permisos

La asociación credencial → productor → fuente → cuenta se provisiona fuera de
la ingesta. Ningún mensaje registra una cuenta automáticamente. En v2 los roles
live/activity restringen tipos de mensaje; lectura usa credencial independiente.
El relay tendrá credenciales centrales distintas de las locales de los EAs.
Las credenciales se envían solo en Authorization, nunca en URL ni ejemplos reales.

La compatibilidad v1 conserva hoy un token compartido para lectura e ingesta.
Separar esas credenciales es un requisito previo a exponer v1 por el transporte
central: la documentación actual no afirma que ese aislamiento ya exista.

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

Las lecturas conservan paginación y filtros del [catálogo vigente](../development/api-reference.md).
No inferir ausencia de operaciones por fallos de red ni cobertura completa por
conteos iguales. Conservar tiempos originales MT5 y captura UTC por separado.

## Documentación accesible

Cada receptor ofrece `/docs` y `/docs.json` con rutas, permisos, parámetros,
errores y ejemplos. El catálogo solo describe capacidades implementadas del
receptor servido. No lee SQLite ni refleja headers, tokens o configuración real.
Se sirve sin JavaScript/CDN, sin guardar credenciales ni ejecutar escrituras.

## Entregables y cierre de este paso

Este paso formaliza las fronteras y entrega la referencia HTTP navegable. Quedan
para pasos posteriores creación v5, traslado entre hosts, relay durable,
aislamiento de credenciales v1, ajustes para backlog, HTTPS, servicio macOS y
pruebas de cortes. No constituye aprobación de despliegue remoto.

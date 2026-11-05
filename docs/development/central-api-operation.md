# API central FastAPI: operación local

Estado: el piloto local anterior fue validado en Juampi el 5 de noviembre de
2026. El contrato descriptivo y esquema 7 están en la rama actual, pendientes de
integración y revisión; no están instalados. No sustituye EAs de trading.

El dashboard admite las lecturas de cuenta y trading en el mismo puerto mediante
`--central-api-port`. Ver [arranque conjunto y operación](central-api-dashboard.md).
`GET /api/accounts/health` requiere credencial de lectura de cuenta; `/health`
permanece mínimo y público.

## Qué cambia

El comando `scripts/central_api.py` sirve ingesta y lecturas descriptivas en un
único puerto. El contrato nuevo usa `central.sqlite3`, esquema global 7 y no
crea ni migra la base durante el arranque.

Al iniciar, la API valida esquema, identidad y fuentes sin reconstruir el
historial completo de actividad. Esto no equivale a una auditoría completa de
payloads: la comprobación explícita `account_evidence` conserva la verificación
de hashes y sus validaciones, y puede leer la evidencia histórica. El snapshot
actual sí puede leerse en el arranque. No cambian el esquema 7 ni la regla de no
migrar automáticamente.

Las consultas de actividad usan lectores SQLite independientes en modo de solo
lectura. Las lecturas admitidas comparten una transacción consistente entre
página y coverage dentro de cada solicitud, no entre páginas. Se admiten hasta
dos a la vez sin esperar en cola; el límite cooperativo es de 2 s, con progreso
SQL cada 1000 operaciones y espera de locks SQLite de hasta 0.1 s. No es una
interrupción instantánea ni elimina toda contención SQLite. Si se satura o vence
el presupuesto, la API devuelve el error existente `503 storage_unavailable`,
nunca datos parciales. El lector cierra su conexión y libera cupo incluso ante
fallos; durante el cierre del receptor las consultas ya admitidas pueden
terminar y las nuevas se rechazan. El ingreso mantiene escritura atómica y ACK
posterior al commit.

- `http://127.0.0.1:8781/openapi.json`: especificación OpenAPI real.
- `http://127.0.0.1:8781/docs`: Swagger UI con modelos, autorización y ejemplos.
- `http://127.0.0.1:8781/redoc`: referencia alternativa.
- `http://127.0.0.1:8781/health`: disponibilidad básica, sin filas ni secretos.

Swagger UI y ReDoc usan los assets CDN predeterminados del framework y necesitan
acceso a Internet en el navegador. La especificación JSON y los endpoints no
dependen de esa UI. No se guarda la autorización entre recargas y se desactiva
el validador externo de Swagger. Los ejemplos son sintéticos: reemplazar fuente,
identidad y fechas antes de probar una ingesta. Usar un directorio y bases de prueba.

El contrato nuevo ofrece `POST /api/account-state` y `POST /api/trading-events`,
además de las lecturas `/api/accounts/*` y `/api/trading/*`. Las rutas antiguas
y los receptores separados son históricos; no se deben usar como configuración
del nuevo contrato. En el piloto local validado, los collectors envían al relay
`8776/8777`, éste reenvía a FastAPI `8781` y el dashboard `8775` lee FastAPI.

## Preparación

Sincronizar el entorno: `uv sync --locked`. Se usa Python 3.14 y las versiones
de FastAPI, Pydantic, Uvicorn y herramientas de prueba fijadas en `uv.lock`.

Crear y provisionar una base central/esquema 7 nueva con el bootstrap remoto.
Mantenerla en un directorio privado de disco local, fuera de Git y de carpetas
sincronizadas. La cuenta y las tres fuentes de estado de cuenta, live y activity
deben estar registradas. El arranque no convierte las bases del piloto anterior.

Configurar cinco credenciales distintas en el entorno o en un archivo ignorado
`.env.central`, con asignaciones `NOMBRE=valor`, sin comillas:

| Variable | Uso |
| --- | --- |
| `CENTRAL_SNAPSHOT_INGEST` | Ingesta de estado de cuenta |
| `CENTRAL_ACCOUNT_READ` | Lecturas de cuenta |
| `CENTRAL_LIVE_INGEST` | Ingesta de trading live |
| `CENTRAL_ACTIVITY_INGEST` | Ingesta de actividad |
| `CENTRAL_TRADING_READ` | Lecturas de trading |

Todas deben tener 24..256 caracteres ASCII imprimibles sin espacios. Ninguna es
el token humano del dashboard. Los tokens centrales de ingesta deben coincidir
con los configurados en el relay; los tokens locales del EA siguen siendo otros.
El archivo admite exclusivamente estas cinco variables y el entorno prevalece.

## Arranque explícito

Ejemplo Windows, reemplazando rutas e identidades:

```text
uv run python scripts/central_api.py --db "C:\TradingLabData\central.sqlite3" --source-id demo-terminal-01 --account-id account-demo --secrets-file .env.central --port 8781
```

En macOS utilizar rutas absolutas `/Users/tu_usuario/TradingLabData/...`. El
comando se limita a loopback, un worker y concurrencia acotada. No acepta headers
proxy de clientes. El servicio privado HTTPS/Tailscale y sus reglas de Host/Origin
se resolverán antes del despliegue remoto; no basta con cambiar el bind a público.

Un lock asociado a la base evita otra instancia de esta CLI sobre el mismo
archivo. Detener con Ctrl+C para cerrar recursos mediante lifespan.

## Semántica y verificaciones

Ingesta conserva `202 accepted` y `200 duplicate`, emitidos después de persistir.
El relay valida el cuerpo del ACK; los EAs actuales reconocen esos códigos HTTP.
Los modelos no convierten strings, booleanos o identificadores a tipos ajenos al
contrato. Se conservan fechas de captura originales y tiempos MT5 del broker.

Los validadores existentes siguen comprobando JSON UTF-8 sin claves repetidas,
profundidad, números finitos, límites, identidad, rangos, conteos, paginación y
relaciones entre campos. OpenAPI describe la estructura; las reglas semánticas
entre campos no se expresan todas mediante JSON Schema. Se prueban ambas capas
con los mismos fixtures. El límite de cuerpo sigue siendo 256 KiB y la lectura
tiene plazo. El servidor requiere Content-Length y rechaza framing ambiguo.

Errores: 400 para entradas inválidas, 401 para credenciales, 403 para permisos,
409 para identidad/secuencia, 411 para longitud, 413 para exceso, 415 para tipo,
503 para almacenamiento. Un fallo del modelo de respuesta se considera error
interno 500. Los mensajes no reflejan el cuerpo recibido ni detalles de validación
con datos sensibles. No se utiliza la respuesta 422 predeterminada.

La nueva API agrega validación de consultas/Host/Origin y errores homogéneos;
no promete que cada etiqueta de error de los handlers antiguos sea idéntica.
Las garantías de aceptación, idempotencia y tipos de negocio se conservan.

La integración local validada envía el relay a ambos targets:
`http://127.0.0.1:8781/api/account-state` y
`http://127.0.0.1:8781/api/trading-events`. La verificación de ACK central y
persistencia para el contrato nuevo queda pendiente de su implementación y
cutover coordinado. El despliegue privado remoto, TLS/Tailscale y cualquier operación
con cuentas reales siguen pendientes. Cambiar targets de una cola existente
exige un corte planificado porque están vinculados a la identidad del stream.
No reutilizar la cola operativa a ciegas.

# API central FastAPI: operación local

Estado: preparada para piloto local. No se activó en MT5 ni en la Mac.

El dashboard admite v1/v2 en el mismo puerto mediante `--central-api-port`.
Ver [arranque conjunto y pruebas](central-api-dashboard.md). El diagnóstico
`GET /v1/health` requiere lectura v1 y no expone el snapshot; `/health` permanece
mínimo y público.

## Qué cambia

El comando `scripts/central_api.py` sirve ingesta y lecturas v1/v2 en un único
puerto. Utiliza las dos bases durables existentes y abre/cierra sus receptores
mediante lifespan. No crea ni migra las bases durante el arranque.

- `http://127.0.0.1:8781/openapi.json`: especificación OpenAPI real.
- `http://127.0.0.1:8781/docs`: Swagger UI con modelos, autorización y ejemplos.
- `http://127.0.0.1:8781/redoc`: referencia alternativa.
- `http://127.0.0.1:8781/health`: disponibilidad básica, sin filas ni secretos.

Swagger UI y ReDoc usan los assets CDN predeterminados del framework y necesitan
acceso a Internet en el navegador. La especificación JSON y los endpoints no
dependen de esa UI. No se guarda la autorización entre recargas y se desactiva
el validador externo de Swagger. Los ejemplos son sintéticos: reemplazar fuente,
identidad y fechas antes de probar una ingesta. Usar un directorio y bases de prueba.

Las rutas `/v1/telemetry`, `/v1/snapshot`, `/v1/deals`, `/v1/account-history`,
`/v2/telemetry`, `/v2/activity`, `/v2/activity-progress`, `/v2/position-cycles` y
`/v2/position-cycle-magics` están disponibles con modelos documentados. Los
receptores anteriores y sus catálogos `/docs.json` continúan separados; no fueron
sustituidos en la configuración del dashboard ni de los EAs.

## Preparación

Sincronizar el entorno: `uv sync --locked`. Se usa Python 3.14 y las versiones
de FastAPI, Pydantic, Uvicorn y herramientas de prueba fijadas en `uv.lock`.

Provisionar las bases locales v1 y v2/esquema 5 por sus comandos independientes.
Mantenerlas en un directorio privado de disco local, fuera de Git y de carpetas
sincronizadas. La fuente v1 y la cuenta v2 ya deben estar registradas. Ver
[creación v5](create-sqlite-v5.md) y [operación v1](telemetry-operation.md).

Configurar cinco credenciales distintas en el entorno o en un archivo ignorado
`.env.central`, con asignaciones `NOMBRE=valor`, sin comillas:

| Variable | Uso |
| --- | --- |
| `CENTRAL_V1_INGEST` | Productor/relay de estado vivo v1 |
| `CENTRAL_V1_READ` | Lecturas v1 |
| `CENTRAL_V2_LIVE` | Productor/relay live v2, si se utiliza |
| `CENTRAL_V2_ACTIVITY` | Productor/relay de actividad v2 |
| `CENTRAL_V2_READ` | Lecturas v2 |

Todas deben tener 24..256 caracteres ASCII imprimibles sin espacios. Ninguna es
el token humano del dashboard. Los tokens centrales de ingesta deben coincidir
con los configurados en el relay; los tokens locales del EA siguen siendo otros.
El archivo admite exclusivamente estas cinco variables y el entorno prevalece.

## Arranque explícito

Ejemplo Windows, reemplazando rutas e identidades:

```text
uv run python scripts/central_api.py --v1-db "C:\TradingLabData\piloto.sqlite3" --v2-db "C:\TradingLabData\piloto-v2.sqlite3" --source-id demo-terminal-01 --account-id account-demo --secrets-file .env.central --port 8781
```

En macOS utilizar rutas absolutas `/Users/tu_usuario/TradingLabData/...`. El
comando se limita a loopback, un worker y concurrencia acotada. No acepta headers
proxy de clientes. El servicio privado HTTPS/Tailscale y sus reglas de Host/Origin
se resolverán antes del despliegue remoto; no basta con cambiar el bind a público.

Un lock asociado a la base v2 evita otra instancia de esta CLI sobre ese mismo
archivo. No impide abrir intencionadamente otros lectores/receptores; durante el
piloto usar solo un escritor central por base. Detener con Ctrl+C para cerrar
recursos mediante lifespan.

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

Después de integrar esta entrega, probar el relay contra ambos targets en
`http://127.0.0.1:8781/v1/telemetry` y `/v2/telemetry` con una cola y bases aisladas.
Cambiar targets de una cola existente exige un corte planificado porque están
vinculados a la identidad del stream. No reutilizar la cola operativa a ciegas.

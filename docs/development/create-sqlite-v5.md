# Crear una base SQLite v5 vacía

El comando portable `scripts/create_telemetry_v2_db.py` crea una base nueva con
el esquema actual (5), una cuenta interna y sus fuentes live/activity, sin
historial ni mensajes. No requiere tokens ni una conexión a MT5.
`v2` identifica el contrato de telemetría; `5` identifica el esquema SQLite.

## Preparación y vista previa

Usar un directorio local privado existente, independiente del checkout. En la
Mac elegir una ruta absoluta como `/Users/tu_usuario/TradingLabData`; en Windows,
`C:\TradingLabData`. Crear ese directorio previamente con las herramientas del
sistema. No utilizar carpetas de red ni carpetas sincronizadas por iCloud/Drive.

Desde el checkout sincronizado (`uv sync --locked`), ejemplo macOS en una línea:

```sh
uv run python scripts/create_telemetry_v2_db.py --storage-root /Users/tu_usuario/TradingLabData --filename piloto-v2.sqlite3 --account-id cuenta-demo --label Demo --login-masked '****1234' --server DEMO-SERVER --currency USD --live-source-id demo-live --activity-source-id demo-activity
```

Reemplazar servidor, moneda, login enmascarado y fuentes por las identidades que
se provisionarán en el receptor. El comando imprime destino y versión sin crear
archivos. Agregar `--apply` al mismo comando para crear la base. En Windows usar
una ruta absoluta entre comillas si contiene espacios; el resto de argumentos es
idéntico. No usar el login completo ni credenciales del broker.

Sin `--storage-root`, se conserva el destino histórico `_storage/` del checkout.
El nombre solo admite un archivo `.sqlite3`, sin subdirectorios. Si el destino ya
existe, incluso en vista previa, el comando falla sin modificarlo. No hay `--force`.

## Resultado y verificación

La creación abre y verifica el esquema exacto, integridad y claves foráneas; luego
comprueba la cuenta y los roles registrados. La base se prepara en un directorio
temporal privado dentro del directorio de destino. Solo después de verificarla y
cerrar SQLite se publica mediante un enlace duro que falla si el destino ya
existe, incluso ante creaciones simultáneas. El disco local debe admitir enlaces
duros; si no los admite, falla sin publicar una base incompleta ni reemplazar archivos.

Los fallos normales limpian el temporal. Una terminación abrupta puede dejar un
directorio `.tradinglab-create-*`, pero no publica el archivo final y permite
reintentar con el mismo nombre. No se reutilizan ni eliminan automáticamente
temporales de otros intentos. Cualquier limpieza manual debe realizarse después
de confirmar que no hay una creación en curso.
Se crean las tablas e índices actuales sin pasar por migraciones de esquemas viejos.

No se arranca ningún servicio. El receptor se configura después para usar esta
ruta, la cuenta y las fuentes. El comando anterior
`provision_telemetry_v2_db.py` sigue disponible con los mismos argumentos.

## Creación, migración y traslado

- **Crear desde cero:** este comando; solo destino nuevo, sin copiar operaciones.
- **Actualizar un esquema existente:** `migrate_telemetry_v2_db.py`, con vista
  previa, copia previa verificada y pasos incrementales conocidos. Su CLI actual
  sigue limitada a `_storage/` del checkout.
- **Mover datos entre servidores:** futura exportación/importación consistente;
  no forma parte de este comando ni del incremento actual.

La base v1 del estado vivo continúa siendo independiente. Esta creación no la
reemplaza ni modifica. Para operar el dashboard completo fuera de la VPS habrá
que resolver también su persistencia y transporte conforme al
[contrato central](../architecture/central-ingestion-api-contract.md).

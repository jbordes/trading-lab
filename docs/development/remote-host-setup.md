# Preparar un host remoto para la API central

**Alcance:** bootstrap local de API central y SQLite en Mac, Linux o Windows.
Este procedimiento no despliega el dashboard en Mac, no cambia MT5 y no configura
automáticamente firewall, servicios, Tailscale ni suspensión del sistema.

Después de preparar y probar los servicios, seguir el
[manual de mantenimiento automático](automatic-maintenance.md) para programar
copias, consolidación diaria y compactación **en el host de SQLite**. Su
instalador independiente funciona en Windows, Linux y macOS, con vista previa
por defecto; no configura el arranque de API/relay ni necesita tokens.

## Estado y límites

**Pendiente importante para la instalación de la base de prueba:** ejecutar en
ese mismo host el [checklist de ensayo del mantenimiento automático](automatic-maintenance.md).
Incluye un disparo real del scheduler, backup verificado, primer cierre diario
y revisión de reinicio/reposo y permisos. Los ensayos quedan diferidos hasta
esa instalación; no se activan ahora en la VPS ni se exige probar otros sistemas
operativos antes del piloto elegido.

El piloto actual validado es local: los collectors envían al relay durable y este
reenvía a FastAPI y SQLite. El setup del host remoto prepara una API central en
loopback y una base nueva. No demuestra todavía un piloto extremo a extremo por
Tailscale ni una migración de datos operativos.

La estructura unificada y el esquema global 8 se describen en la guía de
[SQLite de la API central](central-sqlite.md) y siguen el
[ADR-0020](../adr/0020-single-central-sqlite-database.md) y su corrección
[ADR-0021](../adr/0021-descriptive-central-api-contract.md). El contrato
descriptivo está en la rama actual, pendiente de integración; el cutover está pendiente y se detalla
en la [guía correspondiente](descriptive-api-cutover.md). ADR-0020 reemplaza la
decisión inicial de dos archivos del ADR-0019.

No se han confirmado instalaciones reales de este procedimiento en Mac o Linux.
La validación Python disponible es en Windows; las instalaciones manuales en los
otros sistemas y sus checks de CI siguen pendientes. No interpretar código local
validado como despliegue hecho o mergeado.

El destino de integración estable del programa es `feature/remote-data-platform`.
La rama de este cambio es `feature/remote-host-bootstrap` desde
`origin/feature/remote-data-platform`; completar y revisar su PR antes de tomar
la rama estable para el despliegue. El nombre configurado es
`feature/remote-data-platform`; `feature/remote-data-perform` no es la rama.

## Qué instala el bootstrap

Los wrappers por sistema son:

- `scripts/prepare_remote_macos.sh`
- `scripts/prepare_remote_linux.sh`
- `scripts/prepare_remote_windows.ps1`

En Mac y Linux llaman a `scripts/bootstrap_remote_host.sh`. Si `uv` no existe,
ese bootstrap descarga e instala el `uv` oficial en `~/.local/bin`; no modifica
el `PATH`. Luego prepara Python 3.14 y dependencias bloqueadas mediante
`uv sync --locked --no-dev` y llama al núcleo portable
`scripts/prepare_remote_host.py`.

El núcleo portable valida el JSON de configuración. Sin `--apply` muestra una
vista previa y no modifica archivos; con `--apply` crea la base y credenciales
locales. La vista previa del wrapper de instalación no valida todo el JSON: la
validación completa ocurre en el núcleo cuando se aplica.

Para crear manualmente solo la base central en un destino absoluto nuevo, use
`scripts/create_central_db.py`; sin `--apply` muestra la vista previa y no
escribe. Ejemplo:

```text
uv run python scripts/create_central_db.py --config RUTA\host.json --database RUTA\central.sqlite3
uv run python scripts/create_central_db.py --config RUTA\host.json --database RUTA\central.sqlite3 --apply
```

La aplicación y el bootstrap llaman al mismo primitivo
`create_registered_database`. Esta CLI crea esquema 8 y sus identidades, pero
no genera secretos, no migra ni elimina bases anteriores y no cambia cursores.

El resultado previsto es:

- `central.sqlite3`, esquema central global, SQLite `user_version=8`, con ambos
  flujos de captura y una sola identidad compartida de cuenta/fuentes;
- `.env.central`, con cinco credenciales de API generadas;
- `.env.dashboard`, con un token humano generado;
- `host.json`, metadatos públicos escritos al final como señal de finalización.

Los nuevos endpoints descriptivos son `/api/account-state` y
`/api/trading-events`, con contratos `mt5-account-state-v1` y
`mt5-trading-events-v1`. El JSON de relay usa la clave `contract` con valores
`account-state` con `role: snapshot` o `trading-events` con `role: live` o
`role: activity`. Combinaciones incompatibles se rechazan. El esquema 8 del
archivo no corresponde a la versión de esos contratos. El creador
comprueba integridad y foreign keys. En POSIX crea el directorio con
permisos `700` y los archivos privados con `600`. En Windows limita la ACL al SID
del usuario actual y `SYSTEM`. No instala MT5 ni configura el relay, dashboard,
servicios del sistema, firewall, suspensión, Tailscale o reglas de red.

El data-dir debe ser una ruta absoluta de destino **nueva**, fuera del checkout;
su carpeta padre debe existir. El instalador no sobrescribe, migra ni borra un
destino anterior. Si falla después de iniciar escrituras, conserva e inspecciona
el estado parcial y escoja otro destino nuevo tras revisión. No reintente
borrando carpetas.

## 1. Preparar el checkout

Después del merge humano del PR del bootstrap, clone el repositorio y seleccione
la rama estable temporal:

```text
git clone https://github.com/jbordes/trading-lab.git TradingLab
cd TradingLab
git switch --track origin/feature/remote-data-platform
```

Si ya tiene el checkout, actualícelo según el flujo de ramas vigente sin
sobrescribir cambios locales. No use `feature/remote-host-bootstrap` como base
estable para otras entregas; esa rama es el origen de este cambio.

No clone ni ejecute código no revisado con permisos administrativos. El host que
se prepara debe ser el destino autorizado y el propietario del sistema debe
controlar el directorio de datos.

En una Mac nueva, `git --version` puede solicitar instalar las herramientas de
línea de comandos de Apple. Complete ese diálogo antes de clonar. También puede
descargar el ZIP de la rama desde GitHub y descomprimirlo. Para probar antes del
merge de este incremento, la rama publicada es `feature/remote-host-bootstrap`;
use `git switch --track origin/feature/remote-host-bootstrap` en lugar de la rama
de integración. No asuma que el script ya existe en esta última antes del merge.

## 2. Crear y editar el archivo de host

Copie `docs/development/remote-host.example.json` a un archivo privado fuera del
checkout. Use un editor local; no pegue aquí el contenido real:

```sh
cp -i docs/development/remote-host.example.json "$HOME/remote-host.json"
```

Edite la copia y sustituya `REEMPLAZAR-SERVIDOR` por el nombre de servidor MT5
exacto. `login_masked` debe coincidir con la forma enmascarada que ya registra
el relay. La cuenta y las fuentes deben coincidir con la configuración actual
del relay. El instalador registra en la base nueva los IDs que indique: no
descubre ni verifica automáticamente la configuración real de su relay.

Use las claves `snapshot_source_id`, `live_source_id` y `activity_source_id`;
son roles separados dentro de la cuenta compartida. No cambie
la identidad de una fuente ya vinculada a la outbox del relay. El host JSON no
contiene tokens.

Proteja el archivo localmente y no lo guarde en Git. Puede contener identidad de
cuenta enmascarada y nombres de fuentes; no es un archivo de secretos, pero debe
permanecer en la máquina de operación.

## 3. Elegir un directorio de datos nuevo

Seleccione un directorio absoluto cuyo padre ya exista y que aún no exista como
destino. Manténgalo fuera del checkout, de carpetas sincronizadas y de unidades
de red. Ejemplos de forma (reemplace por rutas locales aprobadas):

- macOS/Linux: `$HOME/TradingLabData/central-host-01`;
- Windows: `%USERPROFILE%\TradingLabData\central-host-01`.

Si hace falta, cree manualmente solo el directorio padre antes del bootstrap,
dejando el destino final sin crear:

```sh
mkdir -p "$HOME/TradingLabData"
```

En PowerShell:

```powershell
New-Item -ItemType Directory -Path "$env:USERPROFILE\TradingLabData"
```

No apunte a `_storage/`, a una base existente, a la outbox del relay ni a una ruta
de red. La base vacía no migra operaciones ni reinicia los cursores de los EAs;
tampoco recupera automáticamente historial anterior. Cualquier backfill requiere
un plan separado.

## 4. Revisar y aplicar en macOS

No necesita instalar Python, SQLite CLI ni Homebrew previamente. El wrapper
instala `uv` si falta y luego Python y dependencias; requiere `curl`, conexión a
Internet y certificados del sistema. Instala `uv` en `~/.local/bin` sin modificar
`PATH`. Si ya existe otro `uv` en PATH utiliza ese binario.

Vista previa desde la raíz del checkout:

```sh
sh scripts/prepare_remote_macos.sh \
  --config "$HOME/remote-host.json" \
  --data-dir "$HOME/TradingLabData/central-host-01"
```

La vista previa indica el destino, no modifica archivos y no valida todo el JSON.
Revise manualmente el archivo, cuenta/fuentes y destino. Para aplicar, repita el
mismo comando agregando `--apply`:

```sh
sh scripts/prepare_remote_macos.sh \
  --config "$HOME/remote-host.json" \
  --data-dir "$HOME/TradingLabData/central-host-01" \
  --apply
```

La aplicación instala dependencias bloqueadas y ejecuta el núcleo portable, que
valida el JSON y crea el data-dir y sus archivos. No elimina restos si se produce
un fallo. No cierre ni limpie un directorio parcial sin inspección y autorización.

Si `uv` no está en PATH después de instalar, habilite su ruta solo para esta sesión:

```sh
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

## 5. Linux

Instale una distribución soportada y siga la instalación oficial de
[Tailscale para Linux](https://tailscale.com/docs/install/linux/) solo cuando se
prepare la conectividad privada. El wrapper de bootstrap también instala `uv`
oficial si falta; la instalación queda en `~/.local/bin` sin modificar `PATH`.

Vista previa:

```sh
sh scripts/prepare_remote_linux.sh \
  --config "$HOME/remote-host.json" \
  --data-dir "$HOME/TradingLabData/central-host-01"
```

Aplicación:

```sh
sh scripts/prepare_remote_linux.sh \
  --config "$HOME/remote-host.json" \
  --data-dir "$HOME/TradingLabData/central-host-01" \
  --apply
```

Use el mismo proceso de revisión de identidad, destino nuevo, secretos y fallo
parcial descrito para macOS. Linux aquí es una opción soportada por el wrapper;
no se afirma una instalación real probada.

## 6. Windows

Instale Tailscale desde la [guía oficial de Windows](https://tailscale.com/docs/install/windows/)
si se requiere la conectividad privada. Desde PowerShell en la raíz del checkout,
use rutas absolutas:

Prepare antes el JSON en Windows, en vez del comando `cp` de macOS/Linux:

```powershell
Copy-Item -LiteralPath 'docs/development/remote-host.example.json' -Destination "$env:USERPROFILE\remote-host.json" -Confirm
notepad.exe "$env:USERPROFILE\remote-host.json"
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/prepare_remote_windows.ps1 `
  -Config "$env:USERPROFILE\remote-host.json" `
  -DataDir "$env:USERPROFILE\TradingLabData\central-host-01"
```

Ese comando solo presenta la vista previa. Tras confirmar que el destino no
existe, aplicar con `-Apply`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/prepare_remote_windows.ps1 `
  -Config "$env:USERPROFILE\remote-host.json" `
  -DataDir "$env:USERPROFILE\TradingLabData\central-host-01" `
  -Apply
```

No lo ejecute elevado si el usuario ordinario puede escribir en el destino. La
ACL creada limita acceso al SID del usuario actual y `SYSTEM`.
`-ExecutionPolicy Bypass` se limita a este proceso, no cambia la política global.
Si `uv` no está en PATH, para los comandos posteriores use
`& "$env:USERPROFILE\.local\bin\uv.exe"` en lugar de `uv`.

Para programar **solo mantenimiento**, usar
`scripts/configure_telemetry_maintenance.py`, según el
[manual multiplataforma](automatic-maintenance.md). Admite otra base mediante
`--database` y una cuenta mediante `--account-id` sin tocar el arranque de API.

Para programar **ambas tareas Windows** (API y copia), use primero la vista previa y
aplique únicamente tras revisar el destino:

```powershell
uv run python scripts/configure_telemetry_windows_tasks.py --data-dir "C:\TradingLabData\central-host-01"
uv run python scripts/configure_telemetry_windows_tasks.py --data-dir "C:\TradingLabData\central-host-01" --apply
```

Si el arranque debe aceptar el host HTTPS de Tailscale, use el mismo FQDN del
arranque manual **en ambos comandos**, primero para revisar y luego para instalar:

```powershell
uv run python scripts/configure_telemetry_windows_tasks.py --data-dir "C:\TradingLabData\central-host-01" --tailscale-host mac.nombre-tailnet.ts.net
uv run python scripts/configure_telemetry_windows_tasks.py --data-dir "C:\TradingLabData\central-host-01" --tailscale-host mac.nombre-tailnet.ts.net --apply
```

Reemplace el FQDN por el real. La vista previa muestra el host y su origen HTTPS;
no ejecuta Task Scheduler. El argumento se conserva en la tarea de API, pasa a
`run_central_api_job.py` y luego a `run_remote_host.py`, que configura Host y
Origin HTTPS/443 según PY14. No se agrega al mantenimiento. No incluye tokens
ni cambia el bind `127.0.0.1`. Sin el flag se conserva el modo local anterior.

El modo predeterminado no instala tareas. La aplicación crea `TradingLab Central
API` y la tarea de mantenimiento de `central.sqlite3`; el ejecutor de la API es
`scripts/run_central_api_job.py --data-dir <HOSTDIR>`. No instale ni modifique
tareas existentes automáticamente. Las tareas antiguas de receptores deben
revisarse y deshabilitarse manualmente durante el cutover aprobado.
Una tarea ya instalada no recibe este argumento por actualizar el checkout:
revise su acción y acuerde su actualización en una ventana autorizada; el
instalador sigue rechazando sobrescribir tareas existentes.

### Logs del ejecutor supervisado

`run_central_api_job.py` guarda stdout y stderr juntos en
`<HOSTDIR>/operations/central-api.log`. El supervisor drena la salida en bloques
de hasta 64 KiB y rota durante la misma ejecución, sin esperar un reinicio:
archivo activo de hasta 5 MiB más tres copias (`.1` es la más reciente).
Los archivos nuevos quedan acotados a 20 MiB en conjunto. No carga la salida
completa en memoria ni necesita que el proceso escriba saltos de línea.

Solo el propietario del lock del job escribe este log; los archivos se cierran
antes de rotarlos, también en Windows. Si falla el destino de escritura, el
supervisor detiene su hijo en lugar de dejarlo bloqueado en una tubería llena.
La rotación es por bytes: una línea o carácter UTF-8 puede quedar dividido entre
archivos. Los archivos sobredimensionados heredados se conservan como copias y
van saliendo con la rotación normal; no se truncan para corregir su tamaño.

Esta política corresponde al ejecutor supervisado, no a una API iniciada a mano
ni a los logs de MT5. No agrega salida de tokens, configuración o argumentos;
el proceso hijo sigue siendo responsable de no registrar credenciales. No es
una redacción automática de secretos que el hijo hubiera impreso.

### Estado del mantenimiento y ejecuciones simultáneas

`run_telemetry_maintenance.py` actualiza `operations/maintenance-status.json`
únicamente mientras posee `operations/maintenance.lock`, tanto para `running`
como para `succeeded`, `partial`, `deferred` o `failed`. Un intento simultáneo no cambia ese archivo
ni su temporal, y no inicia otra copia de seguridad.

Sus códigos de salida son: `0` para vista previa o trabajo terminado, `1` para
error real y `2` para intento omitido porque otro mantenimiento sigue activo.
La modalidad opt-in `--daily-account-id CUENTA` integra consolidación y retención
después de la copia verificada. Devuelve `3` cuando queda trabajo pendiente o
falta una referencia segura del reloj del broker; no relanza bucles de reintento.
Véase el [mantenimiento diario](daily-account-history-storage.md).
El código `2` se explica en stderr; no representa un fallo del propietario.
Errores previos a obtener el lock (configuración, ruta o permisos) también se
informan por stderr sin sustituir el estado de otra ejecución. Si falla guardar
el estado de error, se conserva el error original del trabajo en la salida.

### Publicación de las copias SQLite

Cada backup se prepara en `backups/.tmp-telemetry-*`: base SQLite comprobada,
hash SHA-256, tamaño y `manifest.json` leído de nuevo para verificar su contenido.
Se sincronizan ambos archivos antes de publicar. La publicación mueve la carpeta
completa a su nombre definitivo con un único renombrado dentro de `backups/`.
El lock `operations/backup-publication.lock` serializa a los publicadores de
TradingLab; cualquier destino existente, incluso vacío, bloquea la publicación.
El directorio operativo debe seguir bajo control del usuario del servicio: esta
guarda no protege frente a otro programa que modifique rutas sin respetar el lock.

Un fallo previo al renombrado deja únicamente el paquete nuevo temporal; las
copias anteriores permanecen intactas. No se borran esos temporales ni se reintenta
su publicación automáticamente. Si hay contención en el lock de publicación,
se informa como fallo del trabajo que ya había comenzado, no como una omisión
por mantenimiento simultáneo.

En macOS/Linux también se sincronizan las entradas de directorio antes y después
de publicar. Windows no ofrece aquí una sincronización portable del directorio;
se sincronizan los archivos, sin prometer supervivencia ante todo corte eléctrico.
Si falla la sincronización **después** del renombrado, el paquete ya publicado
queda completo, pero el job informa error porque no pudo confirmar durabilidad.
Revise ese paquete antes de reintentar: no se borra ni se considera parcial por
el solo hecho de que el job haya fallado. Una copia verificada no sustituye una
prueba de restauración, que continúa aplazada.

## 7. Manejo de credenciales

El bootstrap genera cinco tokens para API y un token humano. No los imprime como
parte de esta guía ni los copie en comandos, argumentos, terminal compartido,
logs, chat o Git. No use `Get-Content`, `cat`, redirecciones a consola ni capturas
para inspeccionar `.env.central` o `.env.dashboard`.

Para integrar el relay existente, transfiera por un canal manual revisado solo
`CENTRAL_SNAPSHOT_INGEST`, `CENTRAL_LIVE_INGEST` y `CENTRAL_ACTIVITY_INGEST` a
las variables centrales correspondientes de su entorno privado.
Estos nombres son ejemplos: use los nombres `central_token_env` de su topología
real, que pueden ser distintos. Los valores nunca van dentro del JSON público.
No sustituya los tokens locales que ya usan los EAs; esos secretos permanecen en
la configuración privada de los productores. Las credenciales de lectura del
dashboard se configuran por separado en su host. No comparta los archivos `.env`
como medio de transferencia.

La instalación del host no inicia el servicio ni habilita accesos por red. Revise
permisos de archivos localmente sin revelar contenido. `host.json` es el marcador
público final de que el setup terminó; no contiene credenciales.

## 8. Arrancar y comprobar solo la API

Con el data-dir creado y las credenciales configuradas de forma privada, arranque
la API en primer plano desde el checkout:

```sh
uv run --locked --no-sync python scripts/run_remote_host.py \
  --data-dir "$HOME/TradingLabData/central-host-01" \
  --tailscale-host mac.nombre-tailnet.ts.net
```

En Windows reemplace la ruta por la ruta aprobada en ese host. La API escucha
solo en `127.0.0.1:8781`. `--tailscale-host` agrega el FQDN exacto a
`allowed_hosts` y su origen `https://<FQDN>` (puerto 443) a `public_origins`;
no cambia el bind ni acepta comodines. Revise las salidas no
secretas del proceso.
Use el nombre real obtenido en el paso de Tailscale, no el placeholder del ejemplo.
También puede omitir `--tailscale-host` inicialmente para probar solo localhost.
No arranque las dos variantes de API simultáneamente; detenga la anterior con Ctrl+C.

La comprobación local básica es `http://127.0.0.1:8781/health`; devuelve salud
mínima y pública, no filas ni credenciales. El siguiente paso previsto es publicar
la API mediante Tailscale Serve y comprobar HTTPS desde la VPS. Eso requiere la
configuración explícita de Tailscale descrita abajo; no queda habilitado por este
comando.

En Mac, mientras el proceso esté en primer plano, puede evitar la suspensión con:

```sh
caffeinate -i uv run --locked --no-sync python scripts/run_remote_host.py \
  --data-dir "$HOME/TradingLabData/central-host-01" \
  --tailscale-host mac.nombre-tailnet.ts.net
```

Esto solo mantiene despierta la sesión mientras el comando vive. No crea un job
permanente, servicio de arranque o política de energía. La ejecución continua se
planificará por separado.

## 9. Conectividad privada con Tailscale

Instale Tailscale desde los enlaces oficiales:

- [macOS](https://tailscale.com/docs/install/mac/)
- [Linux](https://tailscale.com/docs/install/linux/)
- [Windows](https://tailscale.com/docs/install/windows/)

Inicie sesión desde la app en ambos equipos con la misma tailnet dedicada y
confirme la identidad de cada nodo. Declare primero las etiquetas en la política
de abajo. Después, en Machines de la consola de administración, edite las
etiquetas de la VPS (`tag:tl-vps`) y de la Mac (`tag:tl-api`), sin intercambiarlas
ni asignar ambas al mismo dispositivo. No use claves de autenticación en Git.

La política de acceso mínima propuesta es direccional: `tag:tl-vps` puede abrir
TCP 443 a `tag:tl-api`; no crea una conexión nueva desde el Mac hacia la VPS. Las
respuestas de una conexión permitida son posibles, así que esto no es un diodo.
Tampoco cubre acceso por IP pública o LAN.

Ejemplo de política para una tailnet dedicada (integrar revisando la política
existente, no pegar encima sin análisis):

```json
{
  "tagOwners": {
    "tag:tl-vps": ["autogroup:admin"],
    "tag:tl-api": ["autogroup:admin"]
  },
  "acls": [],
  "grants": [
    {
      "src": ["tag:tl-vps"],
      "dst": ["tag:tl-api"],
      "ip": ["tcp:443"]
    }
  ],
  "ssh": [],
  "tests": [
    {
      "src": "tag:tl-vps",
      "proto": "tcp",
      "accept": ["tag:tl-api:443"],
      "deny": ["tag:tl-api:22", "tag:tl-api:8781"]
    },
    {
      "src": "tag:tl-api",
      "proto": "tcp",
      "deny": [
        "tag:tl-vps:22", "tag:tl-vps:3389",
        "tag:tl-vps:8776", "tag:tl-vps:8777"
      ]
    }
  ]
}
```

Referencias: [sintaxis grants](https://tailscale.com/docs/reference/syntax/grants) y
[archivo de política](https://tailscale.com/docs/reference/syntax/policy-file).
Las reglas son aditivas: en una tailnet existente, revise y retire permisos
`allow-all` o reglas ACL amplias antiguas que invaliden la restricción. Preserve
los accesos administrativos que realmente necesite; no aplique esta política a
ciegas sobre una tailnet compartida. No configure exit nodes, subnet routes,
Tailscale SSH ni Funnel.

### Publicar con Tailscale Serve

En el Mac, antes de cambiar nada, consulte el estado de Serve y confirme que no
reemplazará otro servicio existente. Use el CLI instalado; si no está en `PATH`,
localice el binario de la instalación real (en macOS puede estar en
`/Applications/Tailscale.app/Contents/MacOS/Tailscale`). No asuma esa ruta sin
confirmarla.

En una Mac con esa variante de instalación puede definir un alias de sesión:

```sh
alias tailscale='/Applications/Tailscale.app/Contents/MacOS/Tailscale'
tailscale status
tailscale serve status
```

Active MagicDNS y certificados HTTPS en DNS de la consola de Tailscale. Serve
puede abrir un enlace de consentimiento para habilitar HTTPS. Para obtener solo
el hostname real de la Mac desde el checkout:

```sh
tailscale status --json | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'
```

Ese nombre se usa tanto en `--tailscale-host` de la API como en la URL desde la
VPS. Los nombres de certificados pueden aparecer en registros públicos de
transparencia; elija nombres de equipo sin información sensible.

Solo después de comprobar que el endpoint está libre, sirva HTTPS 443 hacia la API
local:

```sh
tailscale serve --bg --https=443 http://127.0.0.1:8781
```

Consulte `tailscale serve status` para verificar el hostname y backend. El proceso
no debe enlazar la API a `0.0.0.0` ni a una interfaz LAN. Para referencia, consulte
[Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve) y la
[referencia CLI](https://tailscale.com/docs/reference/tailscale-cli/serve).

Desde la VPS valide certificado y salud sin `-k`:

```powershell
curl.exe --fail --max-time 10 https://mac.nombre-tailnet.ts.net/health
```

La respuesta `/health` es pública y mínima. Los proxies de confianza siguen
desactivados; el API acepta el FQDN exacto, no un wildcard. Una falla TLS o Host
se investiga en DNS, Serve y `allowed_hosts`; no se debe relajar la validación.
El arranque manual con `--tailscale-host` permite ese origen HTTPS aunque Serve
entregue HTTP al backend. La configuración es explícita: no se deduce de
`X-Forwarded-*` ni `Forwarded`. Un origen identifica esquema, host y puerto,
como explica la [referencia de FastAPI](https://fastapi.tiangolo.com/tutorial/cors/#origin).
El puerto HTTPS 443 explícito u omitido representa el mismo origen; otros puertos
requieren autorización exacta mediante `--public-origin` en la CLI central.
No se permiten HTTP público, orígenes ajenos, listas, duplicados, `null`, rutas,
credenciales ni valores ambiguos. Loopback sigue admitiendo únicamente su mismo
esquema/host/puerto. Las peticiones sin Origin (relay) no cambian y la autenticación
Bearer sigue siendo obligatoria en rutas protegidas. Esto no habilita CORS entre sitios.

La política se probó con ASGI local; Swagger Try it out y el recorrido HTTPS real
con Serve siguen pendientes de validación manual. Para arranque programado,
indique `--tailscale-host` al preparar la tarea como se explica en la sección 6:
no hereda los flags de otra ejecución manual ni actualiza tareas ya instaladas.
No relaje Host/Origin para compensar una tarea con argumentos antiguos.

### Verificar dirección de acceso

Compruebe en la consola de administración que los tests de política aceptan desde
la VPS solo `tag:tl-api:443` y niegan API `22/8781`. Desde el Mac deben denegarse
los puertos VPS `22`, `3389`, `8776` y `8777` según la política. Una prueba TCP
desde el Mac solo tiene sentido para puertos que realmente estén escuchando y
cuya prueba haya sido autorizada. `ping` no demuestra acceso TCP.

No cambie firewall de la VPS ni RDP. Esta regla no protege otros caminos de red ni
IPs públicas; cualquier exposición fuera de la tailnet debe permanecer cerrada y
ser revisada por separado.

## 10. Relay, dashboard y datos existentes

**No corte el relay actual ni cambie su configuración como parte del bootstrap.**
Cada target de la outbox está ligado a la identidad y al destino con que se creó.
Cambiarlo al FQDN nuevo requiere que la cola actual esté drenada, un corte
aprobado y, si la identidad/destino lo requiere, una outbox nueva preparada. No
borre ni sustituya la outbox antigua para desbloquear la operación.

El dashboard puede seguir en la VPS. El cliente actual usa loopback y aún no
admite configurar una URL base de API remota; hace falta un incremento posterior
(por ejemplo, un proxy/túnel local revisado) antes de afirmar que el dashboard
consume la API del Mac. En este incremento priorice la API y SQLite y compruebe su
health desde la VPS; el recorrido remoto completo API/relay/dashboard corresponde
a una validación posterior.

La base del host comienza vacía. No reinicia cursores MT5, no migra datos y
no generan un backfill histórico automáticamente. Mantenga las bases, cursores,
identidades y outbox actuales intactos hasta que haya un plan de traslado y
reconciliación aprobado.

## Referencias oficiales

- Instalación de uv: [guía](https://docs.astral.sh/uv/getting-started/installation/)
  y [referencia del instalador](https://docs.astral.sh/uv/reference/installer/).
- Tailscale: [Serve](https://tailscale.com/docs/features/tailscale-serve),
  [CLI Serve](https://tailscale.com/docs/reference/tailscale-cli/serve),
  [grants](https://tailscale.com/docs/reference/syntax/grants) y
  [formato de política](https://tailscale.com/docs/reference/syntax/policy-file).
- Instaladores Tailscale oficiales por plataforma enlazados en la sección 9.

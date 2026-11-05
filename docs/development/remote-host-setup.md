# Preparar un host remoto para la API central

**Alcance:** bootstrap local de API central y SQLite en Mac, Linux o Windows.
Este procedimiento no despliega el dashboard en Mac, no cambia MT5 y no configura
automáticamente firewall, servicios, Tailscale ni suspensión del sistema.

## Estado y límites

El piloto actual validado es local: los collectors envían al relay durable y este
reenvía a FastAPI y SQLite. El setup del host remoto prepara una API central en
loopback y una base nueva. No demuestra todavía un piloto extremo a extremo por
Tailscale ni una migración de datos operativos.

La estructura unificada y el esquema global 6 se describen en la guía de
[SQLite de la API central](central-sqlite.md) y siguen el
[ADR-0020](../adr/0020-single-central-sqlite-database.md), que reemplaza la
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

El resultado previsto es:

- `central.sqlite3`, esquema central global, SQLite `user_version=6`, con ambos
  flujos de captura y una sola identidad compartida de cuenta/fuentes;
- `.env.central`, con cinco credenciales de API generadas;
- `.env.dashboard`, con un token humano generado;
- `host.json`, metadatos públicos escritos al final como señal de finalización.

Los endpoints `/v1/telemetry` y `/v2/telemetry` conservan sus contratos actuales;
el número 6 solo identifica el esquema completo del archivo SQLite. El creador
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

`v2_live_source_id` es una fuente distinta, reservada para un productor v2 live;
no la confunda con la fuente v1 ni reutilice `v2_activity_source_id`. No cambie
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

## 7. Manejo de credenciales

El bootstrap genera cinco tokens para API y un token humano. No los imprime como
parte de esta guía ni los copie en comandos, argumentos, terminal compartido,
logs, chat o Git. No use `Get-Content`, `cat`, redirecciones a consola ni capturas
para inspeccionar `.env.central` o `.env.dashboard`.

Para integrar el relay existente, transfiera por un canal manual revisado solo
`CENTRAL_V1_INGEST` y `CENTRAL_V2_ACTIVITY` a las variables correspondientes
`RELAY_LIVE_CENTRAL_TOKEN` y `RELAY_ACTIVITY_CENTRAL_TOKEN` de su entorno privado.
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
solo en `127.0.0.1:8781`. `--tailscale-host` agrega únicamente el FQDN exacto a
`allowed_hosts`; no cambia el bind ni acepta comodines. Revise las salidas no
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
Los POST desde navegador a través de TLS terminado en Serve pueden rechazarse
por Origin: este incremento no habilita confianza en `X-Forwarded-*`. Use los
clientes de servicio sin Origin para ingesta y conserve las protecciones; no
dé por validado Swagger Try it out remoto como parte de esta preparación.

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

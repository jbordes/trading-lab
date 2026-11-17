# Instalación piloto local (stable)

Esta guía prepara la arquitectura `local-dual-v1`: dos receptores locales, una base para estado de cuenta, otra para actividad y el dashboard. Es una instalación piloto supervisada, no una declaración de disponibilidad de producción.

## Requisitos y límites

- Python 3.14 y `uv` disponible en `PATH`. El bootstrap instala las dependencias bloqueadas con `uv sync --locked --no-dev`.
- El terminal MetaTrader 5 es Windows. Los servicios del piloto son Python y se ejecutan en primer plano; `--start` no instala un servicio ni configura inicio al arrancar el sistema.
- La instalación crea un directorio absoluto nuevo, fuera del checkout. Crea bases nuevas y credenciales privadas; no migra ni sobrescribe instalaciones existentes.
- El modo predeterminado es `demo`. Una configuración `real` exige además `--allow-real-account`.
- La conexión remota existente por Tailscale se opera por separado y no forma parte de esta instalación local.

## Preparar configuración

Copia `docs/development/installation.example.json` a una ubicación privada fuera de Git y edita la copia. Mantén `login_masked` enmascarado; indica `server`, `currency`, identificadores de cuenta y fuentes distintos, puertos disponibles y el offset UTC del broker que hayas confirmado. Este archivo no contiene credenciales.

Ejemplo de PowerShell desde el checkout:

```powershell
New-Item -ItemType Directory -Force C:\TradingLab-private, C:\TradingLabData | Out-Null
Copy-Item docs/development/installation.example.json C:\TradingLab-private\stable-installation.json
notepad C:\TradingLab-private\stable-installation.json
```

El primer comando crea solo los directorios padre. No crees `C:\TradingLabData\stable`: el instalador requiere que el destino final todavía no exista.

En macOS/Linux, copia el mismo JSON a un directorio privado fuera del repositorio y edítalo con tu editor. Los servicios Python son portables; el EA/terminal MT5 requiere el entorno Windows del operador.

## Vista previa e instalación

Primero ejecuta la vista previa; no modifica el destino ni descarga dependencias:

```powershell
python scripts/bootstrap_installation.py --config C:\TradingLab-private\stable-installation.json --data-dir C:\TradingLabData\stable
```

Revisa la configuración y el destino. Para crear la instalación:

```powershell
python scripts/bootstrap_installation.py --config C:\TradingLab-private\stable-installation.json --data-dir C:\TradingLabData\stable --apply
```

El proceso ejecuta `uv sync --locked --no-dev`, genera las dos SQLite nuevas, los tokens de `.env.local` y `installation.json`. Protege el directorio y sus credenciales para el usuario local. Si falla después de crear archivos, conserva el directorio parcial para revisión; no lo borres como parte de un reintento.

Para iniciar inmediatamente en consola añade `--start` al comando `--apply`. También puedes arrancar después:

```powershell
uv run --no-sync python scripts/run_tradinglab.py --data-dir C:\TradingLabData\stable
```

Comprueba una instalación preparada sin levantar servicios:

```powershell
uv run --no-sync python scripts/run_tradinglab.py --data-dir C:\TradingLabData\stable --dry-run
```

Para REAL, primero cambia `account_mode` a `real` en la copia privada del JSON y revisa la identidad y el destino. El permiso explícito es obligatorio:

```powershell
python scripts/bootstrap_installation.py --config C:\TradingLab-private\stable-installation.json --data-dir C:\TradingLabData\stable-real --allow-real-account --apply
```

El dashboard se sirve en `http://127.0.0.1:8775/dashboard`. El estado de cuenta recibe en `http://127.0.0.1:8776/v1/telemetry` y la actividad en `http://127.0.0.1:8777/v2/telemetry`. Los tokens se generan en `C:\TradingLabData\stable\.env.local`: `TRADINGLAB_TELEMETRY_TOKEN`, `TRADINGLAB_TELEMETRY_LIVE_TOKEN`, `TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN`, `TRADINGLAB_TELEMETRY_READ_TOKEN` y `TRADINGLAB_DASHBOARD_TOKEN`. No copies estos valores a Git, argumentos de comandos, capturas ni registros compartidos.

En MT5, añade manualmente `http://127.0.0.1:8776` y `http://127.0.0.1:8777` a la lista de URL permitidas para WebRequest. Configura el colector de estado con la URL de su receptor, su token y `snapshot_source_id`; configura actividad con su receptor, token y `activity_source_id`. `login_masked` es solo metadato: en cada EA introduce el login completo en `ExpectedDemoLogin` y el servidor completo exacto en `ExpectedDemoServer`. Esos nombres se conservan por compatibilidad. `AllowRealAccount=false` permite solo DEMO; para REAL debe ser `true`, con login y servidor exactos. El colector es de solo lectura. No cambia el terminal del socio, no se instala automáticamente y no modifica autotrading.

Compila manualmente ambos archivos `TradingLabTelemetry.mq5` y `TradingLabActivity.mq5` en MetaEditor, manteniendo `TradingLabAccountGuard.mqh` y los demás headers requeridos junto a los fuentes. El `.mqh` es un header incluido, no un archivo que se compile solo. No mezcles fuentes ni binarios de esta rama con los de la arquitectura remote.

## Validación y alcance

El formato `installation.example.json` y los comandos bootstrap son comunes a stable y remote, pero las instalaciones producidas no son compatibles: sus bases, layout y binarios no se intercambian y no existe migración entre arquitecturas. Las comprobaciones nativas del guard, manuales en el terminal e integración del flujo son pasos pendientes. Esta guía describe el piloto local; no acredita producción ni cubre el despliegue Tailscale remoto.

Decisión relacionada: [ADR-0024: instalaciones paralelas con guarda de cuenta](../adr/0024-dual-installation-account-guard.md).

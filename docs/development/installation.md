# Instalación piloto local (remote)

Para la versión multicuenta, abra [TradingLab SetUp para Windows](tradinglab-setup-multicuenta.md).

Esta guía prepara la arquitectura `central-relay-v1`: API central, relay local con cola durable y dashboard. El terminal MT5 envía al relay local; este reenvía los eventos a la API central. Es un piloto supervisado, no una declaración de disponibilidad de producción.

## Requisitos y límites

- Python 3.14 y `uv` disponible en `PATH`. El bootstrap instala dependencias bloqueadas con `uv sync --locked --no-dev`.
- MT5 y MetaEditor se ejecutan en Windows; los servicios Python son portables. `--start` los mantiene en consola, no instala servicios ni configura inicio al arrancar el sistema.
- La instalación crea un directorio absoluto nuevo, fuera del checkout. Crea una base central y una cola durable nuevas, además de credenciales privadas; no migra ni sobrescribe datos existentes.
- El modo predeterminado es `demo`. Una configuración `real` exige además `--allow-real-account`.
- El despliegue remoto por Tailscale que ya existe se opera por separado. Esta guía cubre la topología local del piloto.

## Preparar configuración

Copia `docs/development/installation.example.json` a una ubicación privada fuera de Git y edita la copia. Mantén `login_masked` enmascarado; configura `server`, `currency`, identificador y tres fuentes diferentes, puertos libres y offset UTC confirmado del broker. No introduzcas credenciales en el JSON.

Ejemplo en PowerShell:

```powershell
New-Item -ItemType Directory -Force C:\TradingLab-private, C:\TradingLabData | Out-Null
Copy-Item docs/development/installation.example.json C:\TradingLab-private\remote-installation.json
notepad C:\TradingLab-private\remote-installation.json
```

El primer comando crea solo los directorios padre. No crees `C:\TradingLabData\remote`: el instalador requiere que el destino final todavía no exista.

En macOS/Linux, copia el JSON a un directorio privado fuera del checkout y edítalo con tu editor. Los servicios Python son portables; el EA y MT5 requieren el entorno Windows del operador.

## Vista previa e instalación

La vista previa no modifica el destino ni descarga dependencias:

```powershell
python scripts/bootstrap_installation.py --config C:\TradingLab-private\remote-installation.json --data-dir C:\TradingLabData\remote
```

Tras revisar configuración y destino, crea la instalación:

```powershell
python scripts/bootstrap_installation.py --config C:\TradingLab-private\remote-installation.json --data-dir C:\TradingLabData\remote --apply
```

El bootstrap sincroniza dependencias bloqueadas y crea `central.sqlite3`, `relay.sqlite3`, `relay.json` y credenciales privadas. `.env.central` contiene secretos de ingestión central; `.env.collectors` contiene `RELAY_LIVE_LOCAL_TOKEN` y `RELAY_ACTIVITY_LOCAL_TOKEN` para los colectores; `.env.dashboard` contiene `TRADINGLAB_DASHBOARD_TOKEN`; `.env.relay` contiene las credenciales de tránsito del relay. No copies esos valores a Git, argumentos, capturas o registros compartidos. Si falla con archivos parciales, consérvalos para revisión y no sobrescribas el destino.

Para iniciar inmediatamente en consola añade `--start` a `--apply`, o ejecuta más tarde:

```powershell
uv run --no-sync python scripts/run_tradinglab.py --data-dir C:\TradingLabData\remote
```

Comprueba una instalación preparada sin levantar servicios:

```powershell
uv run --no-sync python scripts/run_tradinglab.py --data-dir C:\TradingLabData\remote --dry-run
```

Para REAL, cambia `account_mode` a `real` en la copia privada del JSON y revisa la identidad y el destino. El permiso explícito es obligatorio:

```powershell
python scripts/bootstrap_installation.py --config C:\TradingLab-private\remote-installation.json --data-dir C:\TradingLabData\remote-real --allow-real-account --apply
```

El dashboard está en `http://127.0.0.1:8775/dashboard`; el relay local recibe estado de cuenta en `http://127.0.0.1:8776/api/account-state` y actividad en `http://127.0.0.1:8777/api/trading-events`. La API central escucha en el puerto `8782` y expone esas rutas bajo `/api/`.

En MT5, añade manualmente `http://127.0.0.1:8776` y `http://127.0.0.1:8777` a la lista de URL permitidas para WebRequest. Configura estado con URL local, token de estado y `snapshot_source_id`; configura actividad con URL local, token de actividad y `activity_source_id`. `login_masked` es solo metadato: en cada EA introduce el login completo en `ExpectedDemoLogin` y el servidor completo exacto en `ExpectedDemoServer`. Esos nombres se mantienen por compatibilidad con archivos `.set`. `AllowRealAccount=false` acepta solo DEMO; para REAL debe ser `true`, con login y servidor exactos. Los colectores son de solo lectura. No cambies el terminal del socio, no instales nada automáticamente ni alteres autotrading.

Compila manualmente ambos archivos `TradingLabTelemetry.mq5` y `TradingLabActivity.mq5` en MetaEditor, manteniendo `TradingLabAccountGuard.mqh` y los demás headers requeridos junto a los fuentes. El `.mqh` es un header incluido, no un archivo que se compile solo. No mezcles fuentes ni binarios de esta rama con los de la arquitectura stable.

## Validación y alcance

El formato `installation.example.json` y los comandos bootstrap son comunes a stable y remote, pero las instalaciones producidas no son compatibles: sus bases, layout y binarios no se intercambian y no existe migración entre arquitecturas. Las comprobaciones nativas del guard, manuales en MT5 e integración del flujo son pasos pendientes. Este documento no declara producción lista y no sustituye la operación remota existente por Tailscale.

Decisión relacionada: [ADR-0024: instalaciones paralelas con guarda de cuenta](../adr/0024-dual-installation-account-guard.md).

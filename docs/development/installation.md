# Instalación piloto local (stable)

Esta guía prepara `local-dual-v1`: dos receptores locales, una base para estado de cuenta, otra para actividad y el dashboard. Es una instalación piloto supervisada, no una declaración de disponibilidad de producción.

## Asistente para Windows

Abre `Instalar-TradingLab.cmd` desde la raíz del checkout. El formulario usa estos nombres: **MT5 Account Nr.**, **History Date From**, **Telemetry/Activity Port** (estable), **Telemetry/Activity Relay Port** (central), **Dashboard Port**, **API Port** (solo central) y **TradingLab Data File (carpeta)** para el directorio privado que contiene bases y tokens. La fecha se expresa en hora del broker (`YYYY.MM.DD HH:MM:SS`); su UTC offset no es la zona horaria de Windows. No se solicita la contraseña de MT5.

Una configuración nueva usa REAL por defecto; marca **Es Cuenta Demo** para DEMO. Al cargar JSON o continuar una instalación se conserva el modo existente. El resumen confirma el modo antes de instalar. Los collectors siguen teniendo DEMO como valor predeterminado; el preset REAL configura la guarda para la identidad exacta. La CLI bootstrap requiere `--allow-real-account` para REAL.

El JSON editable contiene exactamente estos campos: `login_id` (login completo), `server`, `currency`, `account_mode`, `snapshot_port`, `activity_port`, `dashboard_port`, `central_port`, `broker_utc_offset_minutes` e `history_date`. Su nombre es `<login_id>.json`, por ejemplo `12345678.json`. El login completo se guarda en este JSON por decisión explícita del usuario. No agregues `label`, `account_id`, `source_id` ni `login_masked`: son valores internos. Para una configuración nueva, la etiqueta interna se deriva del login y los IDs son `mt5-{login}-{sha256(server)[:8]}-{state|live|activity}` para evitar colisiones entre brokers. En una instalación existente se conservan sus IDs y su etiqueta heredados.

El asistente busca automáticamente un JSON cuyo nombre base sea numérico en `_storage/installation/` del repositorio o en la carpeta padre, y lo carga solo si encuentra exactamente uno. Si hay cero o varios, usa **Abrir JSON**. También permite **Guardar JSON**; confirma antes de reemplazar un archivo. Guardar no instala dependencias ni crea bases. La instalación usa los valores revisados sin modificar silenciosamente el JSON original.

La carpeta de datos contiene SQLite y tokens privados; debe estar fuera del checkout. Para continuar una instalación existente, el asistente conserva bases, tokens e IDs y valida los valores públicos del runtime. No reemplaza secretos por valores del JSON. Si el destino es una carpeta parcial sin `installation.json`, requiere diagnóstico; no borres la carpeta para reintentar.

El asistente encuentra `uv` o descarga su [instalador oficial](https://docs.astral.sh/uv/getting-started/installation/), prepara Python 3.14 y ejecuta el bootstrap compartido. La configuración aparece en una ventana y la instalación en consola. Al finalizar ofrece iniciar servicios; no instala un servicio de Windows. Cancelar el formulario no descarga dependencias ni crea bases. Ante un fallo, conserva archivos parciales para revisión. La validación visual y una instalación manual real desde Windows siguen pendientes.

## Requisitos y límites

### Iniciar sin repetir la instalación

Abrir `Iniciar-TradingLab.cmd` con doble clic y seleccionar el archivo interno
`installation.json` de la carpeta de datos deseada (no el JSON editable de cuenta).
Se usa el entorno Python ya preparado del checkout y las bases y tokens existentes.
No instala dependencias, genera presets ni modifica la configuración.
Mantener la consola abierta; Ctrl+C detiene los servicios iniciados por esa ejecución.
Si los puertos están ocupados, informa el problema y no detiene otros procesos.
La carpeta debe corresponder a la misma arquitectura del checkout.
Si falta el entorno Python, continuar la instalación desde el asistente.

También admite inicio directo sin selector desde PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start_windows.ps1 -DataDir C:\TradingLabData\installation
```

La fecha editable `history_date` se expresa en hora del broker. El generador
escribe `HistoryStartServerTime` en el preset como segundos desde 1970, que es
la representación del parámetro datetime de MT5, sin convertir la hora del broker
a la hora local. Una prueba dirigida verifica JSON → instalación → preset y
recupera del número la misma fecha ingresada. La carga en MT5 sigue requiriendo
validación manual; no se corrigen a mano los artefactos de esa prueba.

- Python 3.14 y `uv`; el bootstrap ejecuta `uv sync --locked --no-dev`.
- MT5 es Windows. Los servicios Python se ejecutan en primer plano; `--start` no configura inicio del sistema.
- El instalador crea un directorio absoluto nuevo fuera del checkout, con bases y credenciales nuevas; no migra ni sobrescribe instalaciones existentes.
- Una configuración REAL requiere `--allow-real-account` en CLI.
- La conexión remota existente por Tailscale se opera por separado.

## Configuración e instalación por CLI

El ejemplo editable usa el contrato de diez campos descrito arriba. Guárdalo fuera de Git con el nombre del login, por ejemplo `C:\TradingLab-private\12345678.json`. Los tokens se generan únicamente como parte de los presets privados o mediante configuración segura por entorno; nunca se guardan en el JSON editable.

```powershell
python scripts/bootstrap_installation.py --config C:\TradingLab-private\12345678.json --data-dir C:\TradingLabData\stable
python scripts/bootstrap_installation.py --config C:\TradingLab-private\12345678.json --data-dir C:\TradingLabData\stable --apply
```

La primera orden es vista previa; revisa identidad y destino. Para REAL, cambia `account_mode` a `real` en el JSON y usa el permiso explícito:

```powershell
python scripts/bootstrap_installation.py --config C:\TradingLab-private\12345678.json --data-dir C:\TradingLabData\stable-real --allow-real-account --apply
```

Para arrancar la instalación o comprobarla sin levantar servicios:

```powershell
uv run --no-sync python scripts/run_tradinglab.py --data-dir C:\TradingLabData\stable
uv run --no-sync python scripts/run_tradinglab.py --data-dir C:\TradingLabData\stable --dry-run
```

El runtime stable expone dashboard en `http://127.0.0.1:8775/dashboard`, estado de cuenta en `http://127.0.0.1:8776/v1/telemetry` y actividad en `http://127.0.0.1:8777/v2/telemetry`. Los tokens viven en `.env.local`; no los copies a Git, argumentos, capturas ni registros compartidos. En MT5 permite manualmente ambas URLs en WebRequest y carga los presets generados desde **Parámetros de entrada → Cargar**. El login completo y la identidad autorizada se configuran en los presets protegidos, nunca se escriben en registros compartidos. Los collectors son de solo lectura y no modifican autotrading.

Compila manualmente `TradingLabTelemetry.mq5` y `TradingLabActivity.mq5` en MetaEditor, con sus headers junto a los fuentes. No mezcles fuentes ni binarios con la arquitectura remote.

Los presets contienen tokens de acceso: no los distribuyas. El usuario confirmó la instalación completa en la cuenta demo, la carga de ambos presets y la recepción persistente de estado y actividad el 2026-11-17. Los collectors y el test nativo de la guarda compilaron sin errores ni advertencias; la ejecución de ese test y la prueba en cuenta real u otro servidor siguen pendientes. Se observaron reintentos y mensajes «HTTP 1001» transitorios; la captura posterior se confirmó en SQLite, pero su diagnóstico detallado sigue pendiente.

## Paquete distribuible

`scripts/build_installation_package.py` genera un ZIP de la arquitectura estable con código, dependencias bloqueadas, instalador e iniciador Windows, un ejemplo demo, los dos `.ex5`, una guía breve y un manifiesto SHA-256. Comprueba que los fuentes y headers usados para compilar coincidan con los del checkout. No incluye bases, tokens, presets privados ni el entorno Python local. Requiere `--output`, `--compiled-dir` y `--example`; no sobrescribe un ZIP existente. Los binarios y el ZIP se conservan fuera de Git bajo `_storage/`.

La versión del instalador para API y bases externas queda pendiente de adaptación y validación; este cambio se publica únicamente contra `main` para el flujo estable local.

Esta guía describe el piloto local. Las instalaciones stable y remote no comparten bases, layout ni binarios y no tienen migración definida.

Decisión relacionada: [ADR-0024: instalaciones paralelas con guarda de cuenta](../adr/0024-dual-installation-account-guard.md).

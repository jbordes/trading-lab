# Mantenimiento diario automático: Windows, Linux y macOS

## Para qué sirve y dónde corre

Se instala **en el equipo que aloja el archivo SQLite**, no necesariamente en
la VPS de MT5. Si movemos API y base a una Mac o Linux, el mantenimiento también
se configura allí. No se abre SQLite por una unidad de red ni desde la VPS.

```text
VPS: MT5 → collectors → relay → HTTPS privado → host de datos: API → SQLite
                                                               ↑
                                    scheduler → mantenimiento local
Navegador → dashboard → API
```

No requiere conexiones desde el host de datos hacia la VPS. Tampoco requiere
que API, dashboard o MT5 estén ejecutándose: procesa capturas ya guardadas.
No captura datos durante una desconexión ni reemplaza la recuperación de Activity.

Cada ejecución:

1. Adquiere el lock de mantenimiento y crea una copia consistente y verificada.
2. Consolida los días cerrados, usando la última observación real de balance,
   equity y PnL flotante del día del broker, más los extremos observados.
3. Compacta contenidos antiguos elegibles, conservando siete fechas recientes,
   cierres diarios, evidencias y las identidades necesarias para deduplicar.
4. Publica el resultado en `operations/maintenance-status.json`.

Si la copia falla, no consolida ni compacta. No altera órdenes, posiciones, EAs,
tokens o cursores de Activity; no reconstruye equity anterior a las capturas y
no borra automáticamente las copias. Los límites y casos de reloj ausente o
atrasado se explican en [histórico diario](daily-account-history-storage.md).

## Preparación del ecosistema

Antes de programar:

1. Preparar el checkout y `.venv` en el host de datos con el
   [bootstrap remoto](remote-host-setup.md). Crear una base nueva de esquema 8
   o realizar la migración supervisada; el instalador no crea ni migra bases.
2. Registrar la cuenta y sus fuentes en esa base. La cuenta de mantenimiento
   es el identificador interno de TradingLab, no el login del broker ni un magic.
3. Configurar la API local y, si está en otro equipo, el enlace privado de
   Tailscale según ese manual. La VPS envía a la API; no al archivo SQLite.
4. Configurar relay y collectors con el
   [manual MT5](mt5-collector-operations.md) y comprobar la recepción.
   Telemetry debe publicar `server_time_msc` (desde 0.3.1); sin esa referencia
   el trabajo diario se difiere en lugar de inventar fechas.
5. Probar la API y el dashboard con la
   [guía de arranque conjunto](central-api-dashboard.md).
6. Revisar la programación siguiente y aplicarla **solo con autorización**.

El instalador solo programa mantenimiento; no instala Python, cron, Tailscale,
API, relay ni collectors. No lee `.env` ni necesita tokens. La base debe ser
local y el usuario debe poder escribir en su directorio, `backups/` y `operations/`.

## Comando común: primero vista previa

Desde el checkout del host de datos, con `.venv` preparada:

```text
uv run python scripts/configure_telemetry_maintenance.py --data-dir RUTA_DATOS --database central.sqlite3 --account-id CUENTA --time 03:30
```

Reemplazar `RUTA_DATOS` y `CUENTA`. Si la base tiene otro nombre, usarlo en
`--database`; por ejemplo `central-unified-pilot.sqlite3` en el piloto local.
Las rutas con espacios deben ir entre comillas en la terminal.

La vista previa valida el esquema, la cuenta y los archivos necesarios, pero
no consulta ni modifica el scheduler y no ejecuta mantenimiento. No necesita
`host.json` ni archivos de secretos. El horario es **local del sistema operativo**;
la selección de días cerrados utiliza el reloj del broker, con cinco minutos de
margen. Elegir un horario posterior al cierre esperado del broker.

La ejecución programada usa la ruta absoluta del Python de `.venv`, no `uv`,
PATH ni activación de entorno. Si se mueve el checkout o se cambia de host,
revisar/desactivar la tarea anterior y generar una nueva con las rutas actuales.

### Windows

```powershell
uv run python scripts/configure_telemetry_maintenance.py --data-dir "C:\TradingLabData\central-host-01" --database central.sqlite3 --account-id CUENTA --time 03:30
```

Después de revisar, el mismo comando con `--apply` registra **solo**
`TradingLab Telemetry Maintenance`, con privilegios ordinarios. No usa el
instalador combinado `configure_telemetry_windows_tasks.py`, que también
registra el arranque de la API.

Requiere una sesión de Windows iniciada, que puede estar bloqueada o
desconectada de RDP, pero no cerrada. No almacena contraseña ni configura un
servicio de sistema. El primer disparo se programa a la siguiente hora futura.
`StartWhenAvailable` permite atender un disparo perdido cuando el scheduler
pueda hacerlo. No hay reintentos por fallo y se ignoran ejecuciones solapadas.

### Linux: cron del usuario

```sh
uv run python scripts/configure_telemetry_maintenance.py --data-dir "$HOME/TradingLabData/central-host-01" --database central.sqlite3 --account-id CUENTA --time 03:30
```

Revisar y repetir con `--apply`. Requiere `crontab` instalado, servicio cron
activo y permiso del usuario para usarlo; varían según la distribución.
No usar `sudo` para instalar la tarea de otro usuario accidentalmente.

Se conserva el resto del crontab y se añade un bloque identificado por base.
Si ya coincide, no cambia nada; si difiere, se rechaza para revisión manual.
Las rutas con espacios o comillas se escapan; las que contienen `%` o barra
inversa se rechazan por las reglas particulares de cron. La salida queda bajo
el mecanismo de correo/logs de cron del host; no se presupone correo configurado.
El estado de producto sigue en `operations/maintenance-status.json`.

No editar el mismo crontab desde otro proceso durante la instalación: se vuelve
a comprobar justo antes de escribir, pero crontab no ofrece compare-and-swap.
No se cambian `MAILTO`, `SHELL`, `TZ` ni otras variables globales del crontab.
Revisar especialmente una `TZ`/`CRON_TZ` preexistente, que puede alterar el horario
según la implementación de cron.

### macOS: launchd recomendado, cron opcional

```sh
uv run python scripts/configure_telemetry_maintenance.py --data-dir "$HOME/TradingLabData/central-host-01" --database central.sqlite3 --account-id CUENTA --time 03:30
```

Por defecto genera un LaunchAgent del usuario. Tras revisar, repetir con
`--apply`: escribe un plist `org.tradinglab.maintenance.<id>.plist` en
`~/Library/LaunchAgents/` y lo registra con `launchctl bootstrap` en la sesión
gráfica actual. No se ejecuta al registrarlo y no se configura `KeepAlive`.
Requiere sesión del usuario iniciada; no es un LaunchDaemon de sistema.

También puede elegirse cron en Mac añadiendo `--scheduler cron` tanto en vista
previa como al aplicar. **No instalar ambos para la misma base.**
Apple mantiene cron pero recomienda launchd para tareas temporizadas; launchd
puede atender el disparo tras salir del reposo.
[Referencia oficial de Apple](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html).
Las reglas especiales de `%` y entorno de cron se describen en
[crontab(5)](https://man7.org/linux/man-pages/man5/crontab.5.html).

## Equipo apagado, reposo y cambio de día

El scheduler no enciende equipos ni elimina la necesidad de disponibilidad.
Cron pierde un disparo si el host está apagado o dormido; vuelve a intentarlo
en el próximo horario diario. En un día afectado por cambio de hora puede
omitir o repetir un disparo, según el scheduler. El job es idempotente y usa un
lock, pero eso no garantiza una ejecución diaria si el host no está disponible.

La próxima ejecución procesa días pendientes que tengan evidencia guardada,
dentro del presupuesto. Si no hay reloj reciente del broker, solo procesa hasta
la frontera observada y avisa; no extrapola el tiempo del broker desde el host.
Un resultado parcial no dispara bucles automáticos ni implica pérdida de datos.

## Comprobación, diagnóstico y desactivación

Primero revisar la tarea registrada:

- Windows: Programador de tareas → `TradingLab Telemetry Maintenance`; comprobar
  acción, próxima ejecución y último resultado. Un código 3 indica parcial/diferido.
- Linux o Mac con cron: `crontab -l`; localizar el bloque `org.tradinglab.maintenance`.
- Mac con launchd: localizar el plist en `~/Library/LaunchAgents/` y consultar
  `launchctl print gui/ID_USUARIO/ETIQUETA`, con el UID de `id -u` y `Label` del plist.

Después de la primera ejecución comprobar `operations/maintenance-status.json`,
su fecha y el paquete nuevo de `backups/`. Estados: `succeeded`, `partial`,
`deferred`, `failed`; código 2 significa que otro job mantiene el lock. Un error
antes de adquirir el lock puede no actualizar el estado: revisar también el
resultado del scheduler y no confiar únicamente en un archivo antiguo.

Para validar el plan de datos sin modificarlo:

```text
uv run python scripts/run_telemetry_maintenance.py --storage-root RUTA_DATOS --database central.sqlite3 --daily-account-id CUENTA
```

Añadir `--apply` aquí **ejecuta mantenimiento de verdad**, a diferencia de
`--apply` en el instalador, que solo registra la tarea. No confundir ambos comandos.

Para desactivar o cambiar una programación, hacerlo primero en el scheduler:
deshabilitar la tarea Windows; en cron retirar solo las líneas del bloque de
TradingLab con `crontab -e` (nunca `crontab -r`); en launchd hacer `launchctl bootout`
de la etiqueta y conservar/mover el plist fuera de `LaunchAgents` si no debe volver
a cargarse al iniciar sesión. No borrar bases ni backups para desinstalar tareas.
El instalador no sobrescribe tareas Windows/plists existentes. Si falla el alta
launchd, conserva el plist para diagnóstico y no lo reemplaza silenciosamente.

En este incremento solo se desarrolló y verificó la programación con pruebas
aisladas. **No se instalaron tareas en la VPS**. La instalación real en Windows,
Linux y Mac y su primer cierre diario quedan como validaciones operativas.

### Pendiente importante al instalar la base de prueba

Acuerdo del 2026-11-09: los ensayos reales se harán **en el host donde se
instale la base de prueba**, no ahora en la VPS. No es necesario desplegar en
los tres sistemas antes de iniciar el piloto: se valida el sistema elegido;
si después se cambia de sistema, se repite el ensayo del scheduler correspondiente.
No declarar completa la instalación del host de prueba hasta verificar:

- [ ] Vista previa con base, cuenta, rutas y horario reales del host elegido.
- [ ] Instalación autorizada de una única tarea, sin duplicados ni otras tareas modificadas.
- [ ] Una ejecución automática real y su resultado en el scheduler y el archivo de estado.
- [ ] Copia consistente verificada anterior a cualquier consolidación/compactación.
- [ ] Primer cierre diario con datos observados y visualización correcta en la API/dashboard.
- [ ] Comportamiento tras reinicio o reposo, permisos y sesión del usuario documentados.

El primer cierre requiere capturas con hora del broker y un día ya cerrado;
si la base comienza vacía, se valida después de reunir esa evidencia. Un
resultado parcial o diferido se revisa, no se marca como ensayo completo.

Validación de desarrollo del 2026-11-09: catorce pruebas nuevas del instalador
y siete del generador Windows aprobaron, junto con `scripts/check.py fast`.
La vista previa sobre la base del piloto aceptó su nombre personalizado y cuenta
sin requerir secretos, registrar tareas ni ejecutar mantenimiento. Se comprobó
también salida UTF-8 en Windows. Estos resultados no sustituyen un ensayo real
del scheduler en cada sistema operativo.

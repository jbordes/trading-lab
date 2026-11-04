# Probar dashboard, API central y relay juntos

Estado: integración local operativa y validada el 5 de noviembre de 2026. El
dashboard se ha observado durante el piloto; no se afirma una batería exhaustiva
de pruebas UI. No está desplegada en Mac ni producción y no sustituye EAs de trading.

```text
EAs -> relay 8776/8777 -> FastAPI 8781 -> SQLite v1 + SQLite v2/esquema 5
                        ^
                        |
                 dashboard 8775 -> navegador
```

El dashboard solo presenta `CENTRAL_V1_READ` y `CENTRAL_V2_READ` a la API.
El token humano `TRADINGLAB_DASHBOARD_TOKEN` es distinto de ambos. El diagnóstico
de captura usa `/v1/health`, autenticado con lectura v1 y sin payloads; `/health`
continúa público y mínimo. Los receptores legacy siguen en el repo solo para
compatibilidad y, si se inician, requieren puertos separados.

## Preparación

En cada consola, usar este checkout:

```powershell
cd 'C:\TradingLab 2.0\.tmp-fastapi-central-api'
```

Una sola vez ejecutar `py -m uv sync --locked`. Preparar `.env.central` según
[la operación de FastAPI](central-api-operation.md). Opcionalmente crear
`.env.dashboard` con una sola asignación privada: `TRADINGLAB_DASHBOARD_TOKEN=valor`.
Si no se usa ese archivo, el token humano se lee del entorno o se solicita oculto.
El entorno prevalece sobre los archivos. No usar el `.env.local` multivariable
como `.env.dashboard`: este último admite únicamente el token humano.

Las bases deben existir, con cuenta/fuentes registradas y v2 en esquema 5. El
arranque no crea ni migra datos. Si hay receptores legacy ejecutándose en esos
puertos, detenerlos antes de iniciar relay y FastAPI. Para pruebas destructivas usar copias
consistentes aisladas; no copiar archivos SQLite activos con una copia simple.

## Consola 1: API

Ejemplo con las rutas e identidades del piloto Juampi:

```powershell
.\.venv\Scripts\python.exe scripts/central_api.py --v1-db 'C:\TradingLab 2.0\.tmp-session-main\_storage\piloto.sqlite3' --v2-db 'C:\TradingLab 2.0\.tmp-session-main\_storage\piloto-v2.sqlite3' --source-id juampi-demo-01 --account-id cuenta-demo-juampi --secrets-file .env.central --port 8781
```

## Consola 2: dashboard

```powershell
.\.venv\Scripts\python.exe scripts/live_dashboard.py --central-api-port 8781 --telemetry-source juampi-demo-01 --history-v2-source juampi-demo-activity-v2 --secrets-file .env.central --dashboard-secrets-file .env.dashboard --port 8775 --broker-utc-offset-minutes 120
```

Si no se creó `.env.dashboard`, omitir únicamente
`--dashboard-secrets-file .env.dashboard`. El offset 120 es la referencia del
piloto, no una detección automática; verificarlo si cambia el horario del broker.

## Consola 3: relay

Con cola y topología ya preparadas según [la guía del relay](durable-telemetry-relay.md):

```powershell
.\.venv\Scripts\python.exe scripts/telemetry_relay.py --queue 'C:\TradingLab 2.0\.tmp-fastapi-central-api\_storage\relay-api-pilot.sqlite3' --config _storage/relay-pilot.json --secrets-file .env.relay --port 8776 --port 8777
```

La topología debe apuntar a `http://127.0.0.1:8781/v1/telemetry` y `/v2/telemetry`,
con las identidades de las bases. El token central v1 coincide con
`CENTRAL_V1_INGEST` y el de actividad con `CENTRAL_V2_ACTIVITY`. Cambiar targets
de una outbox operativa requiere un corte planificado.

Este comando conserva las URLs del piloto: Telemetry envía a
`http://127.0.0.1:8776/v1/telemetry` y Activity a
`http://127.0.0.1:8777/v2/telemetry`, con sus tokens locales actuales. No hay que
cambiar los EAs ni sus permisos WebRequest si ya utilizan esas URLs. Detener
primero cualquier receptor legacy que aún ocupe esos puertos. El relay abre dos
listeners en un proceso, con una cola y un worker. Si no puede abrir cualquiera
de los puertos, falla sin aceptar tráfico por el otro. Ambos listeners admiten
las rutas v1/v2; los permisos siguen determinados por fuente y credencial.

## Chequeos manuales

- `http://127.0.0.1:8781/docs`: lecturas autenticadas y autorización por rol.
- `http://127.0.0.1:8775/dashboard`: login humano y secciones Resumen, Trading,
  Performance financiera, Ejecución y Actividad.
- `http://127.0.0.1:8776/health` o `http://127.0.0.1:8777/health`: la misma cola
  y confirmación central.
- Con captura activa, detener solo la API: las lecturas se degradan y el relay
  conserva pendientes. Reiniciar API: cola drenada y lecturas recuperadas sin
  duplicar operaciones. Un ACK nunca rejuvenece capturas antiguas.
- Reiniciar solo el dashboard: no debe detener captura ni persistencia; las
  sesiones humanas anteriores quedan revocadas.

Detener cada consola con Ctrl+C. No duplicar puertos ni exponer servicios fuera
de loopback. No versionar secretos; mantener sus archivos con permisos privados.

## Alcance remoto pendiente

El despliegue privado en Mac, TLS/Tailscale y la conexión de cuentas reales no
están activados; requieren su propio plan y aprobación operativa. Para la
gestión futura de credenciales y permisos, consultar [el plan de gestión
centralizada](credential-management-plan.md).

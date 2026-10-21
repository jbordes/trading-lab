# Arranque y recuperación de la telemetría MT5

El EA `TradingLabTelemetry` captura datos. El **receptor** es el proceso Python
que acepta esos datos y confirma cada entrega. El **dashboard** consulta al
receptor y muestra la última muestra. Tener MT5 abierto no arranca los otros dos.

## Configuración del piloto Juampi

La bitácora del [19 de octubre](../sessions/2026-10-19.md) registra:

| Componente | Configuración |
| --- | --- |
| EA, `IngestUrl` | `http://127.0.0.1:8776/v1/telemetry` |
| EA, `SourceId` | `juampi-demo-01` |
| Receptor | `127.0.0.1:8776` |
| Dashboard | `http://127.0.0.1:8775/dashboard` |

`8766` y `8765` son los valores genéricos de los scripts individuales, no los
puertos de este piloto. No cambiar el EA para adaptarlo a esos ejemplos.

## Arranque diario

Desde una consola PowerShell en la raíz del checkout aprobado:

```powershell
uv sync --locked
uv run python scripts/start_telemetry.py --source-id juampi-demo-01
```

El comando pide el mismo token configurado en el EA mediante entrada oculta.
Introducirlo únicamente en esa consola local, nunca en chats, comandos,
documentación ni Git. Si ya existe `TRADINGLAB_TELEMETRY_TOKEN` en el entorno,
se utiliza sin mostrarlo. No se leen presets, credenciales de broker ni `.env`.
El token se conserva solo en la memoria y el entorno de los procesos.
Si no se dispone del token, el operador debe configurar localmente un nuevo
valor coincidente en el EA y en el arranque; el comando no cambia MT5.

También se puede usar el intérprete ya preparado, cuando uv no esté en PATH:

```powershell
.\.venv\Scripts\python.exe scripts/start_telemetry.py --source-id juampi-demo-01
```

Mantener la consola abierta. El comando arranca ambos servicios separados,
comprueba salud y HTTP/1.1 en el receptor antes de lanzar el dashboard y vigila
que ninguno termine. Si uno termina, cierra los hijos de esta ejecución y
sale con error. Un segundo arranque con puertos ocupados falla sin detener
ni adoptar procesos existentes. Ctrl+C detiene ambos; no detiene el EA.
Con el comando mostrado, el almacenamiento del receptor es volátil: al detenerlo
se pierde su buffer. Hay un modo SQLite opcional con `--sqlite-db` para una base
preexistente bajo `_storage/` y una fuente registrada. La base no se crea al
arrancar. Hay un comando de primera provisión con vista previa:

```powershell
uv run python scripts/provision_telemetry_db.py --filename piloto.sqlite3 --account-id cuenta-demo-interna --label "Demo de pruebas" --server SERVIDOR-DEMO-VERIFICADO --currency USD --source-id juampi-demo-01
```

El operador debe verificar en MT5 la cuenta demo activa, el servidor y la moneda;
`SERVIDOR-DEMO-VERIFICADO` es solo un marcador de ejemplo. Después de revisar la
vista previa, repetir exactamente el comando con `--apply` para crear una base
nueva bajo `_storage/`. Nunca pasar el login completo ni el token como argumentos.
Una base ya existente no se modifica. La frecuencia de backup y la retención aún
deben acordarse antes de operar el receptor SQLite continuamente.
El supervisor transmite la ruta solo al receptor y mantiene las mismas
comprobaciones de arranque y limpieza. No habilitar este modo para una terminal
real hasta completar ese paso operativo.

## Copia local de la base SQLite

Con la base ya creada, este comando solo muestra qué archivo se copiaría:

```powershell
uv run python scripts/backup_telemetry_db.py --filename piloto.sqlite3
```

Agregar `--apply` crea una carpeta nueva bajo `_storage/backups/` con
`data.sqlite3` y `manifest.json` (tamaño, fecha y SHA-256). El comando usa la
copia online de SQLite, comprueba la integridad de la copia y permite que el
receptor mantenga abierta la base. No reemplaza ni elimina copias anteriores.
Una falla puede dejar una carpeta `.tmp-telemetry-*` para inspección manual.

La [política del piloto](../adr/0008-pilot-telemetry-retention.md) conserva todos
los mensajes y copias sin borrado automático. Exige una copia antes de cambiar la
base y al menos una por día con captura, más un registro diario del tamaño de la
base, las copias, el espacio libre y la verificación. Tras una semana completa con
operaciones reales se revisará con el socio. Si falta espacio, detener la captura
y decidir cómo ampliar o exportar; no borrar para liberar espacio sin aprobación.

Esta copia está en la misma máquina: sirve para errores locales, pero no protege
contra pérdida de la VPS. El [ADR-0009](../adr/0009-defer-external-telemetry-backup.md)
acepta ese riesgo únicamente para el piloto demo descartable. Antes de producción
se exigirán un destino externo controlado, una prueba de restauración y objetivos
de pérdida y recuperación. Google Drive, si se usa como transporte, no se
convierte en fuente de verdad.

## Inspección segura de la base

El inventario de cobertura es de solo lectura y no imprime cuentas, tickets,
comentarios ni payloads. Resume fuentes, sesiones, tipos de mensaje, periodo,
estado del último snapshot, deals históricos únicos y Magic Numbers observados:

```powershell
uv run python scripts/inspect_telemetry_db.py --filename piloto.sqlite3
```

La base debe existir bajo `_storage/`. El comando abre SQLite en modo `ro`, activa
`query_only`, valida la versión y puede ejecutarse mientras el receptor continúa
capturando. `--verify` agrega `quick_check` y verificación de relaciones; usarlo
en controles puntuales porque recorre más información y puede ser costoso cuando
la base crezca.

Vista previa sin token, red ni procesos nuevos:

```powershell
uv run python scripts/start_telemetry.py --source-id juampi-demo-01 --dry-run
```

No se instala un servicio ni una tarea al iniciar Windows. Tras reiniciar la
máquina o cerrar la consola, repetir el arranque. Eliminar la dependencia del
supervisor temporal no equivale a garantizar disponibilidad permanente.

## Verificación después del arranque

1. Abrir el dashboard y comprobar `connected` y la fuente `juampi-demo-01`.
2. Esperar al menos dos minutos: el EA puede tener un reintento pendiente de
   hasta 60 segundos y después necesita drenar la cola.
3. Consultar dos veces, separadas por unos 15 segundos:

   ```powershell
   curl.exe --noproxy "*" -i http://127.0.0.1:8776/health
   ```

   La respuesta debe comenzar con `HTTP/1.1 200`. `accepted` debe avanzar.
   Estos contadores son globales del receptor desde su arranque.
4. Confirmar que la muestra del dashboard se renueva y que dejan de aparecer
   nuevos `queue_full` en MT5. No basta con ver una página abierta o `ready`.

## Diagnóstico

| Síntoma | Acción |
| --- | --- |
| Conexión rechazada en 8776 | Arrancar el conjunto; comprobar si su consola terminó con error. |
| Puerto ocupado | Identificar el proceso que lo usa; no matarlo a ciegas ni arrancar otro receptor. |
| HTTP 401 en MT5 | El token del EA y el del receptor no coinciden. Corregirlo localmente. |
| WebRequest 4014 | Revisar autorización de `http://127.0.0.1:8776` en esa instancia MT5. |
| `1001/1003` | Verificar HTTP/1.1 y código actualizado; fue la incompatibilidad documentada en el piloto. |
| `accepted` avanza pero fuente desconectada | Revisar SourceId y antigüedad de la muestra. |
| `queue_full` persiste | La entrega sigue sin confirmarse: conservar el error de envío y revisar el receptor. |

Los descartes son muestras de telemetría, no órdenes de trading.
No aumentar la cola ni aceptar `1001` como éxito: ocultaría la falta de confirmación.
El arranque no opera MT5, no cambia sus permisos ni ejecuta órdenes.

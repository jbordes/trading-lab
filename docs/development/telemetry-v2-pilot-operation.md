# Operación del piloto de recuperación histórica v2

Este procedimiento mantiene el estado vivo actual en v1 y obtiene el historial
recuperable mediante `TradingLabActivity` y SQLite v2. Solo se usa en la terminal
demo Juampi. No modificar ni instalarlo en la terminal del socio.

## Componentes y límites

| Componente | Valor del piloto |
| --- | --- |
| Receptor vivo v1 | `127.0.0.1:8776` |
| Receptor de actividad v2 | `127.0.0.1:8777` |
| Dashboard | `127.0.0.1:8775` |
| Fuente viva | `juampi-demo-01` |
| Fuente de actividad | `juampi-demo-activity-v2` |
| Cuenta interna | `cuenta-demo-juampi` |
| Base v1 | `_storage/piloto.sqlite3` |
| Base v2 | `_storage/piloto-v2.sqlite3` |

El supervisor nunca inicia ni detiene MT5. Solo administra los tres procesos
Python que él mismo crea. Falla sin adoptar ni cerrar servicios previos cuando un
puerto está ocupado.

## Configuración manual de MT5

En Herramientas → Opciones → Asesores Expertos, autorizar WebRequest para:

```text
http://127.0.0.1:8777
```

En el Navegador, refrescar `Asesores Expertos/TradingLab` y adjuntar
`TradingLabActivity` a un gráfico independiente. Usar:

| Parámetro | Valor |
| --- | --- |
| `IngestUrl` | `http://127.0.0.1:8777/v2/telemetry` |
| `Token` | token local de actividad, ASCII sin espacios y de 24 caracteres o más |
| `SourceId` | `juampi-demo-activity-v2` |
| `IntervalSeconds` | `10` |
| `RequestTimeoutMs` | `1000` |
| `HistoryStartServerTime` | `2026.10.20 00:00:00` para esta primera recuperación |
| `WindowSeconds` | `21600` |
| `MinimumWindowSeconds` | `60` |
| `OverlapSeconds` | `5` |
| `MaxItemsPerCollection` | `200` |
| `ExpectedDemoLogin` | login completo visible localmente en la terminal demo |
| `ExpectedDemoServer` | `RoboForex-Pro` |

No copiar el login ni los tokens a Git, documentación, comandos o chats. El token
de actividad introducido en el EA debe repetirse cuando el supervisor lo solicite.
El botón global de EAs debe permitir la ejecución; el collector no contiene
funciones de trading y no requiere permiso para operar.

El inicio elegido precede la cobertura v1 observada y las órdenes del EA de prueba.
Debe interpretarse como hora del servidor MT5. Un
inicio demasiado antiguo puede producir una recuperación extensa; uno demasiado
reciente deja datos fuera de la cobertura. Cambiarlo después exige revisar también
las variables globales `TL2.ACT.*`; no hacerlo de forma improvisada.

## Arranque único

Desde el checkout de `main` que contiene ambas bases:

```powershell
py -3 -m uv run python scripts/start_telemetry_v2_pilot.py
```

El comando solicita de forma oculta solo tres valores:

1. token vigente del collector v1;
2. token humano del dashboard;
3. token configurado en `TradingLabActivity`.

Genera internamente las credenciales efímeras que no debe conocer el operador,
comprueba que las cinco sean diferentes, abre los dos receptores, espera su salud y
recién entonces inicia el dashboard con historial v2. Ctrl+C detiene exclusivamente
esos tres procesos.

## Comprobación manual

1. Confirmar en la consola `Receptores v1/v2 listos`.
2. En MT5, revisar que `TradingLabActivity` no informe rechazos 4xx ni bloqueo por
   identidad, rango saturado o configuración inválida.
3. Abrir `http://127.0.0.1:8775/dashboard`, iniciar sesión con el segundo token y
   comprobar que el estado vivo siga mostrando `juampi-demo-01`.
4. En Trading → Operaciones cerradas, elegir un período que incluya
   `HistoryStartServerTime`; verificar los ciclos y el filtro por Magic Number.
   En Trading → Registro MT5, comprobar deals, órdenes y actividad en curso sin
   alterar las métricas.
5. Contrastar una muestra con Historial de MT5. Una orden cancelada puede existir
   en SQLite aunque no incremente trades ni métricas.
6. Detener con Ctrl+C y volver a iniciar. El cursor debe continuar desde lo
   confirmado, sin duplicar deals ni órdenes.

La cobertura ya viaja por la API, pero su indicador visual continúa pendiente. Un
lote `truncated` no se considera cobertura completa y requiere revisión antes de
usar métricas como si el período estuviera íntegro.

## Operaciones cerradas vacías después de actualizar el collector

`Operaciones cerradas` y sus métricas no se derivan de cualquier deal aislado.
Exigen una evidencia `position_reconcile` que contenga el ciclo completo de una
posición. Por eso es posible que `Registro MT5` muestre deals y órdenes mientras
ambas vistas continúan vacías.

Esto ocurre, en particular, si se sustituye `TradingLabActivity` 0.1 por 0.2
después de que las posiciones ya se cerraron. La versión 0.2 conserva el cursor
confirmado de la versión anterior y solo intenta reconciliar posiciones cuyos
deals de salida vuelve a observar. Los cierres anteriores al cursor permanecen
guardados como actividad, pero no producen retroactivamente un ciclo completo.

### Diagnóstico previo

Antes de cambiar estado, comprobar en modo de solo lectura:

1. el receptor v2 sigue aceptando mensajes recientes de
   `TradingLabActivity` 0.2;
2. `activity_observations` contiene deals de entrada y salida;
3. `position_cycle_observations` permanece vacía, o no contiene las posiciones
   esperadas;
4. no existen mensajes cuyo `payload.reason` sea `position_reconcile` para esas
   posiciones;
5. la primera ventana procesada por 0.2 comienza después de los cierres que
   faltan.

Si se cumplen estas cinco condiciones, no es un error de la interfaz ni de las
fórmulas: falta recuperar la evidencia completa desde MT5.

### Procedimiento de recuperación controlada

La corrección consiste en retroceder exclusivamente el cursor del collector de
actividad y dejar que la versión actual recorra otra vez el intervalo comprendido
desde `HistoryStartServerTime`. No se debe borrar ni recrear SQLite, cambiar el
`SourceId` para eludir el cursor, ni tocar cursores de otras fuentes.

Este procedimiento modifica estado operativo y requiere aprobación humana. Antes
de ejecutarlo se debe:

1. detener el collector de actividad sin cerrar ni modificar los EAs de trading;
2. identificar de forma inequívoca su variable global
   `TL2.ACT.<hash>.CURSOR`; no borrar variables por patrón;
3. comprobar que `HistoryStartServerTime` cubra las posiciones que faltan;
4. conservar la base existente y verificar que haya espacio para repetir la
   evidencia cruda;
5. retirar solo ese cursor y volver a iniciar `TradingLabActivity` 0.2 con la
   misma cuenta, `SourceId` y configuración;
6. esperar a que la recuperación alcance el presente y comprobar que aparecen
   mensajes `position_reconcile` y filas en `position_cycle_observations`;
7. contrastar una muestra contra MT5 antes de aceptar las métricas.

La repetición puede conservar observaciones crudas de un mismo ticket en mensajes
distintos. Las consultas funcionales seleccionan la evidencia vigente por ticket
o posición; no se debe limpiar manualmente la base para ocultar esa repetición.
Si aparece un rango saturado, un rechazo del receptor o una identidad diferente,
detener el procedimiento y diagnosticarlo antes de continuar.

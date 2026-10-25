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
4. En Historial, elegir un período que incluya `HistoryStartServerTime`; verificar
   que los deals y el filtro por Magic Number provengan de v2.
5. Contrastar una muestra con Historial de MT5. Una orden cancelada puede existir
   en SQLite aunque no incremente trades ni métricas.
6. Detener con Ctrl+C y volver a iniciar. El cursor debe continuar desde lo
   confirmado, sin duplicar deals ni órdenes.

La cobertura ya viaja por la API, pero su indicador visual continúa pendiente. Un
lote `truncated` no se considera cobertura completa y requiere revisión antes de
usar métricas como si el período estuviera íntegro.

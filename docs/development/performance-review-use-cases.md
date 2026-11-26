# Casos de uso de rendimiento de extremo a extremo

[Roadmap y medidas](performance-review-roadmap.md)

## Ingestión y proyección

La proyección usa la evidencia vigente y las dependencias temporales dentro de la transacción de admisión. Conservar los empates entre sesiones y la detección de reasignaciones. [Proyección](../../src/tradinglab/telemetry/remote_positions.py) · [Admisión](../../src/tradinglab/telemetry/sqlite_store_v2.py)

~~~text
para cada ticket observado:
    comparar evidencia vigente antes y después de guardar la observación
    si cambió su contenido, conflicto, procedencia o revisión relevante:
        agregar asignaciones anteriores y actuales
agregar posiciones cuyos intervalos intersectan el delta de cobertura
reconstruir cada posición afectada una vez antes de confirmar el lote
~~~

Validar lote repetido, reasignación, corrección económica, conflicto nuevo o resuelto y cambio de cobertura con lote vacío. Comparar ciclos y metadatos de procedencia. Medir el coste de detectar cambios frente a la reconstrucción que evita.

## Consulta financiera

La consulta debe conservar la prioridad de la evidencia vigente y el cursor numérico estable. Una versión antigua puede tener un magic o una fecha que coincida con el filtro actual. [Lectura SQLite](../../src/tradinglab/telemetry/sqlite_store_v2.py) · [Proveedor financiero](../../src/tradinglab/dashboard/telemetry_v2.py)

~~~text
medir plan de primera página y de continuación para una ventana de siete días
resolver versión vigente por posición incluyendo conflictos de revisión
aplicar filtros solo a la versión resuelta
ordenar por último evento e identificador numérico
si se piden ciclos livianos: recuperar solo los campos de cálculo
comparar resultados y tiempo con historiales de distinto tamaño
~~~

Validar empate de marca temporal, ticket grande, cambio de magic, dos cuentas y una corrección durante la paginación. Documentar el comportamiento si cambian los datos entre páginas.

## Cola durable

La última secuencia y la deduplicación tienen responsabilidades distintas. Comparar un índice que cubra el orden numérico de la secuencia antes de considerar un marcador persistido. [Cola](../../src/tradinglab/telemetry/relay_queue.py)

~~~text
cargar una cola sintética con confirmados y pendientes
medir plan de admisión y consulta de estado antes y después del índice
al admitir un lote: comprobar identidad y duplicado según el contrato existente
obtener la última secuencia en la misma transacción
repetir tras reiniciar y reenviar un lote confirmado antiguo
~~~

## Transporte del relay

Medir cada etapa antes de decidir si la reutilización de conexión basta o si conviene atender flujos concurrentemente. [Envío y rutas](../../src/tradinglab/multi_relay.py) · [Transporte HTTP](../../src/tradinglab/telemetry/relay_delivery.py)

~~~text
para cada stream:
    seleccionar su primer mensaje pendiente
    realizar envío con un plazo total y validar ACK central
    confirmar únicamente ese mensaje si su ACK es válido
registrar tiempo de cola, conexión y confirmación con dos streams
si persiste interferencia medible: limitar la concurrencia entre streams
~~~

Validar API lenta, desconexión, rechazo, reenvío y dos mensajes consecutivos del mismo stream.

## Primer acceso al dashboard

Preservar el primer sondeo síncrono para la cuenta solicitada y limitar su espera a quienes piden esa misma cuenta. [Vistas por cuenta](../../src/tradinglab/multi_dashboard.py) · [Poller](../../src/tradinglab/dashboard/service.py)

~~~text
bajo bloqueo del catálogo: obtener cuenta y reclamar su inicialización
si otra solicitud ya la inicializa: esperar su resultado fuera del bloqueo del catálogo
si esta solicitud es propietaria: crear y arrancar el servicio fuera del bloqueo del catálogo
publicar resultado o error para las solicitudes de esa cuenta
en cierre: coordinar altas pendientes y detener servicios publicados
~~~

Validar dos aperturas simultáneas de la misma cuenta, una cuenta que demora mientras otra abre, fallo del primer arranque y cierre concurrente.

## Condiciones de implementación y revisión posterior

- En proyección, usar la vía abreviada solo para tickets previamente observados con contenido idéntico, captura estrictamente posterior y ciclo materializado. Actualizar procedencia incluso cuando el resultado económico se conserva. Ante empates, conflictos, primera observación o cambio de asignación usar el cálculo completo en la misma transacción.
- En métricas, usar lectura directa de ciclos remotos cuando la transacción de lectura muestre que la cuenta carece de observaciones de ciclos legacy. Mantener el resolvedor de revisiones para cuentas mixtas. El cursor conserva el orden dentro de cada consulta; entre páginas se pueden recibir correcciones. La medición deberá registrar también esa condición.
- En la cola, validar la estructura previa antes de agregar índices y publicar la actualización atómicamente. Conservar contadores y deduplicación. El estado debe leerse de una sola instantánea mientras otro proceso confirma mensajes.
- En transporte, autenticar antes de interpretar el mensaje y comprobar fuente, rol e identidad sobre el mismo envelope validado que se encola. El worker multicuenta conserva como máximo una conexión ociosa por vez y la descarta al cambiar de origen, ante error o respuesta incompleta y durante el cierre. El reintento de un POST pasa por la cola durable. El paralelismo entre flujos queda condicionado a medición.
- En dashboard, garantizar que una inicialización fallida admita reintento y que el cierre alcance los servicios que estaban arrancando.

## Comparación pendiente

Repetir los casos tanto sobre `dee84e8` como sobre la candidata. Incluir una conexión HTTP persistente que el servidor cierre durante el reposo y un ACK truncado. Comprobar que el relay conserva el mensaje hasta la confirmación válida y libera el socket al detenerse. En la cola comprobar secuencias 9, 10 y valores grandes, incluso después de reiniciar con registros confirmados. En el dashboard observar dos pestañas de la misma cuenta durante la apertura de otra cuenta lenta.

# Roadmap de rendimiento de extremo a extremo

Rama `fix/tradinglab-review-performance`, basada en `dee84e8` mientras se revisa el PR #72. La primera etapa cubre API, dashboard y relay. Las intervenciones en MT5 permanecen en pausa. [Revisión completa](tradinglab-static-review.md) · [Pseudocódigo](performance-review-use-cases.md).

| Orden | Trabajo | Referencia para comparar |
|---|---|---|
| 1 | Ingestión y proyección | Duración de transacción, posiciones reconstruidas y ciclos modificados con lotes solapados, correcciones y cambios de cobertura |
| 2 | Performance financiera | Duración total y por página, con siete días de consulta y distintos tamaños de historial por cuenta |
| 3 | Cola durable del relay | Plan de consulta y duración de admisión y estado con muchos registros confirmados y pocos pendientes |
| 4 | Transporte del relay | Espera por flujo, tiempo de conexión y latencia de confirmación con dos cuentas y una respuesta central lenta |
| 5 | Dashboard multicuenta | Tiempo del primer acceso simultáneo a dos cuentas y número de pollers creados por cuenta |

Comparar el commit base y cada cambio usando los mismos datos, configuración y secuencia de peticiones. Registrar aparte la primera ejecución y las consecutivas. Comprobar equivalencia de ciclos, cobertura, métricas, orden y ACK antes de interpretar diferencias de rendimiento. La corrección del PR #72 que limita la reconstrucción por cobertura al delta efectivo ya forma parte de la base de comparación.

Dejar como casos diferidos la paginación densa, la recuperación reciente tras desconexión y las páginas que exceden el presupuesto de bytes. Antes de retomarlos, desglosar `HistorySelect`, escaneo, serialización y tiempo total del ciclo con la instrumentación existente.

La implementación actual se revisa estáticamente. Las mediciones pareadas, la comparación de planes y la prueba de concurrencia quedan para la validación posterior. Para la primera comparación usar bases sintéticas aisladas con tickets repetidos y corregidos, cuentas puramente remotas y mixtas, y una cola anterior con mensajes confirmados y pendientes.

La primera apertura de la cola v1 con esta versión verifica el esquema y los contadores y crea los índices en una transacción que publica el esquema v2. Para un ensayo de actualización usar una copia coherente de la cola detenida. Un rollback al binario anterior requiere una cola compatible y conciliar cualquier mensaje admitido después de la copia. El cambio afecta a la SQLite del relay.

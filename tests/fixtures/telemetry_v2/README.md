# Ejemplos sintéticos del contrato v2 propuesto

Especificación: [contrato v2](../../../docs/architecture/telemetry-v2-contract.md).
Estos archivos son vectores de diseño; el parser v1 debe rechazarlos. No son
capturas reales ni pruebas de un receptor v2 implementado. Los tiempos del broker
son deliberadamente independientes del UTC de captura, sin conversión supuesta.

Provisión ficticia: `synthetic-live` y `synthetic-activity` pertenecen a una misma
cuenta interna de prueba, con roles live y activity respectivamente. No contienen
credenciales. Cada escenario comienza con almacenamiento vacío salvo indicación.

| Archivo | Resultado esperado al implementar v2 |
| --- | --- |
| live-empty.json | Balance/equity 10000, cero posiciones y órdenes; actividad todavía desconocida |
| activity-canceled-order.json | Una sell limit cancelada sin ejecución; cero deals, ningún trade ni P/L generado por la cancelación |
| activity-deals-error.json | Consulta de deals fallida: conservar evidencia anterior y marcar degradación; órdenes sí consultadas |
| activity-truncated.json | Un deal de dos reportados: conservarlo como evidencia parcial, sin cobertura completa ni métricas definitivas |
| heartbeat.json | Actualizar salud del productor, sin rejuvenecer equity ni confirmar actividad |

## Escenarios de regresión que deberá cubrir la implementación

| Entrada o transformación | Resultado requerido |
| --- | --- |
| live-empty + activity-canceled-order, en cualquier orden | Misma vista compuesta; actividad no cambia equity |
| Repetir el mismo archivo de actividad | Una sola observación persistida, respuesta de duplicado |
| Cambiar precio conservando fuente/sesión/secuencia | Conflicto; no sobrescribir |
| Repetir ticket con nueva secuencia y captura posterior | Una entidad histórica, varias observaciones; corrección trazable |
| Recibir esa corrección antes que el lote original | Conservar corrección, sin retroceso por orden de llegada |
| activity-canceled-order seguido de activity-deals-error | Datos previos conservados, fallo visible y cobertura no extendida por error |
| Llegar actividad mientras estado vivo envejece | No presentar balance como actualizado |
| Heartbeat después de la última captura viva | Salud reciente, captura con su antigüedad original |
| activity_batch enviado por synthetic-live | Rechazo por rol antes de escribir |
| Credencial de una fuente enviando la otra fuente | Rechazo, sin registro automático |
| Repetir ticket en otra cuenta provisionada | Entidad diferente; no deduplicar entre cuentas |
| Reiniciar receptor y reenviar mensaje confirmado | No duplicar; restaurar tiempos y cobertura originales |
| Reiniciar collector con nueva sesión | Secuencia desde uno admitida, sin reiniciar historia de cuenta |
| Dos tickets distintos con el mismo time_msc | Conservar ambos, no usar solo timestamp como cursor |
| Ventana complete vacía después de un lote con registros | No borrar registros históricos; señalar discrepancia |
| complete con total diferente de longitud; error con filas | Rechazo de contrato |
| Ticket numérico JSON, NaN, claves duplicadas, campo inesperado | Rechazo de contrato |

No inferir un trade cerrado del deal sintético aislado: la definición de trade y
su agrupación por posición se acuerdan con el socio. Próximo paso: convertir esta
matriz en pruebas del validador y luego de admisión/persistencia/composición.

# Optimización de los collectors MT5

Base de comparación `feature/remote-data-platform` en `4a817a62117810c87b55dfc28b8a6924c9717b63`, después del PR #70. El trabajo se integra por PR desde `feature/collector-optimization`. Esta primera entrega documenta el plan y mide la versión vigente. Continúan vigentes la [captura ligera y reconstrucción central](remote-activity-roadmap.md) y el [ADR-0026](../adr/0026-reconstruccion-remota-de-posiciones.md).

## Objetivo y secuencia

Reducir el trabajo de MT5 por período cubierto, preservando el tiempo de llegada de actividad reciente y la equivalencia financiera. Separar descarga inicial, operación estable y recuperación de cortes. Un ACK del relay acredita persistencia local. Para acreditar disponibilidad al usuario se consulta también la API central.

| Orden | Entrega | Evidencia para continuar |
| --- | --- | --- |
| 0 | [Línea base](collector-optimization-baseline.md) en la versión vigente | Referencia de volumen, contenido y tiempo comprobada en Juampi. |
| 1 | UC1. Instrumentación agregada y diagnóstico por fase | Comparación inicial completada con los mismos binarios y cobertura y contenido equivalentes. La latencia de los EAs sigue pendiente. |
| 2 | UC2. Progreso garantizado al paginar por bytes | Una página grande se entrega en partes válidas. Un registro imposible queda diagnosticado sin reintento incesante. |
| 3 | UC3. Ventana adaptable para el historial antiguo | Menos consultas y turnos por período con igual cobertura, datos y frescura reciente. |
| 4 | UC4. Reutilización de UTF-8 | Aplicar si las mediciones muestran costo material. Comparar asignaciones, bytes y pico de memoria. |
| 5 | UC5–UC7. Historial repetido, completitud y desconexión de Telemetry | Auditar primero lectores y semántica. La reducción de datos requiere que cada consumidor pueda distinguir ausencia, muestra parcial y continuidad. |
| 6 | UC8–UC10. Escaneo denso, cadencia y relay | Opcionales e independientes. Elegir únicamente si los perfiles del escenario correspondiente muestran el cuello de botella. |

Cada entrega tiene un [caso de uso con pasos y aceptación](collector-optimization-use-cases.md). Registrar en el PR la revisión probada, los resultados y el motivo para implementar o descartar cada opción. Mantener la bitácora diaria en integración según el protocolo del programa.

## Condiciones de aceptación

- Igualdad por cuenta, tipo y ticket, importes, volúmenes, proyección de posiciones, coberturas y límites de fecha. Comparar también cierres parciales, comisiones, swap y fee. Una orden colocada antes del corte puede ejecutarse dentro del período. Aplicar en la proyección el criterio de primera ejecución del ADR.
- Mismo conjunto de estrategias, gráficos, configuración, topología y datos históricos en las dos versiones de la prueba. Separar caché fría y caliente. Registrar CPU, memoria, frescura reciente y demora de eventos de los EAs si hay una fuente observable. Marcar como pendiente cualquier medición ausente.
- Usar la dispersión de repeticiones de control para interpretar diferencias. Rechazar regresiones reproducibles en frescura reciente, recursos de la terminal o integridad, aunque se acorte el historial. Una corrida aislada permite detectar fallos y orientar la siguiente prueba.
- En cada comparación usar configuraciones privadas equivalentes y entornos aislados. Conservar el paquete y configuración de referencia para repetir el control. Revertir una etapa ejecutando el control en su entorno aislado. Cualquier cambio futuro de contrato debe conservar compatibilidad durante el despliegue y probar la reversión antes de publicarse.

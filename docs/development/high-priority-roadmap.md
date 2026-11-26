# Roadmap de hallazgos de prioridad alta

Rama `fix/tradinglab-review-high-priority`. Base de código revisada `8e2ea6c`. Este documento propone el alcance de la implementación futura. [Revisión completa](tradinglab-static-review.md) · [Casos de uso y pseudocódigo](high-priority-use-cases.md).

| Orden | Entrega | Dependencia | Evidencia para cerrar |
|---|---|---|---|
| 1 | Copia y restauración de la base central | Independiente. Conviene disponer de una copia verificable antes de intervenir sobre proyecciones existentes. | Copias de esquemas 8, 9 y 10 restaurables en un directorio vacío. Vista previa coherente con la ejecución. Mantenimiento de escritura limitado a los esquemas previamente soportados. |
| 2 | Cobertura de actividad coherente | Fijar la política de intervalos y conflictos antes de cambiar el lector o reconstruir posiciones. | Para la misma cuenta, intervalo y entidad, API y proyección coinciden. El indicador financiero contempla órdenes y deals. Las bases existentes convergen con las nuevas. |
| 3 | Progreso de Activity con heartbeat vencido | Independiente del esquema. Conservar la prioridad relativa actual entre actividad reciente e histórica. | Con temporizador y heartbeat de igual duración avanzan los datos y se confirma periódicamente el heartbeat. Los reintentos preservan el mensaje y los cursores. |
| 4 | Compilación y empaquetado del SetUp | Usar el Activity resultante del punto 3 para cerrar la entrega. | Una compilación limpia genera un paquete verificable. Cambios en dependencias invalidan los EX5 afectados. Una compilación interrumpida o parcial se detecta antes de publicar. |

El orden comienza por backup por su utilidad para recuperar una base existente. Cada entrega admite un commit independiente. La corrección de progreso en Activity es acotada al planificador. Las ventanas adaptables, la concurrencia y el rendimiento de consultas pertenecen a las otras líneas de trabajo de la revisión.

Para comparar resultados se proponen bases temporales con cuentas y evidencia sintéticas, reloj y respuestas controlados para Activity, y un directorio de compilación aislado. Registrar en cada entrega el caso observado antes y después, la versión ensayada y los límites que queden pendientes. Las verificaciones descritas son criterios para la etapa de implementación.

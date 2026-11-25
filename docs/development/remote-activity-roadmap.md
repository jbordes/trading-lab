# Captura ligera de MT5 y reconstrucción central

Rama de trabajo `feature/remote-activity-reconstruction`, creada desde `feature/remote-data-platform` en `05daf13` (merge de #69). La rama de integración es el destino del PR. La decisión se documenta en el [ADR-0026](../adr/0026-reconstruccion-remota-de-posiciones.md).

| Tarea | Resultado de desarrollo | Criterio de aceptación |
| --- | --- | --- |
| Contrato y compatibilidad | Activity usa `/trading-events/resolve-raw`. La API verifica que la base tenga la proyección antes de resolver la cuenta. El relay conserva las vinculaciones y acepta el contrato anterior. | Con API, relay o esquema antiguos, el Activity nuevo espera antes de tomar un cursor. El Activity anterior sigue resolviendo en `/resolve`. |
| Proyección financiera | Índices por cuenta y posición, deduplicación por tipo y ticket, evidencia de apertura, cobertura continua y motor de volumen, comisiones y atribución existente. La API consulta la proyección paginada y entrega detalle y magics. | Comparar tickets, lado, precios, volumen, comisión, swap, fee y resultado con operaciones conocidas. Los cierres parciales suman una operación al quedar el volumen en cero. |
| Fecha desde | El corte del catálogo usa la primera ejecución, en milisegundos del bróker. | Abrir antes y cerrar después excluye el ciclo. Una pendiente colocada antes y ejecutada después entra al cumplirse los demás criterios. Una apertura recibida con retraso debe poder completar posteriormente el ciclo. |
| Carga acotada | Activity conserva envío con reintento, paginación, solapamiento y cursores por cuenta. Avanza tras el ACK del lote. Se retiró la lectura por posición. | Interrumpir el enlace, arrancar con historial profundo y comparar el cursor y los tickets tras recuperar. Registrar latencia de los EAs, CPU del terminal, tiempo de recuperación y pendientes del relay con la misma carga. |
| Distribución | El perfil local sigue disponible. Un host MT5 con cero servicios de TradingLab puede preparar la terminal con el ID público del relay y la vinculación en API. | Validar en dos hosts el certificado, las dos rutas de datos y sus rutas de resolución. Cambiar entre dos cuentas conocidas y una desconocida. |
| Actualización | Esquema multicuenta 10 en instalaciones nuevas. Actualización explícita 9 → 10 con reconstrucción desde observaciones. La consulta conserva las conciliaciones históricas dentro del corte. | Probar vista previa y aplicación sobre una copia. Validar lectura antes y después, posiciones antiguas, cierres confirmados y colas existentes. |

## Estado de la rama

- `54641e6` incorpora la proyección central, el corte por apertura y la actualización transaccional desde el esquema 9. `3cd54a1` incorpora Activity 0.9.0, el relay remoto y su preparación desde SetUp.
- Los modos `fast` y `full` pasaron. La corrida final completó 53 pruebas del harness y 533 de producto. Los casos nuevos cubren cierre recibido antes de la apertura, llegada posterior de una ventana vacía, repetición de una salida, exclusión por fecha, orden pendiente ejecutada desde el corte y cierres parciales.
- MetaEditor compiló Activity, Telemetry y el asistente con cero errores y cero advertencias. Los binarios de trabajo están en `_storage/setup/compiled/` del worktree.
- El 25 de noviembre se verificó una instalación limpia en demo con esquema 10. Activity 0.9.0 cubrió de forma continua órdenes y ejecuciones desde el 1 de noviembre hasta ponerse al día en unos 30 minutos. El relay registró 4.825 entregas confirmadas, cero pendientes y ningún rechazo en la última revisión.
- Quedan para las pruebas manuales la comparación financiera con MT5, el enlace HTTPS entre servidores y la medición de carga de la terminal.

## Secuencia de aceptación en demo

1. Guardar la configuración de fechas, una muestra de tickets y los valores actuales de ejecución y financiera. Registrar el rango y la cobertura que muestra el dashboard para comparar períodos iguales.
2. Validar la actualización con una copia y preparar los servicios según la [guía de SetUp](tradinglab-setup.md). Arrancar primero API y relay. Comprobar el collector anterior y un cierre histórico existente.
3. Cargar los collectors nuevos en sus gráficos dedicados. Registrar avance reciente e histórico. Un cierre que llega antes que la apertura o antes de cubrir una ventana intermedia debe esperar. Enviar por solapamiento otra observación del mismo ticket y verificar un único resultado.
4. Interrumpir y recuperar el enlace MT5 → relay y después el enlace relay → API. En el segundo caso el relay debe seguir confirmando lotes ya vinculados. Las cuentas nuevas requieren que el catálogo esté disponible. Verificar el origen de los lotes antes y después de cambiar de cuenta.
5. Medir tiempos y carga en demo, comparar financiera y ejecución, revisar el diff y abrir el PR hacia integración. La validación funcional en terminal y el despliegue quedan a cargo de la aceptación manual.

## Recuperación

Mientras se evalúa la nueva versión se puede volver a Activity 0.8.4 contra los servicios actualizados. Para volver también al servidor anterior hay que usar la copia de esquema 9 y planificar la recuperación de los lotes admitidos después del backup. Restaurar la copia por sí sola perdería esas admisiones. Conservar los ficheros privados y los cursores hasta terminar la comparación.

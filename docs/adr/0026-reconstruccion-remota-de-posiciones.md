# ADR-0026 · Reconstrucción de posiciones fuera de MT5

**Estado:** proposed

**Fecha:** 2026-11-21

## Contexto

Activity 0.8.4 rastrea posiciones con salidas, consulta su historial individual y espera el ACK de cada conciliación antes de avanzar. El host de MT5 comparte recursos con los EAs operadores. El catálogo multicuenta define la fecha inicial en hora de servidor del bróker. La plataforma también tiene instalaciones con MT5, relay y API en un mismo equipo.

## Decisión

Activity 0.9.0 entrega órdenes y ejecuciones mediante el contrato de lotes existente. Conserva identidad de cuenta, prioridad del tramo reciente, ventanas acotadas, paginación, reintentos y cursores. El ACK corresponde al registro durable en el relay. El servidor central proyecta los ciclos por cuenta y posición dentro de la transacción de admisión. Un lote duplicado mantiene la misma identidad. Una ventana vacía completa también puede completar la evidencia que faltaba entre dos ejecuciones.

La inclusión financiera exige que la primera ejecución de apertura ocurra desde el corte inclusivo de la cuenta. Se verifica la orden de apertura, su volumen ejecutado, la cobertura de órdenes y ejecuciones y el cierre de volumen con las reglas del motor de ciclos. La fecha de colocación de una orden pendiente puede ser anterior. Un cierre dentro del período sigue visible en ejecución aunque su apertura sea anterior. Los filtros temporales de visualización sobre los cierres siguen usando la fecha de cierre.

El relay puede vivir en otro equipo. SetUp admite HTTPS para los colectores mediante un proxy TLS delante del relay. En una instalación local continúa usando HTTP en loopback. El catálogo entrega credenciales por terminal, rol y relay al preparar una terminal remota. Las credenciales de administración se presentan únicamente a la API. Telemetry conserva el contrato de observación de estado, incluida su muestra acotada de historial.

## Alternativas consideradas

Una terminal MT5 dedicada reduciría la competencia con los EAs pero mantendría el trabajo repetido por posición. Reconstruir desde cero al abrir el dashboard trasladaría la espera a cada consulta. La base materializa las posiciones afectadas por un lote y vuelve a evaluar las pendientes al cubrirse el intervalo.

## Consecuencias

Una base multicuenta existente requiere una actualización explícita de esquema antes de activar Activity 0.9.0. El proceso admite vista previa y una transacción para aplicar los cambios y reconstruir desde el historial guardado. Las conciliaciones históricas se pueden seguir leyendo. La pérdida de conectividad puede demorar la captura. Activity recupera desde su cursor y Telemetry conserva los límites de su cola volátil. El operador gestiona el proxy y su certificado.

El [roadmap de implementación y aceptación](../development/remote-activity-roadmap.md) registra los criterios de verificación.

# API central con FastAPI y mejoras de diseño

**Estado:** implementación preparada para validación e integración; piloto manual pendiente.

Operación: [API central FastAPI](central-api-operation.md). Decisión:
[ADR-0018](../adr/0018-fastapi-central-api.md). Incluye separación del transporte/ACK
del relay, consultas HTTP compartidas y extracción de esquema/migraciones SQLite.

**Rama:** `feature/fastapi-central-api`, desde `feature/durable-telemetry-relay`
en `6ce5edc` (PR 58). Mantener el flujo de integración del
[programa remoto](remote-data-platform-delivery.md).

## Objetivo

Adoptar FastAPI y OpenAPI para la API central antes del despliegue en la Mac,
reutilizando admisión, persistencia y cálculos probados. Completar las mejoras
concretas de separación de responsabilidades detectadas en el relay. La auditoría
de diseño de todo el código Python es una tarea independiente, todavía pendiente.

## Trabajo de esta rama

1. **API central:** introducir FastAPI con arranque y cierre explícitos de recursos,
   configuración segura y separación de credenciales. Mantener el despliegue
   optativo hasta completar la validación local.
2. **OpenAPI:** ofrecer `/openapi.json` y documentación interactiva con modelos de
   entrada/salida, autenticación, errores y ejemplos reales sintéticos. Evitar que
   los modelos generados describan un contrato distinto del que acepta el servidor.
3. **Contratos:** separar reglas de negocio, garantías de integridad y decisiones
   de transporte. Las rutas, campos y códigos pueden evolucionar cuando exista
   una mejora justificada; documentar el cambio y actualizar consumidores o
   proporcionar compatibilidad explícita. No permitir cambios accidentales por
   coerciones de tipos o respuestas predeterminadas del framework.
4. **Relay:** separar el cliente HTTP de la coordinación de reintentos y de la
   interpretación del ACK. Inyectar el transporte para probarlo sin interceptar
   métodos internos; dar al forwarder sus dependencias necesarias directamente,
   en lugar de obtenerlas de atributos públicos de `RelayIngress`.
5. **Cohesión y duplicación:** reducir la lógica HTTP manual repetida en la API
   central y delimitar las responsabilidades del registro SQLite. Cualquier
   extracción de consultas, proyecciones o migraciones debe conservar transacciones
   y comportamiento, y tener una necesidad concreta. Evitar una reorganización
   general de todo el proyecto dentro de esta entrega.
6. **Verificación:** probar contratos, autorización, tipos estrictos, errores,
   límites, ACK tras commit y compatibilidad con los EAs/relay. Ejecutar pruebas
   dirigidas de las fronteras modificadas y dejar el gate completo en GitHub.

## Garantías a conservar

- Confirmar recepción local solo tras guardar en la outbox y confirmar central
  solo tras persistencia central durable.
- Mantener la identidad original del mensaje, deduplicación, asociación de
  cuenta/fuente y aislamiento de permisos.
- Conservar tiempos originales y no confundir reenvío con captura reciente.
- Preservar cálculos y reglas acordadas de posiciones completas y elegibilidad
  de métricas; cambiar el framework no altera fórmulas ni reglas de negocio.
- Los EAs actuales reconocen HTTP 200/202 como confirmación. El relay valida
  además el JSON del ACK central. Un cambio deliberado debe contemplar ambos
  consumidores; esos códigos no son una exigencia técnica impuesta por MT5.
- La cola sigue siendo un componente independiente de FastAPI: persiste y entrega
  mensajes aunque la API central esté temporalmente indisponible.

## Criterio de cierre

La API implementada y OpenAPI deben coincidir, las pruebas de contrato y
recuperación deben pasar y la documentación operativa debe explicar cómo probar
el conjunto localmente. El PR pertenecerá al programa remoto, con merge humano;
no activa infraestructura remota ni realiza migraciones de datos automáticamente.

## Tarea independiente pendiente

[Revisión completa de diseño Python](python-design-review-plan.md): cubrir todo
el proyecto, más allá de los módulos modificados por esta rama.

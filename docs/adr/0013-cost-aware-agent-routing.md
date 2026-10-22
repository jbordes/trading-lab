# ADR-0013: Enrutar tareas del harness según coste y complejidad

**Estado:** accepted

**Fecha:** 2026-10-22

## Contexto

Operaciones mecánicas como crear ramas, preparar commits, publicar un PR o registrar
una decisión consumen contexto y tiempo del modelo de razonamiento principal. Esas
tareas siguen procedimientos estables y verificables. Usar siempre el modelo más
potente encarece el trabajo sin mejorar proporcionalmente el resultado.

La delegación tampoco debe entregar decisiones de arquitectura o permisos amplios
a un agente económico, ni repetir toda la conversación para cada tarea.

## Alternativas consideradas

1. Usar el mismo modelo para análisis, código, Git y documentación. Es simple, pero
   paga razonamiento de alto coste para acciones deterministas.
2. Delegar todo Git y toda documentación sin límites. Reduce coste, pero puede
   ocultar conflictos, reinterpretar decisiones o ampliar el alcance del cambio.
3. Automatizar primero lo determinista y usar agentes económicos especializados
   con encargos breves, rutas permitidas y condiciones claras de escalamiento.

## Decisión

Adoptar la tercera alternativa como dirección de Harness 0.2. El agente principal
se reserva para arquitectura, diseño, depuración compleja, revisión de riesgos y
cambios de comportamiento. Dos roles económicos podrán ejecutar tareas ya
definidas cuando el entorno permita elegir modelo:

- operador Git: estado, rama, diff, commit, push, apertura y consulta de PR;
- registrador documental: actualizar documentos y bitácora desde decisiones ya
  aprobadas, sin crear nuevas decisiones ni reinterpretar su alcance.

Cada encargo incluirá objetivo, rama o worktree, rutas autorizadas, texto o decisión
fuente, validación requerida y condición de escalamiento. El agente principal
revisará el diff material antes de entregar el cambio. Conflictos, force-push,
reescritura de historia, borrados, migraciones y merges vuelven al agente principal
o requieren la aprobación humana ya definida por el proyecto.

Los scripts siguen siendo la primera opción para pasos deterministas. Un agente
económico orquesta esos scripts y resuelve variaciones pequeñas; no reemplaza una
automatización repetible con conversación. El merge continúa siendo humano.

## Consecuencias

- El modelo principal dedica más presupuesto a decisiones y problemas difíciles.
- Los handoffs deben ser pequeños; enviar el historial completo eliminaría buena
  parte del ahorro y aumentaría el riesgo de confusión.
- La selección concreta de modelos y la configuración de agentes se implementarán
  en un cambio separado y deberán demostrar ahorro sin reducir controles de Git.
- Hasta implementar esos roles, esta decisión documenta el reparto esperado pero
  no obliga a simularlos manualmente en cada operación.

## Reemplaza

No aplica. Extiende el diseño evolutivo de Harness 0.1.

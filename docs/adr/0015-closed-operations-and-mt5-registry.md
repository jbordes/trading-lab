# ADR-0015: Operaciones cerradas y registro MT5

**Estado:** accepted

**Fecha:** 2026-10-27

## Contexto

ADR-0014 unificó la exploración de actividad bajo `Trading`, pero propuso deals y
órdenes como alcances principales. Esa organización todavía traslada entidades
técnicas de MT5 a la navegación del analista. Además, presentar métricas junto a
deals individuales sugiere incorrectamente que cada ejecución equivale a una
operación completa.

El analista necesita evaluar operaciones que terminaron de principio a fin y, en
otra tarea distinta, investigar toda la evidencia que explica qué hicieron MT5,
un EA o una intervención externa.

## Alternativas consideradas

1. Mantener `Ejecuciones` y `Órdenes` como vistas principales y explicar la
   diferencia. Conserva la implementación incremental, pero no resuelve el modelo
   mental ni la unidad usada para las métricas.
2. Aplanar órdenes, deals y posiciones en una única tabla de trades. Simplifica la
   apariencia a costa de perder trazabilidad y semántica MT5.
3. Separar el análisis de operaciones reconstruidas del registro exhaustivo, sin
   modificar las entidades durables ni sus fuentes.

## Decisión

Adoptar la tercera alternativa. `Trading` tendrá tres alcances orientados a tareas:

- `En curso`: posiciones abiertas y órdenes pendientes del snapshot vigente.
- `Operaciones cerradas`: ciclos reconstruidos mediante `account_id + position_id`.
  Las métricas y gráficos usan exclusivamente ciclos completos, cerrados,
  atribuibles a un único EA y sin exclusiones.
- `Registro MT5`: cronología investigable de ejecuciones, órdenes y actividad en
  curso, con filtros por entidad, período y Magic Number. Ninguna agregación del
  registro alimenta métricas directamente.

Las operaciones cerradas excluidas de las métricas permanecen visibles con su
motivo. Las fórmulas aplicadas a ciclos se versionan como `position-cycle-v1`;
`partner-workbook-v1` conserva su significado provisional basado en deals y no se
redefine silenciosamente.

## Consecuencias

- La unidad visible junto a las métricas coincide con la unidad medida.
- Deals y órdenes siguen disponibles para auditoría sin dominar la navegación.
- El registro combinado requiere ordenar respuestas de fuentes diferentes y
  mantener explícito el tipo real de cada fila.
- Los períodos sin ciclos elegibles pueden mostrar evidencia en el registro y, al
  mismo tiempo, cero operaciones válidas para rendimiento.
- La zona horaria y la cobertura siguen siendo contexto obligatorio antes de
  interpretar períodos como completos.

## Reemplaza

Reemplaza únicamente la organización de alcances de consulta definida en la
sección «Experiencia de consulta» de
[ADR-0014](0014-unified-trading-activity-and-position-cycle-metrics.md). Mantiene
vigentes su identidad de ciclo, atribución, exclusiones y tratamiento de netting.

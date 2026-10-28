# ADR-0016: Separar performance financiera y de ejecución

**Estado:** accepted

**Fecha:** 2026-10-28

## Contexto

La actividad en curso, el análisis de operaciones cerradas y la consulta del
registro MT5 responden a tareas diferentes. Agruparlas bajo un único menú
`Trading` dificulta distinguir el rendimiento financiero de la evidencia sobre
el comportamiento de ejecución.

## Alternativas consideradas

1. Mantener los tres alcances dentro de `Trading`, como propone ADR-0015. Es
   sencillo y conserva una sola sección, pero mezcla tareas de consulta distintas.
2. Separar la navegación por tarea y mantener intactos los contratos de actividad,
   atribución y métricas. Añade entradas laterales, pero hace explícita la
   diferencia entre estado operativo, resultados financieros y ejecución.

## Decisión

Adoptar la segunda alternativa. La navegación tendrá tres entradas:

- `Trading`: solo posiciones y órdenes en curso.
- `Performance financiera`: operaciones cerradas, métricas y gráficos existentes.
- `Performance de ejecución`: Registro MT5 para consultar el comportamiento
  observado.

La separación cambia la navegación, no los datos ni su semántica. Se conservan
la identidad de ciclo por cuenta y posición, las reglas de atribución y
exclusión, y las fórmulas versionadas definidas en ADR-0015. Las tablas mantienen
un estilo consistente y los enlaces antiguos siguen siendo válidos.

## Consecuencias

- Las tareas de operación en curso, análisis financiero e investigación de
  ejecución quedan diferenciadas en la navegación.
- El Registro MT5 ofrece evidencia consultable, pero no se presenta como una
  métrica de ejecución ya definida.
- Definir métricas y gráficos de ejecución, y determinar si requieren persistir
  evidencia adicional, queda pendiente de datos y definiciones; no se presupone
  cobertura completa.

## Reemplaza

Reemplaza únicamente la agrupación de navegación adoptada por ADR-0015. Mantiene
vigentes la identidad cuenta+posición, la atribución, las exclusiones y las
fórmulas de ese ADR.

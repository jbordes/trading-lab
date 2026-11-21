# Revisión completa de diseño y buenas prácticas Python

**Estado:** iniciada el 2026-11-05; revisión estática parcial realizada, no es
una auditoría completa ni incluye benchmarks. Ver [revisión inicial de diseño y
rendimiento](python-collector-design-performance-review.md).

## Alcance

Revisar el código Python de `src/tradinglab/`, `scripts/` y las pruebas relevantes.
Incluir APIs, collectors/adaptadores Python, persistencia, métricas, dashboard,
configuración, jobs y harness. La revisión parcial no sustituye la cobertura
restante descrita en el informe enlazado.

## Aspectos a evaluar

- SOLID: cohesión, responsabilidades, dependencias y tamaño de las interfaces.
- DRY: duplicación de conocimiento y reglas, diferenciándola de similitudes
  justificadas entre versiones o fronteras distintas.
- YAGNI y simplicidad: capas o abstracciones sin necesidad demostrada y soluciones
  manuales cuyo mantenimiento ya justifique una herramienta existente.
- Encapsulamiento: estado mutable público, acceso a detalles privados y contratos
  claros entre componentes.
- Patrones de diseño: adecuación de adapters, outbox, repositorios y otros patrones
  realmente presentes; evaluar beneficios concretos, no contabilizar patrones.
- Separación entre reglas de trading/métricas, casos de uso e infraestructura.
- Tipos y validación de interfaces públicas, errores útiles y control de recursos.
- Testabilidad de reloj, red, procesos, aleatoriedad y persistencia; detectar
  pruebas demasiado acopladas a detalles de implementación.
- Rendimiento: complejidad de recorridos, memoria acotada, paginación, contención,
  parseos e I/O repetidos; aplicar las guías consultadas según el contexto, sin
  introducir librerías, cachés o concurrencia por rutina.

## Entregable y forma de ejecución

Realizar primero una revisión de solo lectura, dividida por componentes para
mantener el alcance manejable. Entregar hallazgos priorizados con ubicación,
evidencia, efecto práctico y propuesta proporcional; distinguir bugs de deuda de
diseño y preferencias de estilo. No justificar refactors únicamente por longitud
de archivo ni por adhesión ceremonial a un principio.

Las correcciones se acordarán y agruparán después por capacidad o riesgo, con
pruebas dirigidas y PR humano. Esta tarea no bloquea por defecto el piloto remoto
ni implica reescribir el proyecto. Un hallazgo crítico sí deberá evaluarse antes
de continuar con la capacidad afectada.

# Revisión de eficiencia del harness

**Estado:** propuesta de evaluación diferida; no implementada.

Esta nota recoge hipótesis para reducir el costo total del trabajo con agentes.
No cambia el enrutamiento ni las validaciones vigentes. La configuración actual
de roles está descrita en [Agentes de costo acotado](cost-aware-agents.md), bajo
ADR-0013.

## Observaciones y preparación existente

Se observan cuatro fuentes posibles de fricción: exceso de contexto en los
encargos, repetición de verificaciones, delegaciones demasiado pequeñas y
confusión entre documentar una decisión e implementar el cambio. Ya están
preparados el chequeo `docs` y los agentes `git_operator` y `docs_recorder`.
El ahorro no se ha medido. El piloto anterior invocó el agente manualmente;
queda pendiente verificar el descubrimiento automático de los archivos TOML.

## Cómo evaluar

Probar primero cinco encargos reales y registrar para cada uno el rol usado,
escalamientos y retrabajo. Delegar paquetes con resultado claro, no comandos
aislados. El agente principal conserva el juicio y las decisiones; los scripts
se ocupan de la mecánica determinista.

El criterio de éxito es el ahorro total de coordinación, ejecución y
retrabajo. No se debe inferir ahorro por usar un modelo más barato. Si no hay
medición de tokens, usar indicadores observables sin inventar porcentajes. Cada
paso debe producir un resultado preciso: contrato documentado, receptor
implementado o comportamiento probado con datos reales. La entrega resume qué
cambió, qué se validó y qué queda pendiente sin duplicar documentos.

## Candidatas para evaluar después del piloto

- Un resumen pequeño de `change inspect` con rama, rutas, diffstat y
  validaciones sugeridas; consultar el estado del PR sería opcional.
- Un selector de validaciones con pocas reglas explícitas y pruebas
  proporcionales. La documentación no requiere suites de producto ni tres
  sistemas operativos. Para el harness sí importa la portabilidad, aunque CI
  todavía ejecute el conjunto completo en tres sistemas.
- Registrar qué se validó y repetir solo lo que un cambio posterior pueda
  invalidar. Se pospone crear receipts o caché: el hash del diff por sí solo
  no representa la base, las dependencias, el entorno ni los archivos no
  versionados relevantes.
- Posponer el comando para agregar entradas a la bitácora y un auditor de
  worktrees hasta tener evidencia de costo. Evaluar ignorar `/.tmp-*/` para
  reducir ruido en Git, revisando antes su alcance. Nunca borrar esos
  directorios automáticamente.
- No añadir roles. Considerar esfuerzo `low` para razonamiento de Git solo
  después de los pilotos y con evidencia.

## Límites vigentes y siguiente paso

Se mantienen las ramas cortas y el flujo de PR con merge humano. La bitácora
diaria se gestiona aparte: solo se modifica directamente en `main`, para la
fecha actual de Europe/Madrid, y sin mezclar otras rutas. Una rama de cambio no
incluye entradas de `docs/sessions/`; las fechas anteriores son inmutables.

No se requiere una ADR nueva mientras la evaluación siga pendiente bajo
ADR-0013. Tras los pilotos, revisar los resultados y elegir únicamente la
automatización que reduzca fricción; después, devolver el foco al historial y
las métricas.

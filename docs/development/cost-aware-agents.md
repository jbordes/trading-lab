# Agentes de costo acotado

**Estado:** Vigente en Harness 0.2; evaluación de eficiencia todavía abierta.

Esta configuración implementa [ADR-0013](../adr/0013-cost-aware-agent-routing.md)
mediante agentes de proyecto de Codex. La selección sigue la documentación
oficial de subagentes: cada rol vive en `.codex/agents/`, fija su modelo e
instrucciones y hereda permisos y sandbox de la sesión principal.

## Roles

| Agente | Uso | No puede decidir |
| --- | --- | --- |
| `git_operator` | Paquetes mecánicos ya definidos: preparar rutas revisadas, commit, push y PR | Contenido, conflictos, reescritura de historia, merge o cambios en `main` |
| `docs_recorder` | Plasmar decisiones aprobadas en rutas documentales enumeradas | Arquitectura nueva, alcance, código, Git o correcciones retroactivas de bitácora |

Ambos usan `gpt-6-luna` con esfuerzo medio y salida breve. Se desactivan apps,
plugins, memorias, solicitud de permisos y skills para reducir superficie y
contexto. Estas restricciones no crean un sandbox independiente: el agente
principal conserva responsabilidad sobre permisos, encargo y revisión.

## Cuándo delegar

Delegar solo cuando exista un paquete suficiente para amortizar el handoff. Un
comando aislado, una línea documental o pasos dependientes continúan en el agente
principal. El encargo no lleva la conversación completa; incluye únicamente:

1. objetivo concreto y resultado esperado;
2. worktree, rama y rutas autorizadas;
3. decisión o texto fuente, sin reinterpretarlo;
4. validación ya realizada o comando exacto pendiente;
5. condiciones que obligan a frenar y escalar.

El agente principal define el cambio, revisa el diff material y conserva la
depuración, arquitectura, seguridad y decisiones. El merge sigue siendo humano.

## Evaluación inicial

Durante los primeros cinco encargos registrar de forma breve el rol utilizado,
si completó el paquete sin escalamiento y si hubo que rehacer su salida. No hace
falta guardar prompts ni secretos. Si el handoff agrega más trabajo que el que
elimina, reducir su alcance o retirar el rol antes de sumar otros agentes.

Referencia: [Subagents — OpenAI Docs](https://learn.chatgpt.com/docs/agent-configuration/subagents).

La evaluación de eficiencia del harness está pendiente; véase
[Revisión de eficiencia del harness](harness-efficiency-review.md).

# Bitácora de sesiones

La bitácora conserva el contexto cronológico del trabajo. No sustituye la arquitectura, los ADR, los manifests, el catálogo ni el storage: enlaza esas fuentes de verdad sin copiar su contenido completo.

## Cuándo actualizarla

Cada rama de cambio debe crear o actualizar al menos una entrada `YYYY-MM-DD-<tema>.md`. La entrada puede abarcar varias conversaciones dedicadas al mismo objetivo, pero debe quedar cerrada antes de solicitar el merge.

Una sesión registra:

- objetivo y alcance;
- hechos y evidencias verificables;
- interpretaciones separadas de los hechos;
- trabajo realizado y validación ejecutada;
- decisiones y ADR relacionados;
- preguntas abiertas y próximo paso;
- referencias a proyectos, experimentos, runs, commits y PR cuando existan.

No debe contener secretos, resultados autoritativos completos ni grandes bloques de logs.

## Flujo

Crear una entrada desde la plantilla portable:

```text
uv run python scripts/session.py new <tema> --objective "Objetivo concreto"
```

Durante el trabajo se mantiene `**Estado:** En curso`. Antes del PR se completan las secciones, se cambia a `**Estado:** Cerrada` y se valida:

```text
uv run python scripts/session.py check --closed
uv run python scripts/check.py full
```

El check completo exige que una rama distinta de `main` modifique al menos una entrada de sesión. Las entradas anteriores al 12 de octubre de 2026 conservan su formato histórico; las posteriores utilizan `session-v1`.

## Relación con ADR

Una decisión durable o con alternativas significativas se registra en `docs/adr/`. La sesión enlaza el ADR y cuenta qué ocurrió; el ADR conserva el razonamiento; la arquitectura refleja el resultado vigente.

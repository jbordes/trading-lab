# Bitácora diaria

La bitácora conserva el contexto cronológico del trabajo cotidiano de TradingLab, haya o no cambios en Git. Registra actividades, decisiones, análisis, cambios de estrategias o datos y cualquier información útil para continuar el laboratorio. No sustituye la arquitectura, los ADR, manifests, catálogo ni storage: enlaza esas fuentes de verdad.

## Unidad y nombres

La unidad es el día calendario en `Europe/Madrid`, no una feature ni una rama. Puede existir una o varias entradas del día con nombres `YYYY-MM-DD.md` o `YYYY-MM-DD-<tema>.md`.

Las bitácoras diarias son canónicas en `main` y no deben viajar dentro de ramas de cambio. Una feature solo se menciona como iniciada, continuada o terminada cuando resulte relevante para la jornada.

## Inmutabilidad

Solo se pueden crear o actualizar entradas cuya fecha inicial coincida con el día actual en `Europe/Madrid`. Al cambiar el día, todas las entradas anteriores quedan inmutables. Una corrección posterior se registra en la bitácora del día corriente y referencia la entrada antigua; nunca se reescribe el pasado.

## Flujo excepcional sobre `main`

La bitácora es la única excepción autorizada al flujo por pull request. Un commit directo a `main`:

- puede contener una o varias bitácoras fechadas hoy bajo `docs/sessions/`;
- no puede contener ningún otro archivo, ni siquiera documentación auxiliar;
- no puede crear, modificar, renombrar o borrar entradas de otra fecha;
- debe pasar el guard antes del commit y del push.

```text
uv run python scripts/session.py today --activity "Actividad inicial"
uv run python scripts/session.py today --topic harness --activity "Continuar el harness"
uv run python scripts/session.py check docs/sessions/2026-10-12-harness.md
uv run python scripts/session.py guard-publish
```

Durante el día el estado puede permanecer `Abierta`. `Cerrada` indica que no se prevén más agregados ese día, pero no habilita modificarla en fechas posteriores.

## Contenido

Se separan hechos de interpretaciones y se registran actividades, decisiones, validaciones, preguntas abiertas, próximo paso y referencias. No deben incluirse secretos, resultados autoritativos completos ni grandes bloques de logs.

Una decisión durable o con alternativas significativas se registra en `docs/adr/`. La bitácora cuenta qué ocurrió; el ADR conserva el razonamiento; la arquitectura refleja el resultado vigente. Las entradas anteriores al 12 de octubre de 2026 conservan su formato histórico; las posteriores utilizan `daily-v1`.

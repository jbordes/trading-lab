# Entorno de desarrollo de TradingLab 2.0

**Versión:** 0.1

**Estado:** Implementado para la fase de fundación

## Objetivo

El entorno debe producir los mismos resultados en Windows, macOS y Linux sin trasladar lógica entre scripts específicos de cada shell. Python contiene las validaciones y uv administra el intérprete y las futuras dependencias.

## Requisitos

- Git.
- uv 0.13.0 o una versión compatible explícitamente aprobada.
- Acceso a la red únicamente durante la preparación inicial o la actualización deliberada de dependencias.

No es necesario instalar Python manualmente: uv lee `.python-version` y puede descargar la versión fijada por el proyecto.

## Preparación

```text
uv sync --locked
```

Este comando prepara un entorno aislado usando `pyproject.toml`, `.python-version` y `uv.lock`.

## Comandos

Validación rápida durante el trabajo:

```text
uv run python scripts/check.py fast
```

Validación completa antes de solicitar revisión:

```text
uv run python scripts/check.py full
```

La validación rápida comprueba estructura, fronteras de Git/storage, archivos prohibidos, tamaño, UTF-8, conflictos, patrones evidentes de secretos y enlaces Markdown. La completa agrega los tests del harness.

Los checks inspeccionan archivos versionados. Un archivo nuevo debe agregarse al índice antes de la validación final para que forme parte del control completo.

## Bitácora y decisiones

La bitácora representa la jornada en `Europe/Madrid`, no una rama ni una feature. Para iniciar o localizar una entrada del día:

```text
uv run python scripts/session.py today --activity "Actividad inicial"
uv run python scripts/session.py today --topic <tema> --activity "Actividad inicial"
```

Las entradas fechadas nunca se incluyen en una rama de cambio. Se publican directamente en `main` en un commit exclusivo, después de ejecutar `uv run python scripts/session.py guard-publish`. El guard solo admite archivos de `docs/sessions/` cuya fecha sea el día actual y rechaza cualquier otra ruta. Desde el día siguiente, esas entradas son inmutables; las correcciones se agregan a la bitácora corriente.

Las decisiones durables o con alternativas relevantes se registran en `docs/adr/` usando su plantilla. La bitácora enlaza el ADR, pero no duplica todo su razonamiento.

## Flujo de Git

1. Actualizar `main` sin sobrescribir trabajo local.
2. Crear una rama corta `feature/*`, `fix/*`, `docs/*` o `chore/*`.
3. Implementar y ejecutar la validación rápida durante el trabajo.
4. Actualizar los ADR que correspondan; la bitácora diaria se mantiene por el flujo separado de `main`.
5. Ejecutar la validación completa y revisar el diff.
6. Publicar la rama y abrir un pull request.
7. Esperar que CI pase en Windows, macOS y Linux.
8. Realizar el merge manualmente después de la revisión humana.

El workflow de CI tiene permisos de solo lectura y no ejecuta auto-merge. La ruleset de GitHub deberá exigir pull request y el check `Quality` para cambios normales, bloquear force-push y contemplar únicamente la excepción estrecha de bitácoras diarias descrita arriba.

## Evolución prevista

- Agregar validación de schemas cuando se definan los contratos del piloto.
- Agregar un modo de artefactos para hashes, manifests y lineage sin ejecutarlo al inicio de cada sesión.
- Incorporar linters y tests por rutas cuando exista código de aplicación.
- Crear skills únicamente para procedimientos manuales ya estabilizados.

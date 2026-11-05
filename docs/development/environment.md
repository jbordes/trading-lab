# Entorno de desarrollo de TradingLab 2.0

**Versión del documento:** 0.1

**Estado:** entorno del repositorio operativo; el número 0.1 identifica este
documento y no el estado del producto. El Harness actual es 0.2 (2026).

## Rama de integración temporal

Durante el programa `remote-data-platform`, la base estable de trabajo es
`feature/remote-data-platform`, según la excepción temporal descrita en el
[`AGENTS.md`](../../AGENTS.md) y en
[el programa de entrega](remote-data-platform-delivery.md). Las ramas cortas del
programa parten de esa rama y vuelven a ella mediante PR y revisión humana. El
programa regresará a `main` al cierre; no implica que cambios locales estén ya
integrados, tengan CI verde o estén publicados.

La bitácora canónica del programa se mantiene en esa rama, limitada a la entrada
de hoy en `Europe/Madrid`. Las ramas cortas siguen sin incluir sesiones y las
entradas de días anteriores son inmutables. Fuera de esta excepción temporal, la
regla general del repositorio mantiene la bitácora diaria por el flujo de `main`.

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

Validación de un cambio exclusivamente documental:

```text
uv run python scripts/check.py docs
```

Este modo rechaza cambios fuera de `docs/`, `AGENTS.md` y `README.md`. Comprueba
las fronteras del repositorio, seguridad de texto, enlaces, ADR y bitácoras, pero
no ejecuta Ruff ni los tests del producto.

Validación rápida durante el trabajo:

```text
uv run python scripts/check.py fast
```

Validación completa manual, solo cuando el alcance o un diagnóstico la justifique:

```text
uv run python scripts/check.py full
```

La validación rápida comprueba estructura, fronteras de Git/storage, archivos prohibidos, tamaño, UTF-8, conflictos, patrones evidentes de secretos, enlaces Markdown, formato y lint de Python con Ruff. Durante la implementación se ejecutan aparte solo los tests relacionados con el cambio. GitHub Actions agrega todos los tests del harness y del producto mediante `full` y actúa como gate obligatorio del pull request. No se repite localmente por rutina: se reserva para cambios transversales, modificaciones del pipeline, impacto sobre la mayoría de la suite o diagnóstico concreto de CI.

Las reglas para estructurar, probar y proteger código nuevo se encuentran en [Estándares de desarrollo de código](coding-standards.md).

Los checks inspeccionan archivos versionados. Un archivo nuevo debe agregarse al índice antes de la validación final para que forme parte del control completo.

## Bitácora y decisiones

La bitácora representa la jornada en `Europe/Madrid`, no una rama ni una feature. Para iniciar o localizar una entrada del día:

```text
uv run python scripts/session.py today --activity "Actividad inicial"
```

El nombre normal es `YYYY-MM-DD.md` y reúne todos los temas mediante bloques horarios o subtítulos. `--topic <tema>` solo se utiliza excepcionalmente cuando una jornada deba dividirse de forma deliberada; no representa una feature.

Las entradas fechadas no se mezclan con ramas cortas. En el flujo normal, la
entrada de hoy se publica en `main` en un commit exclusivo después de ejecutar
`uv run python scripts/session.py guard-publish`; las entradas de días anteriores
son inmutables. Durante el programa remoto se aplica la excepción de rama y
bitácora descrita arriba y en `AGENTS.md`.

Las decisiones durables o con alternativas relevantes se registran en `docs/adr/` usando su plantilla. La bitácora enlaza el ADR, pero no duplica todo su razonamiento.

## Flujo de Git

1. Actualizar la base estable vigente sin sobrescribir trabajo local (`main` en
   el flujo normal; `feature/remote-data-platform` durante su excepción aprobada).
2. Crear una rama corta `feature/*`, `fix/*`, `docs/*` o `chore/*` desde esa base.
3. Implementar y ejecutar `docs`, `fast` y tests dirigidos según el alcance.
4. Actualizar los ADR que correspondan; la bitácora diaria usa el flujo y la rama
   canónica vigentes descritos arriba.
5. Revisar el diff final y confirmar las validaciones locales proporcionales. Ejecutar `full` local solo si el alcance o un diagnóstico concreto lo requiere.
6. Publicar la rama y abrir un pull request.
7. Esperar que CI ejecute la validación completa y pase en Windows, macOS y Linux.
8. Realizar el merge manualmente después de la revisión humana.

El workflow de CI tiene permisos de solo lectura y no ejecuta auto-merge. La ruleset de GitHub deberá exigir pull request y el check `Quality` para cambios normales, bloquear force-push y contemplar únicamente la excepción estrecha de bitácoras diarias descrita arriba.

## Evolución prevista

- Continuar evolucionando las validaciones de schemas a medida que cambien los
  contratos y sus consumidores.
- Evaluar un modo de artefactos para hashes, manifests y lineage sin ejecutarlo al
  inicio de cada sesión.
- Ajustar linters y pruebas por ruta conforme crezcan los componentes y el costo
  de validación.
- Crear skills únicamente para procedimientos manuales ya estabilizados.

# TradingLab 2.0 — Análisis y diseño del Harness 0.1

**Fecha:** 12 de octubre de 2026

**Estado:** Vigente desde Harness 0.1

**Alcance:** entorno de desarrollo y controles básicos del repositorio

## 1. Contexto

Se analizaron tres documentos procedentes de otro proyecto: una configuración local de Fenix, reglas globales personales y un inventario completo de su harness de Claude Code. El objetivo fue determinar qué prácticas podían reutilizarse sin trasladar supuestos sobre Node.js, Next.js, PostgreSQL, Docker, OCR, macOS o agentes específicos de Fenix.

## 2. Conclusión del análisis

TradingLab necesita un harness propio, pero no una copia del anterior. Sus riesgos principales son diferentes:

- separación entre Git, catálogo y storage pesado;
- trazabilidad mediante IDs, manifests, hashes y lineage;
- entradas externas de SQX, MT5 y Google Drive;
- operación principal en Windows con trabajo ocasional desde macOS o Linux;
- dos VPS separadas y aprobación humana para acciones sensibles;
- proyecto todavía en fase de fundación y piloto.

Por estas razones se adopta un harness pequeño, portable y evolutivo. Se evita introducir gestión paralela de tareas, agentes permanentes, memoria propia, hooks costosos o automatización autónoma antes de demostrar su necesidad.

## 3. Elementos reutilizados y adaptados

- Reglas de simplicidad, aislamiento entre proyectos y seguridad de Git.
- Prohibición de secretos y artefactos operativos dentro del repositorio.
- Comandos rápidos durante el desarrollo y validación completa antes de cerrar.
- Pull requests con revisión y merge humano.
- Automatización determinista en scripts testeables.
- Skills únicamente después de estabilizar el procedimiento manual.

No se reutilizan configuraciones de modelos, sonidos, permisos de una máquina, comandos npm, agentes de Fenix ni instrucciones para desactivar el sandbox.

## 4. Decisiones del Harness 0.1

### Núcleo portable

La lógica se escribe en Python y se ejecuta mediante uv. PowerShell o shell pueden utilizarse como bootstrap, pero no contendrán una segunda implementación de las validaciones.

Se fija Python 3.14 porque es una rama estable con mantenimiento activo en la fecha de esta decisión. Se evita Python 3.15 durante sus primeros días de disponibilidad para no adoptar inmediatamente una versión mayor nueva.

### Validación escalonada

- `fast`: controles baratos adecuados para el ciclo habitual.
- `full`: controles rápidos más tests del harness.
- validación futura de artefactos: ejecución explícita, nunca automática al abrir cada sesión.

No se recorren `_storage/` ni grandes colecciones de resultados en los checks habituales. Un inventario podrá utilizar caché como optimización, pero toda ingestión o frontera de confianza deberá recalcular SHA-256.

### Integración continua

El mismo comando completo corre en Windows, macOS y Linux. CI tiene permisos de lectura y no puede realizar merges ni publicar artefactos operativos.

### Git y aprobación humana

Cada feature se desarrolla en una rama corta y llega a `main` mediante pull request. El merge humano es una política del proyecto; una ruleset de GitHub será el mecanismo recomendado para impedir pushes directos y exigir que CI esté verde.

## 5. Contenido implementado

- `AGENTS.md`: política operativa neutral respecto del agente utilizado.
- `.python-version`, `pyproject.toml` y `uv.lock`: toolchain portable y reproducible.
- `scripts/check.py`: entrada única para validaciones.
- `tests/harness/`: tests de las reglas críticas del harness.
- `.github/workflows/quality.yml`: CI multiplataforma y de solo lectura.
- `.github/pull_request_template.md`: checklist de revisión.
- `.editorconfig`: codificación y finales de línea coherentes.
- `docs/development/environment.md`: preparación y operación diaria.
- `docs/sessions/`: proceso, plantilla, generador y validación de la bitácora.
- `docs/adr/`: convención, plantilla y validación de decisiones durables.
- `.env.example`: contrato seguro de configuración, actualmente sin variables requeridas.
- `docs/development/coding-standards.md`: contrato pragmático de estructura, seguridad y pruebas del código.
- Ruff: formato y lint portable integrado en los checks habituales.

## 6. Cobertura de requisitos de la arquitectura

| Requisito arquitectónico | Mecanismo del Harness 0.1 | Estado |
|---|---|---|
| Fuentes de verdad separadas | Reglas en `AGENTS.md` y fronteras verificadas de Git/storage | Cubierto |
| Historia de trabajo en bitácora | `daily-v1`, generador, validación, fecha Madrid e inmutabilidad histórica | Cubierto |
| Decisiones durables mediante ADR | Plantilla, estados y validador estructural | Cubierto |
| Ramas, PR y revisión humana | Política, plantilla de PR y CI sin auto-merge | Cubierto; falta activar ruleset remota |
| Secretos fuera de Git | `.gitignore`, `.env.example` y detección de patrones evidentes | Cubierto como primera barrera; requiere revisión humana |
| Portabilidad | Python + uv y CI Windows/macOS/Linux | Cubierto |
| Calidad de código | Estándar versionado, Ruff y checklist de revisión | Cubierto como base incremental |
| Criterio de finalización | Check completo, documentación y ADR; bitácora diaria por flujo independiente | Cubierto |
| Schemas y fixtures de dominio | Requiere contratos y archivos reales del piloto | Postergado con disparador explícito |
| Hashes, manifests y lineage | Requiere seleccionar el expediente piloto | Postergado con disparador explícito |
| Backup y restauración | Requiere decidir catálogo y storage autoritativos | Postergado con disparador explícito |
| Observabilidad y tests E2E | Requiere servicios y flujo ejecutable | Postergado con disparador explícito |
| Skills operativas | Requiere repetir y estabilizar primero los procedimientos manuales | Postergado con disparador explícito |

## 7. Decisiones postergadas deliberadamente

- schemas de dominio y fixtures reales, hasta seleccionar la estrategia piloto;
- validación masiva de hashes y manifests;
- linters o frameworks de test adicionales;
- hooks locales obligatorios;
- agentes revisores personalizados;
- skills de importación, migración o cierre de sesión;
- automatización de merge o deployment.

## 8. Criterios de aceptación

El Harness 0.1 queda aceptado cuando:

1. puede prepararse con uv sin una instalación previa de Python;
2. el mismo check completo pasa en Windows, macOS y Linux;
3. detecta secretos evidentes, conflictos, enlaces rotos y archivos prohibidos;
4. impide incorporar accidentalmente storage o ejecutables MT4/MT5;
5. sus reglas críticas tienen tests;
6. existe un pull request revisable y el merge queda bajo control humano.
7. las features no modifican bitácoras diarias, solo las entradas de hoy pueden publicarse directamente en `main` y las decisiones durables quedan enlazadas mediante ADR.

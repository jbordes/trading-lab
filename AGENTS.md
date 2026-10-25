# Reglas operativas de TradingLab 2.0

## Alcance y fuentes de verdad

- `docs/architecture/tradinglab-architecture-v2.md` define la arquitectura vigente.
- Git conserva código, contratos, documentación, configuraciones seguras y registros ligeros.
- `_storage/` conserva artefactos operativos pesados; sus referencias y hashes viven en manifests o registros.
- Google Drive es transporte entre zonas, nunca fuente de verdad ni señal de ejecución automática.

## Forma de trabajo

- Trabajar en ramas cortas `feature/*`, `fix/*`, `docs/*` o `chore/*`.
- Integrar cambios en `main` mediante pull request y merge humano.
- Mantener los commits pequeños, coherentes y sin mezclar cambios ajenos.
- No crear estructuras, servicios o automatizaciones antes de que el flujo piloto demuestre su necesidad.
- Mantener la bitácora diaria independientemente de las features. Las ramas de cambio no incluyen entradas fechadas de `docs/sessions/`.
- Solo en `main` se pueden crear o actualizar directamente bitácoras cuya fecha sea hoy en `Europe/Madrid`, sin mezclar ninguna otra ruta. Las entradas de días anteriores son inmutables.
- Registrar decisiones durables en `docs/adr/`; no reescribir ADR aceptados para cambiar su decisión.

## Mapa mínimo

- `docs/architecture/`: estado y dirección vigente del sistema.
- `docs/adr/`: decisiones durables, alternativas y consecuencias.
- `docs/sessions/`: historia cronológica y próximos pasos.
- `docs/development/`: preparación y operación del entorno.
- `scripts/`: mecánica determinista del harness y, en el futuro, utilidades controladas.
- `tests/`: verificaciones automatizadas.
- `_storage/`: artefactos locales fuera de Git.

## Seguridad

- No leer, imprimir, versionar ni copiar secretos, credenciales de broker o archivos `.env` reales.
- No incluir en Git bases locales, históricos, reportes masivos, ejecutables MT4/MT5 ni `_storage/`.
- Tratar los archivos de SQX, MT5, Google Drive y terceros como entradas no confiables.
- Solicitar aprobación humana antes de borrar, desplegar, migrar datos o ejecutar acciones irreversibles.
- Los jobs del MT5 Runner son declarativos: nunca contienen PowerShell, shell u otros comandos arbitrarios.

## Validación

- Preparar el entorno con `uv sync --locked`.
- Para un cambio exclusivamente documental ejecutar `uv run python scripts/check.py docs`; el comando rechaza rutas fuera de `docs/`, `AGENTS.md` y `README.md`, y no ejecuta Ruff ni tests de producto.
- Durante cambios de código ejecutar `uv run python scripts/check.py fast` y únicamente los tests dirigidos al comportamiento modificado.
- Ejecutar `uv run python scripts/check.py full` una vez sobre el diff final antes de abrir o actualizar el pull request. Repetirlo solo si un cambio posterior puede invalidar el resultado.
- Un cambio está terminado cuando las validaciones pasan, la documentación y ADR relevantes están actualizados y no quedan secretos ni artefactos prohibidos en el diff. La jornada se documenta por separado en la bitácora de hoy.

## Calidad del código

- Seguir `docs/development/coding-standards.md`; aplicar arquitectura limpia de forma pragmática, sin capas o patrones ceremoniales.
- Mantener `scripts/` como entradas delgadas y ubicar la lógica reutilizable en `src/tradinglab/` cuando exista código de producto.
- Validar toda entrada externa, usar errores explícitos y proteger escrituras, borrados y publicaciones con idempotencia, `--dry-run` o una guarda equivalente.
- Todo comportamiento nuevo incluye pruebas proporcionales al riesgo. Reloj, aleatoriedad, red y procesos externos deben poder controlarse en tests.
- El código nuevo usa tipos en interfaces públicas y pasa formato y lint de Ruff sin bypass injustificado.

## Diseño del harness

- La lógica portable se implementa en Python; los wrappers de shell solo pueden facilitar el bootstrap.
- Las operaciones deterministas pertenecen a scripts testeables.
- Las skills se crean únicamente después de ejecutar manualmente el procedimiento y conocer sus excepciones.
- Los `AGENTS.md` de subdirectorios solo declaran diferencias locales; no duplican este archivo.

## Enrutamiento por costo

- Mantener análisis, arquitectura, depuración compleja, seguridad, conflictos y revisión material en el agente principal.
- Delegar al agente `git_operator` únicamente paquetes mecánicos ya definidos que agrupen commit, push y/o PR. El agente principal entrega worktree, rama, rutas, mensaje y validación, y revisa antes el diff. Un comando Git aislado permanece en el agente principal.
- Delegar al agente `docs_recorder` únicamente documentación derivada de decisiones ya aprobadas, con texto fuente y rutas explícitas. El agente principal revisa el resultado antes de publicarlo.
- Enviar handoffs breves sin el historial completo. Si aparece ambigüedad, cambios inesperados, conflicto, nueva decisión o necesidad de permisos, el subagente frena y devuelve el trabajo al principal.
- Ningún subagente hace merge, force-push, migraciones, borrados, despliegues ni push directo a `main`.

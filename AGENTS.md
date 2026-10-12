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
- Crear o actualizar una bitácora `docs/sessions/YYYY-MM-DD-<tema>.md` en cada rama y cerrarla antes del PR.
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
- Durante el trabajo ejecutar `uv run python scripts/check.py fast`.
- Antes de cerrar un cambio ejecutar `uv run python scripts/check.py full`.
- Un cambio está terminado cuando las validaciones pasan, la bitácora está cerrada, la documentación y ADR relevantes están actualizados y no quedan secretos ni artefactos prohibidos en el diff.

## Diseño del harness

- La lógica portable se implementa en Python; los wrappers de shell solo pueden facilitar el bootstrap.
- Las operaciones deterministas pertenecen a scripts testeables.
- Las skills se crean únicamente después de ejecutar manualmente el procedimiento y conocer sus excepciones.
- Los `AGENTS.md` de subdirectorios solo declaran diferencias locales; no duplican este archivo.

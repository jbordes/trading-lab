# TradingLab 2.0

Laboratorio para investigar, preparar, validar e incubar estrategias de trading con trazabilidad y reproducibilidad entre StrategyQuant X y MetaTrader 5.

## Estado

El proyecto se encuentra en fase de fundación y validación de arquitectura. La versión vigente es la Arquitectura 2.4 y el entorno de desarrollo utiliza el Harness 0.2.

## Documentación principal

- [Arquitectura 2.4](docs/architecture/tradinglab-architecture-v2.md)
- [Comparación y cobertura de TradingLab 1.0 frente a 2.3](docs/architecture/architecture-v1-vs-v2.3-coverage.md)
- [Guía de estructura del repositorio](docs/architecture/repository-structure-guide.md)
- [Guía de decisiones de arquitectura](docs/architecture/architecture-decisions-guide.md)
- [Pipeline SQX → MT5 → Incubación](docs/architecture/sqx-mt5-incubation-pipeline.md)
- [Workflow de TradingLab MT5 Runner](docs/architecture/tradinglab-mt5-runner-workflow.md)
- [Análisis y diseño del Harness 0.2](docs/architecture/development-harness-0.2.md)
- [Dashboard local de riesgo](docs/architecture/live-risk-dashboard.md)
- [Entorno de desarrollo](docs/development/environment.md)
- [Estándares de desarrollo de código](docs/development/coding-standards.md)
- [Referencia unificada de APIs](docs/development/api-reference.md)
- [Roadmap del dashboard local de riesgo](docs/development/live-risk-dashboard-roadmap.md)
- [Análisis de UX y diseño en evolución del dashboard](docs/development/dashboard-evolution-ux.md)
- [Guía para acordar métricas de riesgo](docs/development/guia-metricas-para-el-socio.md)
- [Spike de captura MT5](docs/development/mt5-capture-spike.md)
- [Spike de colector de telemetría MT5](docs/development/mt5-telemetry-collector-spike.md)
- [Manual de instalación y operación de los collectors MT5](docs/development/mt5-collector-operations.md)
- [Registros de decisiones](docs/adr/)
- [Bitácora de sesiones](docs/sessions/)

El documento `Trading_Lab_2_0_Arquitectura_Inicial.pdf` se conserva para comparar la propuesta inicial con la arquitectura vigente.

## Principios actuales

- Un monorepo para el laboratorio.
- Un catálogo lógico central para proyectos, estrategias, runs y artefactos.
- Separación entre Git, catálogo y storage.
- Artefactos y ejecuciones identificados mediante manifests y hashes.
- VPS TradingLab y VPS MT5 como zonas de confianza separadas.
- Automatización MT5 mediante paquetes verificables y aprobación local.
- Google Drive como transporte inicial, no como fuente de verdad.

## Próximo hito

Comparar la muestra de posiciones y órdenes del dashboard con el terminal MT5 demo y cerrar con el socio las fórmulas de DDD y Max DD.

## Dashboard local

Probar la interfaz sin conectar un terminal:

```text
uv run python scripts/live_dashboard.py --demo
```

El comando solicita de forma oculta un token humano local para el dashboard. Se
ingresa ese mismo token en `/login`; no se escribe en argumentos ni en Git. El
modo de fuente siempre es explícito: se debe indicar `--demo`, `--telemetry` o la
configuración central con `--central-api-port`, y la aplicación no descubre terminales MT5.
El modo demo usa por defecto `http://127.0.0.1:8765/dashboard`; el piloto central
descrito debajo utiliza el puerto `8775`.

El flujo MT5 central del piloto utiliza collectors de solo lectura en cuentas
demo aprobadas:

```text
EAs -> relay local 8776/8777 -> FastAPI 8781 -> SQLite v1 + v2 (schema 5)
                                            -> dashboard local 8775
```

El dashboard consulta FastAPI, no accede a SQLite por red. Los cuatro puertos
permanecen en loopback. El token humano del dashboard es distinto de los tokens
de lectura de la API, de ingesta central y de los dos tokens locales de los EAs.
No incluyas valores de tokens en comandos, documentación ni Git.

La vista `Trading` permite consultar la actividad en curso. `Performance financiera`
reúne operaciones cerradas, métricas y comparaciones de EAs; `Performance de ejecución`
permite explorar el registro de órdenes y deals de MT5.
La vista `Actividad` presenta el estado de captura e historial separado de la
actualización visual. Los datos históricos conservan tiempos del broker MT5.
Consulta el [manual de instalación y operación de los collectors MT5](docs/development/mt5-collector-operations.md)
para compilar, instalar, configurar fuentes, operar los servicios, revisar logs,
diagnosticar fallos y volver atrás. Para los comandos coordinados de los servicios,
consulta [API central, relay y dashboard](docs/development/central-api-dashboard.md).

El conjunto documentado corresponde al piloto demo. No declara desplegada una
instalación remota ni habilita cuentas reales. La conexión legacy de un dashboard
a un receptor local no representa la topología central vigente del piloto.

## Validación del repositorio

Con [uv](https://docs.astral.sh/uv/) instalado:

```text
uv sync --locked
uv run python scripts/check.py full
```

`full` es el gate que GitHub Actions ejecuta en cada pull request. Durante el
trabajo local se usa `scripts/check.py docs` o `scripts/check.py fast` más los
tests afectados; la suite completa local se reserva para cambios transversales o
diagnósticos concretos.

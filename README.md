# TradingLab 2.0

Laboratorio para investigar, preparar, validar e incubar estrategias de trading con trazabilidad y reproducibilidad entre StrategyQuant X y MetaTrader 5.

## Estado

El proyecto se encuentra en fase de fundación y validación de arquitectura. La versión vigente es la Arquitectura 2.4 y el entorno de desarrollo utiliza el Harness 0.1.

## Documentación principal

- [Arquitectura 2.4](docs/architecture/tradinglab-architecture-v2.md)
- [Comparación y cobertura de TradingLab 1.0 frente a 2.3](docs/architecture/architecture-v1-vs-v2.3-coverage.md)
- [Guía de estructura del repositorio](docs/architecture/repository-structure-guide.md)
- [Guía de decisiones de arquitectura](docs/architecture/architecture-decisions-guide.md)
- [Pipeline SQX → MT5 → Incubación](docs/architecture/sqx-mt5-incubation-pipeline.md)
- [Workflow de TradingLab MT5 Runner](docs/architecture/tradinglab-mt5-runner-workflow.md)
- [Análisis y diseño del Harness 0.1](docs/architecture/development-harness-0.1.md)
- [Dashboard local de riesgo](docs/architecture/live-risk-dashboard.md)
- [Entorno de desarrollo](docs/development/environment.md)
- [Estándares de desarrollo de código](docs/development/coding-standards.md)
- [Roadmap del dashboard local de riesgo](docs/development/live-risk-dashboard-roadmap.md)
- [Análisis de UX y diseño en evolución del dashboard](docs/development/dashboard-evolution-ux.md)
- [Guía para acordar métricas de riesgo](docs/development/guia-metricas-para-el-socio.md)
- [Spike de captura MT5](docs/development/mt5-capture-spike.md)
- [Spike de colector de telemetría MT5](docs/development/mt5-telemetry-collector-spike.md)
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

Con el extra MT5 instalado y un terminal demo autenticado:

```text
uv sync --locked --extra mt5
uv run python scripts/live_dashboard.py
```

La aplicación queda disponible únicamente en `http://127.0.0.1:8765`.
La vista `Operaciones` permite filtrar posiciones abiertas y órdenes pendientes por Magic Number. Para cuentas reales se utilizará una instancia separada con acceso de inversor.
La vista `Actividad` muestra deals y órdenes históricas recientes junto con duración, éxitos y fallos de la captura.

El colector MQL5 push se mantiene como spike independiente y no se instala en una
terminal sin revisión y aprobación humana. Su receptor local puede iniciarse con:

```text
uv run python scripts/telemetry_receiver.py
```

Con el mismo `TRADINGLAB_TELEMETRY_TOKEN` disponible en ambos procesos, otra
terminal puede mostrar la última muestra push validada:

```text
uv run python scripts/live_dashboard.py --telemetry --telemetry-source demo-terminal-01
```

El adaptador solo consulta `http://127.0.0.1:8766`, no entrega el token al
navegador y marca la vista como degradada si pasan 30 segundos sin una muestra
nueva. El `SourceId` debe coincidir con el configurado en el EA.

## Validación del repositorio

Con [uv](https://docs.astral.sh/uv/) instalado:

```text
uv sync --locked
uv run python scripts/check.py full
```

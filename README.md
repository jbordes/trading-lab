# TradingLab 2.0

Laboratorio para investigar, preparar, validar e incubar estrategias de trading con trazabilidad y reproducibilidad entre StrategyQuant X y MetaTrader 5.

## Estado

El proyecto se encuentra en fase de diseño y validación de arquitectura. La versión vigente es la Arquitectura 2.2.

## Documentación principal

- [Arquitectura 2.2](docs/architecture/tradinglab-architecture-v2.md)
- [Guía de estructura del repositorio](docs/architecture/repository-structure-guide.md)
- [Guía de decisiones de arquitectura](docs/architecture/architecture-decisions-guide.md)
- [Pipeline SQX → MT5 → Incubación](docs/architecture/sqx-mt5-incubation-pipeline.md)
- [Workflow de TradingLab MT5 Runner](docs/architecture/tradinglab-mt5-runner-workflow.md)
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

Validar la Arquitectura 2.2 con los socios y comenzar la fase de fundación: estructura mínima, reglas del repositorio, contratos iniciales y primer flujo piloto SQX–MT5.

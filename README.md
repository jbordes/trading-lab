# TradingLab 2.0

Laboratorio para investigar, preparar, validar e incubar estrategias de trading con trazabilidad y reproducibilidad entre StrategyQuant X y MetaTrader 5.

## Estado

**TradingLab SetUp** es el instalador predeterminado para Windows. Incluye
captura multicuenta, relay durable, API y dashboard sobre SQLite esquema 10.
Se puede instalar en un equipo o distribuir los componentes entre hosts.
La instalación limpia en demo con Activity 0.9.0 y Telemetry 0.3.4 confirmó
la carga local, la cobertura histórica y las entregas al relay. La validación
manual entre servidores y la comparación financiera con MT5 siguen pendientes.

## Documentación vigente

- [Arquitectura 2.4](docs/architecture/tradinglab-architecture-v2.md)
- [Diseño del dashboard y captura MT5](docs/architecture/live-risk-dashboard.md)
- [Análisis y diseño del Harness 0.2](docs/architecture/development-harness-0.2.md)
- [Entorno de desarrollo](docs/development/environment.md)
- [Instalación y operación con TradingLab SetUp](docs/development/tradinglab-setup.md)
- [Estándares de desarrollo de código](docs/development/coding-standards.md)
- [Referencia unificada de APIs](docs/development/api-reference.md)
- [Manual de instalación y operación de los collectors MT5](docs/development/mt5-collector-operations.md)
- [Preparación de un host remoto para la API central](docs/development/remote-host-setup.md)
- [Mantenimiento diario automático en Windows, Linux y macOS](docs/development/automatic-maintenance.md)
- [Arranque conjunto de API, relay y dashboard](docs/development/central-api-dashboard.md)
- [Operación de la API central](docs/development/central-api-operation.md)
- [Cutover al contrato descriptivo de la API central](docs/development/descriptive-api-cutover.md)
- [Base SQLite central](docs/development/central-sqlite.md)
- [Progresión histórica de cuenta: balance, PnL y equity observada](docs/development/account-progression-history.md)
- [Relay con outbox durable](docs/development/durable-telemetry-relay.md)

## Planes y definiciones pendientes

- [Programa de plataforma de datos remota](docs/development/remote-data-platform-delivery.md)
- [Roadmap del dashboard local de riesgo](docs/development/live-risk-dashboard-roadmap.md)
- [Plan de captura autónoma e historial](docs/development/autonomous-capture-history-plan.md)
- [Revisión de diseño Python](docs/development/python-design-review-plan.md)
- [Plan de credenciales y permisos](docs/development/credential-management-plan.md)
- [Guía para acordar métricas de riesgo con el socio](docs/development/guia-metricas-para-el-socio.md)
- [Pipeline SQX → MT5 → Incubación](docs/architecture/sqx-mt5-incubation-pipeline.md)
- [Workflow de TradingLab MT5 Runner](docs/architecture/tradinglab-mt5-runner-workflow.md)

## Antecedentes y consulta

- [Comparación y cobertura de TradingLab 1.0 frente a 2.3](docs/architecture/architecture-v1-vs-v2.3-coverage.md)
- [Análisis de UX y diseño en evolución del dashboard](docs/development/dashboard-evolution-ux.md)
- [Spike de captura MT5](docs/development/mt5-capture-spike.md)
- [Spike de colector de telemetría MT5](docs/development/mt5-telemetry-collector-spike.md)
- [Guía de estructura del repositorio](docs/architecture/repository-structure-guide.md)
- [Guía de decisiones de arquitectura](docs/architecture/architecture-decisions-guide.md)
- [Registros de decisiones](docs/adr/)
- [Bitácora de sesiones](docs/sessions/)

El documento `Trading_Lab_2_0_Arquitectura_Inicial.pdf` se conserva para comparar la propuesta inicial con la arquitectura vigente.

## Principios actuales

Los principios de arquitectura describen la dirección del laboratorio y no implican
que cada componente ya esté desplegado: monorepo, separación entre Git, catálogo y
storage, artefactos con manifests/hashes, zonas de confianza diferenciadas,
aprobación local para automatización MT5 y Google Drive como transporte, nunca
fuente de verdad.

## Próximo hito

Revisar e integrar el PR en `feature/remote-data-platform`. Las
[pruebas manuales y condiciones para integrar en main](docs/development/remote-data-platform-delivery.md)
quedan registradas en el programa.

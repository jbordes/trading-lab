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
- [Operación supervisada del collector MT5](docs/development/mt5-collector-operations.md)
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

El comando solicita de forma oculta un token local para el dashboard. Luego se
ingresa ese mismo valor en `/login`; no se escribe en argumentos ni en Git.

El modo de fuente siempre es explícito: ejecutar el comando sin `--demo` o
`--telemetry` se rechaza y nunca intenta descubrir una terminal MT5.

La fuente MT5 operativa es el collector MQL5. Con el receptor local iniciado, el
mismo token disponible fuera de Git y un `SourceId` configurado en el EA:

```text
uv run python scripts/telemetry_receiver.py
uv run python scripts/live_dashboard.py --telemetry --telemetry-source demo-terminal-01 --broker-utc-offset-minutes 120
```

La aplicación queda disponible únicamente en `http://127.0.0.1:8765`: `/` es la
página del proyecto, `/login` crea una sesión local y `/dashboard` es el panel
protegido de la cuenta, con tema claro y oscuro. El token humano debe ser distinto
del token de telemetría configurado en el EA. La vista `Trading` reúne `En curso`,
`Operaciones cerradas` y `Registro MT5`: permite analizar ciclos completos junto
a sus métricas y explorar órdenes, deals y actividad vigente sin mezclarlos en el
cálculo. Para cuentas
reales se utilizará una identidad separada con acceso de inversor.
El offset del ejemplo (`120`, UTC+02:00) es una configuración explícita de la
fuente: debe ajustarse al reloj vigente del broker y nunca se deduce de la VPS.
La vista `Actividad` muestra el estado de la fuente (salud del receptor local:
aceptados, duplicados, secuencias faltantes, retenidos e historial) separado de
la actualización de la vista. La hora del historial se presenta según el
timestamp de MT5 y su escala todavía debe validarse con el socio.

El adaptador solo consulta `http://127.0.0.1:8766`, no entrega el token al
navegador y marca la vista como degradada si pasan 30 segundos sin una muestra
nueva. El `SourceId` debe coincidir con el configurado en el EA. La API Python se
reserva para diagnóstico de una sola terminal por proceso, siempre con ruta e
identidad explícitas; no es la fuente multterminal del dashboard.

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

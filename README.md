# TradingLab 2.0

Laboratorio para investigar, preparar, validar e incubar estrategias de trading con trazabilidad y reproducibilidad entre StrategyQuant X y MetaTrader 5.

## Estado

El piloto local MT5 está operativo en demo con Telemetry `0.2.1` y Activity
`activity-0.7.1`, relay durable, API central y dashboard. No está desplegado en la
Mac ni en producción, no usa enlace privado remoto y no habilita cuentas reales.
La implementación local requiere revisión humana y el gate de CI antes de
considerarse integrada. La dirección de arquitectura vigente es 2.4; el entorno
de desarrollo sigue el Harness 0.2.

## Documentación vigente

- [Arquitectura 2.4](docs/architecture/tradinglab-architecture-v2.md)
- [Diseño del dashboard y captura MT5](docs/architecture/live-risk-dashboard.md)
- [Análisis y diseño del Harness 0.2](docs/architecture/development-harness-0.2.md)
- [Entorno de desarrollo](docs/development/environment.md)
- [Estándares de desarrollo de código](docs/development/coding-standards.md)
- [Referencia unificada de APIs](docs/development/api-reference.md)
- [Manual de instalación y operación de los collectors MT5](docs/development/mt5-collector-operations.md)
- [Arranque conjunto de API, relay y dashboard](docs/development/central-api-dashboard.md)
- [Operación de la API central](docs/development/central-api-operation.md)
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

Completar las validaciones operativas pendientes de 401/403, desconexión del broker
y carga, y preparar el piloto remoto en la Mac con conectividad privada y gestión
de credenciales. Las fórmulas financieras existentes siguen sujetas a revisión
con el socio; las métricas de riesgo y ejecución aún requieren definición.

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
```

Elegir el check según el alcance (no ejecutar ambos por rutina):

```text
uv run python scripts/check.py docs
```

Para cambios de código:

```text
uv run python scripts/check.py fast
```

`docs` valida cambios documentales; `fast` es el check local habitual para código,
junto a las pruebas dirigidas. `full` es el gate completo de GitHub Actions y se
ejecuta localmente solo por un diagnóstico concreto o un cambio transversal que
lo justifique, no como rutina.

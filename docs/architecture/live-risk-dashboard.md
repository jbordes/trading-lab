# Dashboard local de riesgo — Arquitectura del piloto

**Fecha:** 2026-10-14

**Estado:** vigente para el piloto

**Decisión:** [ADR-0002](../adr/0002-local-live-risk-dashboard.md)

## Objetivo

Observar en `localhost`, con pocos segundos de demora, información de cuentas de trading obtenida mediante fuentes de solo lectura. El piloto valida primero MT5 y después incorporará StocksTrader sin convertir ninguna API externa en el modelo de la interfaz.

El Excel deja de ser el producto prioritario. Podrá reaparecer como exportación derivada si existe una necesidad concreta.

## Flujo inicial

```text
Terminal MT5
    |
    | account_info / positions_get / orders_get
    v
Mt5SnapshotSource -- snapshot mínimo --> buffer acotado en memoria
                                            |
                                            v
                                  HTTP solo 127.0.0.1
                                            |
                                            v
                                  dashboard sin build
```

El navegador consulta el estado local cada dos segundos. La fuente lee MT5 cada cinco segundos por defecto. Ambos intervalos son independientes y el intervalo de captura es configurable.

## Contrato mínimo del snapshot

La primera frontera compartida contiene únicamente:

- fuente e instante UTC de observación;
- referencia de cuenta enmascarada, servidor y moneda;
- balance, equity y beneficio flotante;
- margen, margen libre y nivel de margen;
- cantidad de posiciones abiertas y órdenes activas.

Esto no constituye un modelo canónico completo. Evita que la pantalla dependa de estructuras específicas de MT5 y ofrece el mínimo punto de extensión para StocksTrader. Los payloads operativos completos y la identidad por bot se incorporarán solo cuando una métrica aprobada los necesite.

## Fuentes

### MT5

El adaptador Python es específico de Windows y se conecta al terminal autorizado. Su interfaz pública no incluye `order_send` ni equivalentes. Cada lectura cierra la conexión mediante `shutdown()` aun ante errores. Para una barrera efectiva del lado de la plataforma se usará una contraseña de inversor cuando el broker la admita.

El diagnóstico inmutable ya implementado se conserva para inventario, reconciliación y evidencia; la vista en vivo no lo reemplaza.

### StocksTrader

Será un adaptador REST separado para cuentas de esa plataforma. No se asumirá que cubre cuentas MT5 de RoboForex ni que ofrece WebSocket. El colector propio permitirá únicamente llamadas de lectura, mantendrá el token fuera del navegador y se probará primero con una cuenta demo.

Antes de conectar una cuenta real se confirmará si StocksTrader ofrece scopes read-only. Una restricción de métodos en nuestro código reduce accidentes, pero no neutraliza un token robado que conserve permisos de trading.

## Métricas acordadas

El documento aportado por el socio separa dos grupos:

1. Control operativo: Daily Drawdown (DDD) y Maximum Drawdown total.
2. Análisis de riesgo: VaR, volatilidad, covarianza, varianza o volatilidad del portfolio, Maximum Drawdown histórico y Sharpe.

Ninguna fórmula se implementará desde ejemplos genéricos. DDD y Max DD requieren primero reglas exactas sobre referencia, equity o balance, reinicio diario, zona horaria, trailing, depósitos y retiros. El segundo grupo requiere definir frecuencia y ventana de retornos, pesos, confianza, horizonte, tasa libre de riesgo y scopes.

El piloto captura desde ahora las observaciones directas disponibles, pero no presenta como válida una métrica cuyo contrato siga abierto.

## Estado y persistencia

- El incremento inicial conserva un buffer limitado en memoria.
- Un reinicio pierde esa ventana visual y no se considera pérdida de evidencia autoritativa.
- El diagnóstico MT5 puede seguir generando evidencia inmutable bajo `_storage/`.
- Cuando las métricas históricas tengan contrato se evaluará una SQLite append-only mínima.
- PostgreSQL y TimescaleDB no forman parte del piloto; requieren evidencia de concurrencia, volumen o centralización.

## Presentación

La primera pantalla usa HTML, CSS, JavaScript y SVG servidos por la biblioteca estándar de Python. No descarga scripts de terceros ni necesita Node. Muestra valores directos y una curva reciente de balance/equity.

Apache ECharts queda seleccionado como candidato para la etapa que incluya histogramas de VaR, matrices de covarianza y gráficos combinados. Se incorporará como dependencia fijada y local solo cuando esas visualizaciones estén aprobadas.

## Seguridad y límites

- Bind fijo a `127.0.0.1`; no acepta una dirección pública por configuración.
- No recibe credenciales por argumentos ni las entrega al navegador.
- Cuenta mostrada de forma enmascarada.
- Endpoints HTTP de lectura; `POST` se rechaza.
- Content Security Policy sin scripts remotos.
- Sin ejecución de órdenes, cambios de posiciones ni automatización de trading.
- La cuenta demo es el único entorno autorizado hasta revisar credenciales de solo lectura y exposición de red.

## Criterios de aceptación del incremento

1. Modo demo usable sin MT5 ni secretos.
2. Modo MT5 consulta cuenta, posiciones y órdenes mediante la frontera read-only.
3. La aplicación solo escucha en loopback.
4. Balance, equity, flotante, margen y conteos se actualizan sin recargar la página.
5. Un fallo conserva la última muestra válida y se muestra como estado degradado.
6. Las validaciones automatizadas cubren fuente, servicio y frontera HTTP.

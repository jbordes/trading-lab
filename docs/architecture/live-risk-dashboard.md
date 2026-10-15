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
    | history_deals_get / history_orders_get
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
- cantidad de posiciones abiertas y órdenes activas;
- muestra operativa actual de posiciones y órdenes, con ticket y Magic Number
  representados como texto para conservar identificadores de 64 bits;
- símbolo, tipo, volumen, precios, SL/TP, resultado flotante, hora y comentario de
  cada operación disponible;
- actividad reciente normalizada desde deals y órdenes históricas;
- estado de captura con intentos, éxitos, fallos consecutivos, duración y último
  instante correcto.

Esto no constituye un modelo canónico completo. Es una proyección de lectura para
la pantalla, no una copia del payload completo de MT5. El detalle operativo vive
solo en la última muestra; el historial acotado conserva valores de cuenta sin
repetir todas las operaciones en cada punto.

## Actividad reciente y estado de captura

Al iniciar, la fuente recupera hasta 24 horas de deals y órdenes históricas. Las
lecturas posteriores parten dos minutos antes del último cursor observado para
tolerar llegadas tardías y deduplican por tipo de registro y ticket. Se retienen
como máximo 200 eventos en memoria. Cada cinco minutos se reconcilia nuevamente
la ventana completa para no depender de semánticas temporales no documentadas de
las órdenes históricas. Un reinicio también reconstruye la ventana desde MT5; no
se crea todavía una base histórica propia.

El servicio mide cada intento con un reloj monotónico y publica conteos de éxito
y fallo, fallos consecutivos, duración de la última captura, máximo observado y
último instante correcto. Estas medidas describen la salud técnica de la captura;
no son métricas de trading.

## Fuentes

### MT5

El adaptador Python es específico de Windows y se conecta al terminal autorizado. Su interfaz pública no incluye `order_send` ni equivalentes. Cada lectura cierra la conexión mediante `shutdown()` aun ante errores. Para una barrera efectiva del lado de la plataforma se usará una contraseña de inversor cuando el broker la admita.

El diagnóstico inmutable ya implementado se conserva para inventario, reconciliación y evidencia; la vista en vivo no lo reemplaza.

El [spike de telemetría push](../development/mt5-telemetry-collector-spike.md)
evalúa un segundo adaptador para terminales ubicados en otra VPS. Su receptor es
un proceso loopback separado y no modifica la frontera HTTP read-only del
dashboard. Solo una comparación contra la captura Python podrá justificar una
topología remota posterior.

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

La aplicación usa HTML, CSS, JavaScript y SVG servidos por la biblioteca estándar
de Python. No descarga scripts de terceros ni necesita Node. La vista Resumen
muestra valores directos y una curva reciente de balance/equity. La vista
Operaciones lista posiciones abiertas y órdenes pendientes y permite filtrar por
Magic Number sin recargar la página. La vista Actividad muestra la salud de la
captura y la ventana móvil de deals y órdenes históricas con filtros por tipo y
Magic Number.

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
7. La muestra actual distingue posiciones y órdenes y preserva tickets y Magic
   Numbers sin pérdida de precisión.
8. El filtro por Magic Number funciona en el navegador y no envía consultas ni
   acciones al terminal.
9. La actividad reciente se actualiza mediante una ventana incremental solapada,
   se reconcilia periódicamente, se deduplica y permanece acotada en memoria.
10. El estado de captura hace visibles duración, último éxito y fallos sin ocultar
    la última muestra válida.

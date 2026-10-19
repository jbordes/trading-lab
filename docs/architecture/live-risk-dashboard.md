# Dashboard local de riesgo — Arquitectura del piloto

**Fecha:** 2026-10-14

**Estado:** vigente para el piloto

**Decisiones:** [ADR-0002](../adr/0002-local-live-risk-dashboard.md) y
[ADR-0004](../adr/0004-mt5-collector-primary-source.md)

## Objetivo

Observar en `localhost`, con pocos segundos de demora, información de cuentas de trading obtenida mediante fuentes de solo lectura. El piloto valida primero MT5 y después incorporará StocksTrader sin convertir ninguna API externa en el modelo de la interfaz.

El Excel deja de ser el producto prioritario. Podrá reaparecer como exportación derivada si existe una necesidad concreta.

## Flujo inicial

```text
Terminal MT5 + collector MQL5
    |
    | snapshot identificado + ventana reciente de deals
    v
receptor autenticado en 127.0.0.1
    |
    | último snapshot validado del source_id esperado
    v
TelemetrySnapshotSource --> buffer acotado en memoria
                                  |
                                  v
                        HTTP solo 127.0.0.1
                                  |
                                  v
                        dashboard sin build
```

El navegador consulta el estado local cada cinco segundos por defecto. El collector
captura MT5 también cada cinco segundos por defecto y el dashboard consulta el
receptor de forma independiente. Los intervalos son configurables y no prometen
tiempo real estricto.

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
- estado y ventana acotada de deals recientes; su proyección en la UI queda
  pendiente de validar la escala horaria del servidor;
- estado de captura con intentos, éxitos, fallos consecutivos, duración y último
  instante correcto.

Esto no constituye un modelo canónico completo. Es una proyección de lectura para
la pantalla, no una copia del payload completo de MT5. El detalle operativo vive
solo en la última muestra; el historial acotado conserva valores de cuenta sin
repetir todas las operaciones en cada punto.

## Actividad reciente y estado de captura

En cada captura el collector relee una ventana completa de deals del servidor MT5;
por defecto cubre una hora y como máximo 200 filas. Informa de forma explícita si
la ventana está completa, truncada o falló. El receptor reemplaza la vista previa
por la última ventana validada y no crea todavía una base histórica propia. Los
deals aún no se muestran en la UI hasta validar la escala horaria del servidor.

El servicio mide cada intento con un reloj monotónico y publica conteos de éxito
y fallo, fallos consecutivos, duración de la última captura, máximo observado y
último instante correcto. Estas medidas describen la salud técnica de la captura;
no son métricas de trading.

## Fuentes

### MT5

El [collector de telemetría](../development/mt5-telemetry-collector-spike.md) es la
fuente MT5 operativa primaria. Se ejecuta dentro de cada terminal, no contiene
funciones de trading y valida la cuenta y servidor aprobados antes de capturar o
enviar. Un `source_id` representa una sola identidad y el adaptador del dashboard
rechaza cualquier fuente distinta de la esperada.

La API Python queda reservada para diagnóstico y reconciliación de una terminal
por proceso. Debe recibir la ruta explícita y verificar ejecutable, carpeta de
datos, cuenta y servidor; `initialize()` sin ruta no es una fuente autorizada. No
se implementará un supervisor Python multterminal mientras el collector cubra el
flujo operativo. Para una barrera efectiva en cuentas reales se usará acceso de
inversor cuando el broker lo admita.

El collector incorpora una ventana móvil de ejecuciones (`deals`) para recuperar
actividad entre muestras: una hora y hasta 200 filas por defecto, con estados
explícitos completo/truncado/error. La vista recibida se reemplaza al reconciliar,
no se acumulan solapamientos. Es memoria temporal, sin emparejar trades ni
alimentar todavía la UI; no reemplaza una futura persistencia durable. Los tiempos
de ejecución conservan la escala del servidor
MT5 hasta validar su conversión.

La primera integración visible conserva receptor y dashboard como procesos
separados. El receptor expone la última muestra de una fuente mediante
`GET /v1/snapshot?source_id=<id>`, autenticado y limitado a loopback. Cada consulta
exige exactamente un identificador válido y los mensajes de otras fuentes no
pueden desplazar su resultado. Un adaptador del lado servidor del dashboard vuelve
a validar el contrato y el `source_id` esperado, y degrada la vista cuando la
muestra supera la antigüedad configurada.
El token no llega al navegador. Balance, equity y operaciones actuales se
proyectan en la interfaz; los deals y los timestamps operativos quedan fuera de
esta integración hasta validar la zona horaria del servidor MT5.

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
de Python. No descarga scripts de terceros ni necesita Node. `/` presenta el
proyecto y ofrece una entrada al panel; `/dashboard` es el espacio de trabajo
de la cuenta, con Resumen, Operaciones y Actividad. Ambas páginas comparten un tema claro y otro oscuro con tokens
`light-dark()`; la elección manual se persiste en `localStorage` y sin elección se
sigue la preferencia del sistema, sin flash al recargar.

Solo el panel muestra la navegación de sus secciones: barra lateral en escritorio
y barra inferior en pantallas estrechas. La portada tiene encabezado propio, sin
accesos directos a vistas internas. Ambas páginas comparten el logo provisto por
el proyecto. Esta organización prepara el uso móvil, pero no implica una app
instalable ni crea destinos para funciones aún no implementadas. El login con
token previsto requerirá proteger en el servidor `/dashboard` y las rutas de
datos; la separación visual actual no es autenticación.

El panel de la cuenta tiene tres vistas. Resumen muestra el equity como cifra
principal neutral, el resultado abierto con semántica de signo y color, balance y
margen libre secundarios, una curva reciente de balance/equity y una franja de
origen. La curva respeta los tiempos observados y deja huecos cuando se interrumpe
la captura. Operaciones lista posiciones abiertas y órdenes pendientes, muestra
el Magic Number sin abrir el detalle y filtra por Magic y tipo desde una barra
encima de los resultados. El selector enumera los Magic disponibles, conserva
como texto los identificadores y hace explícito un bot filtrado sin operaciones.
En móvil la tabla adopta jerarquía de tarjeta, sin scroll interno; los nodos se
actualizan por tipo/ticket conservando detalle y foco. Los filtros se persisten por fuente y los
timestamps no validados se muestran como "No informada". Actividad antepone una
conclusión comprensible y mantiene en un diagnóstico desplegable la salud global
del receptor, la actualización de la vista y sus contadores técnicos. La ventana
de deals recibida por telemetría se incorporará después de validar la escala
horaria del servidor.

El modo simulado se identifica en las tres vistas. La carga inicial, ausencia de
operaciones, filtros sin resultados y desconexión son estados distintos. La edad
de la muestra afecta al indicador de conexión y al resumen de salud; el reloj
visual no genera anuncios continuos para lectores de pantalla. Las métricas de
riesgo pendientes se explican en un desplegable, sin competir con los datos actuales.

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
2. Modo MT5 recibe cuenta, posiciones y órdenes desde el collector read-only de
   la terminal y exige el `source_id` configurado.
3. La aplicación solo escucha en loopback.
4. Balance, equity, flotante, margen y conteos se actualizan sin recargar la página.
5. Un fallo conserva la última muestra válida y se muestra como estado degradado.
6. Las validaciones automatizadas cubren fuente, servicio y frontera HTTP.
7. La muestra actual distingue posiciones y órdenes y preserva tickets y Magic
   Numbers sin pérdida de precisión.
8. El filtro por Magic Number funciona en el navegador y no envía consultas ni
   acciones al terminal.
9. El collector reconcilia una ventana reciente completa, informa truncamiento o
   error y el receptor conserva únicamente una vista acotada en memoria.
10. El estado de captura hace visibles duración, último éxito y fallos sin ocultar
    la última muestra válida.

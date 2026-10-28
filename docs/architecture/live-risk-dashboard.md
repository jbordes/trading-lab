# Dashboard local de riesgo — Arquitectura del piloto

**Fecha:** 2026-10-14

**Estado:** vigente para el piloto

**Decisiones:** [ADR-0002](../adr/0002-local-live-risk-dashboard.md),
[ADR-0004](../adr/0004-mt5-collector-primary-source.md) y
[ADR-0010](../adr/0010-separate-dashboard-authentication.md)

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
                       login con token humano
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
- estado y ventana acotada de deals recientes, conservando la referencia temporal
  del broker y el instante convertible a la zona local del usuario;
- estado de captura con intentos, éxitos, fallos consecutivos, duración y último
  instante correcto.

Esto no constituye un modelo canónico completo. Es una proyección de lectura para
la pantalla, no una copia del payload completo de MT5. El detalle operativo vive
solo en la última muestra; el historial acotado conserva valores de cuenta sin
repetir todas las operaciones en cada punto.

## Actividad reciente y estado de captura

En cada captura el collector relee una ventana completa de deals del servidor MT5;
por defecto cubre una hora y como máximo 200 filas. Informa de forma explícita si
la ventana está completa, truncada o falló. El receptor v1 reemplaza la vista
previa por la última ventana validada; el collector de actividad v2 conserva el
historial durable de deals y órdenes que consume `Trading`.

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
alimentar la persistencia durable v2. Los tiempos de ejecución conservan la
referencia del servidor MT5. La conversión a hora local solo se realiza cuando el
instante y la zona u offset del broker son explícitos; no se adivina una zona a
partir del reloj de la VPS.

La primera integración visible conserva receptor y dashboard como procesos
separados. El receptor expone la última muestra de una fuente mediante
`GET /v1/snapshot?source_id=<id>`, autenticado y limitado a loopback. Cada consulta
exige exactamente un identificador válido y los mensajes de otras fuentes no
pueden desplazar su resultado. Un adaptador del lado servidor del dashboard vuelve
a validar el contrato y el `source_id` esperado, y degrada la vista cuando la
muestra supera la antigüedad configurada.
El token no llega al navegador. Balance, equity y operaciones actuales se
proyectan en la interfaz; la actividad durable se integra mediante telemetría v2.

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

- V1 conserva un buffer limitado en memoria para el estado vivo y la curva
  reciente; perderlo tras un reinicio no elimina actividad histórica durable.
- V2 persiste en SQLite mensajes, cobertura, deals, órdenes y ciclos de posición.
  SQLite es la fuente de verdad local del historial piloto.
- El diagnóstico MT5 puede seguir generando evidencia inmutable bajo `_storage/`.
- Las tablas derivadas adicionales y una caché solo se incorporarán ante consultas
  medidas; no se mantendrá una proyección histórica ilimitada en memoria.
- PostgreSQL y TimescaleDB no forman parte del piloto; requieren evidencia de
  concurrencia, volumen o centralización.

## Presentación

La aplicación usa HTML, CSS, JavaScript y SVG servidos por la biblioteca estándar
de Python. No descarga scripts de terceros ni necesita Node. `/` presenta el
proyecto y ofrece una entrada al panel; `/dashboard` es el espacio de trabajo
de la cuenta, con Resumen, Trading y Actividad. Ambas páginas comparten un tema claro y otro oscuro con tokens
`light-dark()`; la elección manual se persiste en `localStorage` y sin elección se
sigue la preferencia del sistema, sin flash al recargar. La portada permanece
pública; el panel y su API exigen una sesión local obtenida con un token humano
distinto del secreto del EA. El navegador conserva únicamente una cookie opaca,
temporal y `HttpOnly`; el token de telemetría no sale del backend.

Solo el panel muestra la navegación de sus secciones: barra lateral en escritorio
y barra inferior en pantallas estrechas. La portada tiene encabezado propio, sin
accesos directos a vistas internas. Ambas páginas comparten el logo provisto por
el proyecto. Esta organización prepara el uso móvil, pero no implica una app
instalable ni crea destinos para funciones aún no implementadas. El acceso
continúa restringido a loopback. Esta sesión no sustituye TLS ni una identidad
multiusuario y no habilita publicar el dashboard en la LAN o Internet.

El panel de la cuenta tiene tres vistas. Resumen muestra el equity como cifra
principal neutral, el resultado abierto con semántica de signo y color, balance y
margen libre secundarios, una curva reciente de balance/equity y una franja de
origen. La curva respeta los tiempos observados y deja huecos cuando se interrumpe
la captura. Trading agrupa `En curso`, `Operaciones cerradas` y `Registro MT5`. En curso lista
posiciones abiertas y órdenes pendientes, muestra
el Magic Number sin abrir el detalle y filtra por Magic y tipo desde una barra
encima de los resultados. El selector enumera los Magic disponibles, conserva
como texto los identificadores y hace explícito un bot filtrado sin operaciones.
En móvil la tabla adopta jerarquía de tarjeta, sin scroll interno; los nodos se
actualizan por tipo/ticket conservando detalle y foco. Los filtros se persisten por fuente y los
timestamps que no puedan convertirse de forma inequívoca se muestran como "No
informada". Operaciones cerradas
consulta ciclos reconstruidos por período y Magic; sus métricas `position-cycle-v1`
solo incluyen ciclos elegibles. Registro MT5 combina ejecuciones, órdenes y el
snapshot en curso para diagnóstico, sin alimentar métricas. Actividad antepone una
conclusión comprensible y mantiene en un diagnóstico desplegable la salud global
del receptor, la actualización de la vista y sus contadores técnicos.

Toda fecha operativa mostrará de forma compacta ambas referencias: `Broker` y
`Local`. Cada una incluye fecha y hora porque una conversión puede cambiar el día.
En escritorio pueden compartir una celda y en móvil se apilan dentro del mismo
bloque, sin tarjetas ni columnas adicionales. El formato base será, por ejemplo,
`Broker 27/10 23:45` y `Local 28/10 00:45`; el detalle podrá informar zona u
offset. La hora local proviene del navegador y la del broker de una referencia
explícita de la fuente, nunca de una suposición por máquina.

En el piloto esa referencia es un offset UTC configurable en minutos, necesario
para convertir la hora local. Sin configurarlo se informa que falta el offset.
Es suficiente para la observación vigente, pero no modela cambios
históricos de horario de verano: antes de analizar períodos que atraviesen esos
cambios se deberá adoptar una regla temporal versionada del broker.

Junto a los filtros históricos se presenta la cobertura durable informada por
SQLite. `Datos completos` exige cobertura continua del período y ausencia de
lotes incompletos; cualquier otra situación se rotula `Datos parciales` y también
califica como parcial a las métricas calculadas sobre ese rango.

Esta decisión resuelve la presentación, no el comienzo del día para DDD u otras
métricas: cada contrato deberá declarar su zona de corte.

Cuando el total informado por MT5 supera el detalle incluido por el collector,
Operaciones muestra la cantidad recibida sobre el total y advierte que los
filtros solo abarcan esas filas. Una lista parcial nunca se presenta como si fuera
el estado completo de la cuenta.

El modo simulado se identifica en las tres vistas. La carga inicial, ausencia de
operaciones, filtros sin resultados y desconexión son estados distintos. La edad
de la muestra afecta al indicador de conexión y al resumen de salud; el reloj
visual no genera anuncios continuos para lectores de pantalla. Las métricas de
riesgo pendientes se explican en un desplegable, sin competir con los datos actuales.

Las actualizaciones incrementales comparan instantes ISO normalizados, incluida
su fracción de segundo y zona horaria. Un cursor `since` inválido se rechaza y no
se interpreta mediante orden alfabético ni como una lectura completa.

La performance primaria de un EA se consulta por cuenta y Magic propietario. Los
agregados futuros por cuenta y entre cuentas son contratos separados: deben
declarar período, moneda base, conversión y tratamiento de transferencias antes de
sumar resultados.

Apache ECharts es la dependencia local fijada para las curvas analíticas actuales.

En operaciones cerradas, la fila principal prioriza Magic, tipo Long/Short con
posición debajo, símbolo, volumen, Open, Close, TP/SL y ganancia neta al final. Open/Close reciben
mayor ancho; bajo cada precio se muestra solo la fecha y hora del broker hasta
minutos en una línea. TP/SL ocupa una columna compacta y conserva su procedencia
como ayuda contextual. La fila despliega u oculta el detalle con clic, toque, Enter o
Espacio, sin columna ni botón adicional y con foco visible para teclado.
El detalle evita repetir la fila y muestra únicamente deals, ganancia bruta,
swap, comisión, pips y duración en una grilla de baja altura. Se presenta como
una extensión plana de fondo neutro, con divisores finos y una transición breve;
no compite visualmente con el resultado de la fila. Entradas y salidas parciales usan
precios medios ponderados por volumen. Las reversiones ambiguas no se etiquetan
como una dirección única. La ganancia neta determina un fondo verde/rojo tenue;
el cero conserva el fondo normal. En anchos reducidos la fila se reorganiza y
todos los campos se reorganizan sin scroll horizontal.
Pips espera una definición por símbolo; TP/SL no presume cambios no observados.
Las visualizaciones futuras, como histogramas de VaR o matrices de covarianza,
reutilizarán la misma biblioteca una vez aprobadas sus métricas.

### Navegación y tablas de actividad

La navegación lateral separa `Trading`, `Performance financiera` y
`Performance de ejecución`. `Trading` contiene únicamente posiciones y órdenes
en curso. `Performance financiera` reúne las operaciones cerradas y las
métricas y gráficos existentes. `Performance de ejecución` ofrece el Registro
MT5 para consultar el comportamiento observado. Los nombres anteriores de las
vistas se conservan solo como contexto histórico.

Las tablas de posiciones y órdenes en curso, igual que el Registro MT5, usan el
estilo compacto de operaciones cerradas: Magic primero, expansión por fila con
clic o teclado y detalles sin duplicar los datos ya visibles en la fila. El
diseño responde a pantallas estrechas. Los colores financieros expresan el
resultado pertinente y no presentan cancelaciones como fallos.

El resumen muestra Equity como cifra principal, con Balance y PnL flotante en
segundo plano y el margen libre bajo «En esta cuenta». La Performance financiera
ofrece dos modos. `Sumarizar` es el predeterminado: los EA elegidos se agregan
en una sola serie y sus métricas se recalculan desde los ciclos, sin sumar ratios.
`Comparar EAs` ofrece una barra lateral buscable con selección de hasta cinco EA.
En este modo los gráficos preceden a la tabla comparativa de métricas. PnL
acumulado es el gráfico principal y Drawdown aparece debajo, alineado con él; el
DD se dibuja negativo, aunque el valor de la métrica se presenta positivo.
PnL por operación y media móvil de 20 están bajo «Más gráficos». Un único zoom
temporal visible sincroniza los cuatro gráficos. El cursor y las interacciones
se conectan entre ellos, y al pasar por un EA se resaltan sus series. Se reducen
grillas y etiquetas para dar prioridad a las curvas; los colores por EA son
estables y no se repiten leyendas.

Las curvas siguen usando fechas reales y segmentos rectos entre observaciones,
sin suavizado ni escalones, y no alinean operaciones por índice. PnL por
operación usa barras en ambos modos: `Sumarizar` colorea por resultado y
`Comparar EAs` por EA. Cada barra muestra su valor numérico compacto, arriba si
es positivo y debajo si es negativo. La tabla de ciclos cerrados se conserva.
Se mantiene ECharts; este ajuste no cambia fórmulas ni datos.

Las ventanas temporales de los gráficos admiten hasta 12 meses y una fecha final,
incluida la vista de cuenta. El historial de Balance/Equity consulta capturas
existentes de SQLite mediante las APIs descritas en la referencia de API; no
cambia la retención. Cada consulta admite como máximo 366 días y devuelve hasta
480 puntos, tomando la última observación por bucket de al menos un minuto. No
preserva extremos, inventa valores ni rellena huecos. La ventana elegida no
garantiza que existan observaciones para todo el período.

La lista de operaciones cerradas conserva la paginación acotada a 500 registros
consultados y filtra en el cliente por los Magic elegidos. Si aún no hay
coincidencias en lo cargado, informa que puede usarse «Cargar más». La primera
página de la lista no define el conjunto de las métricas: estas se calculan sobre
el período consultado completo, sujeto al límite seguro de 500 ciclos.

El resumen compacto de los tres mejores EA usa PnL neto del período de 7 o 30
días (30 por defecto), solo ciclos elegibles y la cuenta actual, con los mismos
colores deterministas por Magic. Muestra cuenta, operaciones y cobertura; no es
un ranking ajustado por riesgo y puede incluir PnL negativo. Se actualiza como
máximo cada 60 segundos y también al llegar una captura nueva o cambiar vista o
filtro. Las etiquetas financieras usan «PnL neto»; distinguen «PnL flotante» y
«PnL bruto».

El historial de Balance/Equity solo presenta capturas disponibles: no reconstruye
equity desde operaciones ni modifica la retención existente. Los textos
auxiliares de métricas y cobertura se presentan como ayuda contextual junto al
dato pertinente.

Este ajuste de navegación no modifica la semántica del contrato de ciclos. Quedan
pendientes definir métricas y gráficos de ejecución con el socio, y revisar si
requieren persistir más evidencia; no es urgente ni se presupone cobertura
completa.

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

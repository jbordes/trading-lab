# Roadmap — Dashboard local de riesgo

## Prioridad acordada — 29 de octubre de 2026

El [plan de captura autónoma, historial completo y rendimiento](autonomous-capture-history-plan.md)
define la siguiente tanda, pendiente de aprobación para implementar:

1. **Implementación preparada:** separar receptores y dashboard, incluyendo
   configuración y credenciales; pendiente de validación manual, CI y merge.
2. Preparar arranque autónomo y mantenimiento programado con guardas.
3. Ampliar la recuperación reanudable a toda la historia disponible sin frenar
   datos recientes.
4. Preparar consultas y métricas para años de actividad; índices justificados por
   consultas y validación sintética, sin esperar a acumular años en el piloto.
5. Definir retención por clase de dato manteniendo entretanto la política sin TTL.

SQLite continúa para estos incrementos. Servidor central y PostgreSQL se evalúan
en una etapa posterior. Cada paso del plan detalla implementación, aceptación y
reversión; esta actualización no activa tareas, migraciones ni cambios en MT5.

**Fecha:** 2026-10-14

**Estado:** piloto MT5 operativo; validación de exactitud con reporte en curso

**Arquitectura:** [Dashboard local de riesgo](../architecture/live-risk-dashboard.md)

## Principios

- Solo lectura desde la credencial hasta la interfaz.
- Cuenta demo antes de conectar cuentas reales.
- Pocos segundos de demora; no prometer tiempo real estricto.
- Sin métricas cuya fórmula no haya aprobado el socio.
- Sin base ni modelo amplio antes de comprobar su necesidad.
- Historial, errores y frescura visibles; nunca ocultar datos obsoletos.
- Un collector y un `source_id` por identidad MT5; nunca selección automática de
  terminales mediante Python.

## Incremento 0B — Vista MT5 local

### Diseño de producto — 18 de octubre de 2026

- Inicio orientado a tareas; navegación y temas coherentes con el panel.
- Resumen con jerarquía equity/balance/margen y límites del gráfico visibles.
- Operaciones con filtros integrados, Magic seleccionable y composición móvil.
- Actividad primero, diagnóstico técnico secundario; carga y degradación explícitas.
- Actualizaciones por identidad de operación para conservar foco y detalle.
- Check opcional de navegador y alcance de validación documentados en la
  [guía UX](dashboard-evolution-ux.md).

No cambia las fuentes, el collector ni las definiciones de métricas. Queda
pendiente contrastar la usabilidad con los socios y dispositivos físicos.

Alcance:

1. Adaptador mínimo para `account_info`, `positions_get` y `orders_get`.
2. Snapshot tipado con cuenta enmascarada y valores finitos.
3. Polling configurable, cinco segundos por defecto y mínimo de dos.
4. Historial acotado en memoria.
5. Servidor enlazado únicamente a `127.0.0.1`.
6. Pantalla responsive con estado, valores y curva balance/equity.
7. Modo demo determinista.
8. Tests de la fuente, degradación, historial y HTTP read-only.

Gate:

- validación completa del harness;
- vista demo comprobada en localhost;
- ejecución real habilitada con terminal y cuenta demo autorizados.

## Incremento 0C — Validación MT5 real

Implementado:

1. Captura conectada al terminal MT5 demo autorizado.
2. Posiciones abiertas y órdenes pendientes individuales, con filtro por Magic
   Number.
3. Ventana móvil de 24 horas de deals y órdenes históricas, con lectura
   incremental solapada, reconciliación completa periódica, deduplicación y
   límite en memoria.
4. Estado de captura con duración, intentos, éxitos, fallos y último éxito.
5. Investigación multterminal: el descubrimiento automático eligió una terminal
   implícita; dos conexiones concurrentes dentro del mismo proceso cruzaron su
   estado. Procesos separados con ruta explícita no se cruzaron.

Pendiente para cerrar el incremento:

1. Comparar precios, volumen, SL/TP, resultado y timestamps con el terminal
   durante una sesión controlada.
2. Conservar la API Python solo para diagnósticos de una terminal por proceso,
   con ruta e identidad verificadas.
3. Incorporar una identidad separada con contraseña de inversor antes de usar
   cuentas reales.
4. Evaluar agrupación por bot después de validar el muestreo operativo, sin
   reemplazar el detalle por operación.

## Collector MT5 — Fuente operativa primaria

Implementado en la rama del [spike](mt5-telemetry-collector-spike.md): guardas de
demo/loopback, cola acotada, validación estricta y recuperación de deals mediante
relectura de una ventana reciente. La reconciliación reemplaza la vista, conserva
Magic Number y costes y señala errores/truncamiento. No cambia la UI ni calcula
métricas; pruebas sintéticas y compilación no equivalen a validación en terminal.

El receptor incorpora límites de conexiones, plazo de red y contenido retenido,
con eliminación de índices de sesiones al desalojar sus mensajes. Los seis
puntos de revisión están implementados para el piloto; no implican cierre de
la validación final con operaciones reales ni autorización de despliegue en una
cuenta real.

La prueba nativa determinista fue compilada y ejecutada en MT5-Juampi el
2026-10-17 con 0 errores, 0 warnings y 0 fallos. Se ejecutó sin red, lecturas de
cuenta ni funciones de trading; valida las simulaciones, no el piloto real.

ADR-0004 adopta este collector como fuente operativa primaria. La comparación
amplia contra Python deja de ser un gate: queda pendiente una validación acotada
de apertura/cierre, costes, Magic Number, completitud y timestamps para comprobar
el contrato. El reporte MT5 de la cuenta demo será la referencia para ese
contraste. La UI mostrará fecha y hora del broker y local; los futuros cortes
diarios declararán por separado su zona contractual.

## Incremento 0D — Telemetría push visible

Implementado en el primer corte:

1. lectura autenticada de la última muestra validada desde el receptor loopback;
2. selección explícita del `source_id` esperado y rechazo de otra fuente;
3. proyección de cuenta, balance/equity, posiciones y órdenes al contrato del
   dashboard;
4. estado degradado ante receptor ausente, autenticación incorrecta o muestra
   con más de 30 segundos;
5. deduplicación de muestras sin cambios para no inflar la curva al consultar el
   receptor más rápido que el colector.
6. frescura calculada continuamente en el navegador y degradación visual de la
   última muestra válida ante una caída del servicio local;
7. gráfico temporal con interrupciones visibles, navegación móvil sin desborde,
   filtros por Magic y tipo conservados por fuente, y detalles que permanecen
   abiertos durante las actualizaciones.

Pendiente para cerrar el incremento:

1. **Validado el 2026-10-28:** campos y operaciones del piloto coinciden con el
   reporte MT5 para el mismo corte;
2. **Implementado:** presentación compacta `Broker` / `Local` con offset explícito,
   sin inferirlo desde la VPS;
3. medir frescura y estabilidad durante una prueba prolongada.

Ya se comprobó en la terminal demo aislada el recorrido collector-receptor-
dashboard, la paridad de los campos seguros de cuenta, la degradación durante una
caída y la recuperación automática al reanudar el receptor.

## Incremento 0E — Promoción del collector

Implementado:

1. El dashboard exige elegir `--demo` o `--telemetry`; eliminó el descubrimiento
   automático de MT5 y telemetría requiere un `source_id` explícito.
2. Python permanece únicamente en la herramienta diagnóstica. La captura exige
   por entorno ruta de terminal, carpeta de datos, cuenta y servidor esperados,
   los verifica antes de leer operaciones y trabaja con una terminal por proceso.
3. El receptor conserva y entrega el último snapshot por `source_id`; el cliente
   solicita una fuente concreta y vuelve a verificarla. Pruebas con mensajes
   intercalados demuestran que un collector no desplaza los datos de otro.
4. El procedimiento manual de instalación, configuración, actualización y retiro
   se ejecutó en la terminal demo Juampi. Incluyó una recuperación controlada del
   cursor de actividad sin modificar los EAs de trading.

Pendiente:

5. Diseñar cómo presentar y alternar varias fuentes en una misma interfaz sin
   asumir todavía una base, cola o despliegue remoto. Nota: la interfaz ya
   presenta una fuente con su `source_id`, versión del colector y salud del
   receptor local; la alternancia entre varias fuentes sigue pendiente.
6. Completar la validación acotada con operaciones antes de usar cuentas reales.

## Prioridad inmediata — Historial y comparación por EA

La comparación con MT5 del 2026-10-25 detectó historial incompleto en la base
piloto. El [plan de recuperación histórica](history-recovery-plan.md) ya separó
estado vivo y actividad, recuperó deals y órdenes y reconstruyó ciclos cerrados.
La prioridad actual es contrastar esos ciclos y sus importes contra un reporte
MT5 generado en la misma cuenta demo, y luego hacer visible la cobertura por
período.

Esta prioridad precede nuevas ampliaciones de telemetría v2 y se rige por
[ADR-0012](../adr/0012-durable-operation-history.md).

1. **Implementado:** exponer desde la SQLite actual una consulta de deals
   históricos paginada y de solo lectura, con filtros por cuenta, periodo y
   Magic Number. La cuenta se resuelve mediante la fuente autorizada.
2. **Implementado:** `Trading` separa actividad en curso, ciclos cerrados y el
   registro MT5 auditable. El registro integra deals y órdenes históricas sin
   confundirlos con operaciones completas ni con las métricas.
3. **Implementado en el piloto:** mostrar cobertura y lotes incompletos junto a
   los filtros mediante una señal compacta. Indica `Datos completos`, `Datos
   parciales` o `Instantánea actual`; las métricas con cobertura parcial quedan
   rotuladas como tales.
4. **Primer corte implementado:** calcular y visualizar por período y Magic Number
   las fórmulas `partner-workbook-v1` observadas en el Excel del socio. Se incluyen
   tarjetas y las cuatro curvas de referencia con ECharts local. Cada cierre MT5
   fue inicialmente una fila. Este corte se conserva como referencia de contraste;
   la interfaz vigente aplica las mismas fórmulas bajo el contrato separado
   `position-cycle-v1`, únicamente a operaciones completas elegibles.
   La interfaz presenta hora y fecha del broker/MT5 junto con hora y fecha local
   del usuario mediante un offset explícito de la fuente. Esta decisión de
   presentación no define todavía qué zona
   usarán los futuros cortes diarios de las métricas.
5. Crear tablas derivadas durables e índices mediante una migración explícita
   cuando la consulta real o una prueba sintética representativa demuestre esa
   necesidad. No conservar el historial creciente en memoria.
6. Considerar una caché acotada únicamente después de medir consultas repetidas;
   SQLite seguirá siendo la fuente de verdad.

### Siguiente evolución acordada — Actividad y ciclos de posición

La dirección se rige por
[ADR-0014](../adr/0014-unified-trading-activity-and-position-cycle-metrics.md):

1. **Implementado:** unificar `Operaciones` e `Historial` como experiencia de
   `Trading`, con alcances `En curso`, `Operaciones cerradas` y `Registro MT5`,
   sin reemplazar las entidades MT5 ni forzar una única tabla de almacenamiento.
2. Exponer las órdenes históricas ya admitidas por telemetría v2 y su cobertura;
   conservar canceladas y vencidas para analizar comportamiento, no rendimiento.
   **API autenticada e integración visual implementadas.**
3. **Implementado y desplegado en el piloto:** proyectar durablemente ciclos por
   `account_id + position_id`, mediante una migración explícita y sin reconstruir
   el historial creciente completo en memoria.
4. **Implementado:** registrar Magic propietario, Magic observados, completitud y
   motivo de exclusión. La detección usa evidencia relacionada, no un único
   campo.
5. **Primer contrato implementado:** `position-cycle-v1` calcula exclusivamente
   sobre ciclos cerrados y elegibles. Las fórmulas continúan versionadas porque
   el socio las ajustará durante la evolución del producto.
6. **Implementado:** `Operaciones cerradas` separa rendimiento de la actividad y
   del diagnóstico del sistema y hace visible la cobertura del período.

La organización de navegación se rige por
[ADR-0016](../adr/0016-separate-financial-and-execution-performance.md), que
reemplaza únicamente la agrupación definida por ADR-0015. ADR-0015 sigue rigiendo
la experiencia de operaciones cerradas, el Registro MT5 y el contrato
`position-cycle-v1`.

### Navegación y tablas — corte de presentación

- [x] Separar la navegación lateral en `Trading` (solo posiciones y órdenes en
  curso), `Performance financiera` (operaciones cerradas, métricas y gráficos
  existentes) y `Performance de ejecución` (Registro MT5 para consultar
  comportamiento).
- [x] Compactar las tablas en curso y el Registro MT5 al estilo de operaciones
  cerradas: Magic primero, expansión por fila y teclado, detalles sin duplicados
  y composición responsive.
- [x] Aplicar colores financieros sin interpretar cancelaciones como fallos.
- [x] Presentar aclaraciones de métricas y cobertura como ayuda contextual junto
  al dato, no como textos sueltos en la vista.
- [ ] Definir métricas y gráficos de ejecución.
- [ ] Revisar si las métricas de ejecución requieren persistir evidencia
  adicional. No es urgente y no implica que la cobertura actual sea completa.

Este corte cambia presentación y navegación; no modifica contratos, fórmulas,
collector ni BDD. Los nombres anteriores de las vistas se mantienen como
contexto histórico.

### Pendientes visuales futuros

- [ ] Revisar la iconografía semántica del panel lateral.
- [ ] Añadir iconos para cerrar sesión y alternar tema claro/oscuro.
- [ ] Permitir expandir y contraer la barra lateral.
- [ ] Permitir seleccionar colores por Magic de forma controlada.
- [ ] Diagnosticar el indicador «Actualizado hace…», que rara vez vuelve a cero
  o parece quedar desfasado.

### Comparación financiera por EA y resumen compacto

- [x] Extender `/api/cycle-metrics` con `by_ea`, agrupado por
  `account_id + magic_number`, exclusivamente para ciclos cerrados elegibles.
  Cada grupo conserva `trade_count`, `net_profit`, `profit_factor`,
  `winning_percentage`, `maximum_drawdown`, `average_trade` y series de
  `time_msc`, `cumulative_profit`, `net_profit`, `drawdown` y
  `rolling_average_20`. Usa las fórmulas, cobertura y límite seguro de 500
  operaciones existentes.
- [x] Reutilizar los cuatro gráficos financieros existentes (PnL acumulado,
  drawdown, media móvil 20 y PnL por operación) con series por EA, colores
  estables por Magic y eje temporal de fechas reales. Las curvas trazan líneas
  rectas continuas entre observaciones reales, sin suavizado ni escalones. PnL
  por operación usa barras y no alinea cierres entre EA por índice. No se añade
  un quinto gráfico.
- [x] Incorporar `Sumarizar` como modo predeterminado, con los EA elegidos
  agregados en una sola serie y métricas recalculadas desde ciclos elegibles.
- [x] Incorporar `Comparar EAs` con barra lateral buscable, selección de hasta
  cinco, colores estables y sin leyendas repetidas; la tabla compara las mismas
  métricas y la tabla de ciclos se conserva.
- [x] Ordenar la vista comparativa con gráficos antes de la tabla de métricas;
  PnL acumulado es principal y Drawdown queda debajo y alineado. PnL por
  operación y media móvil 20 se muestran en «Más gráficos».
- [x] Sincronizar los cuatro gráficos con un solo zoom temporal visible y
  conectar cursor e interacción; hover de EA resalta sus series.
- [x] Reducir grillas y etiquetas y evitar leyendas repetidas. Dibujar DD
  negativo, manteniendo positivo el valor de la métrica.
- [x] Usar barras de PnL por operación en ambos modos: coloreadas por resultado
  en `Sumarizar` y por EA en `Comparar EAs`. Cada barra muestra el valor numérico
  compacto arriba si es positivo y debajo si es negativo.
- [x] Mantener ECharts; el ajuste no cambia datos ni fórmulas.
- [x] Permitir ventanas de gráfico hasta 12 meses con fecha final, incluida la
  cuenta. La consulta de Balance/Equity usa capturas SQLite existentes, con
  bucket mínimo de un minuto y máximo de 366 días y 480 puntos. Toma la última
  observación por bucket, no preserva extremos ni rellena huecos, no inventa
  datos y no modifica retención. La ventana no garantiza cobertura histórica.
- [x] Mantener paginación de operaciones cerradas acotada a 500 registros
  consultados con filtro cliente; sin coincidencias entre lo cargado, indicar
  que se puede «Cargar más». La primera página no limita el cálculo de métricas,
  que usa el período consultado completo dentro de su límite seguro de 500.
- [x] Mostrar Equity como cifra principal del resumen, Balance y PnL flotante
  debajo, y margen libre en «En esta cuenta».
- [x] Añadir Top 3 por PnL neto para período de 7/30 días (30 por defecto), solo
  ciclos elegibles y cuenta actual; mostrar cuenta, operaciones y cobertura.
  Usa los mismos colores deterministas por Magic; no es un ranking ajustado por
  riesgo y puede incluir resultados negativos. Se actualiza como máximo cada 60
  segundos y ante captura nueva o cambio de vista o filtro.
- [x] Usar «PnL neto» en etiquetas y distinguir PnL flotante y bruto.
- [ ] Definir métricas y gráficos de ejecución con el socio.
- [x] Consultar el historial de Balance/Equity disponible en SQLite sin
  migración ni cambio de retención. Solo se muestran observaciones persistidas;
  no se reconstruye equity desde operaciones ni se rellenan períodos sin datos.
- [ ] Ampliar retención únicamente tras una decisión basada en necesidad
  observada; la consulta actual no garantiza seis meses disponibles.

Mantener y ampliar fixtures de entrada múltiple, cierre parcial, Stop Loss/Take
Profit, intervención manual, Magic mixto, reversa netting, orden sin ejecución y
ventana histórica incompleta antes de modificar las reglas de elegibilidad.

**Dominio desplegado en el piloto:** un reconstructor puro agrupa deals
comerciales por cuenta y posición, suma volumen y resultado neto, conserva tickets
y Magic observados y clasifica ciclos cerrados, abiertos, incompletos o
inconsistentes. Solo devuelve resultado definitivo cuando el llamador confirma la
cobertura y no existen acciones sin atribución ni Magic mixtos. Sus ciclos cerrados
alimentan las métricas y la UI.

**Evidencia por ciclo implementada en código:** el collector de actividad detecta
posiciones candidatas al observar salidas o reversas y usa
`HistorySelectByPosition` antes de avanzar el cursor confirmado. Si puede probar
una posición cerrada completa, emite deals y órdenes como `position_reconcile`;
el receptor los valida y persiste sin confundir esa selección con cobertura global
de la cuenta. El collector `activity-0.2.0` se validó en Juampi mediante una
recuperación controlada: produjo 19 ciclos cerrados distintos y elegibles para los
Magic Numbers `11121` a `11125`. La proyección durable usa el esquema 4 y se
expone a métricas y UI.

**Consulta autenticada implementada en código:** el receptor expone ciclos
paginados en loopback con la credencial de lectura v2, filtro por Magic propietario
y validación estricta en el cliente del dashboard. La sesión humana puede
consultarlos mediante `/api/position-cycles` sin recibir esa credencial interna.
Las métricas `position-cycle-v1` y su presentación fueron validadas manualmente
con la base piloto real. La exactitud de importes y campos se contrastará ahora
contra un reporte MT5 de esa misma cuenta. La comparación con el workbook del
socio se posterga hasta desplegar TradingLab en su entorno real, porque sus EAs y
datos no existen en este piloto.

Criterio del primer corte alcanzado y validado manualmente: se puede abrir el historial
persistido, paginarlo y filtrar un EA por Magic Number sin cargar todos los
mensajes en memoria. La actividad durable y los ciclos provienen de v2; el estado
vivo continúa aislado en v1.

### Alcance de métricas acordado

1. El alcance principal para evaluar un bot es `account_id + owner_magic`: el
   mismo Magic se analiza dentro de una cuenta concreta, nunca mezclado
   implícitamente entre cuentas.
2. Las fórmulas actuales no son definitivas. Cada revisión aprobada creará una
   versión de contrato o una evolución explícita; no se reescribirán resultados
   históricos con una fórmula nueva sin identificarla.
3. En una etapa posterior se agregarán agregados por cuenta: PnL y otras métricas
   generales de todos los bots pertenecientes a la cuenta seleccionada.
4. Cuando existan varias cuentas podrá incorporarse una vista global. Antes se
   definirán moneda base, conversión, período, cuentas incluidas y tratamiento de
   transferencias; sumar importes de monedas distintas no será una operación
   implícita.

## Incremento 1 — Contrato de control operativo

Guía para la conversación: [Métricas de riesgo para acordar con el socio](guia-metricas-para-el-socio.md).

Resolver con el socio:

1. definición exacta del método DDD/WSF;
2. timezone y comienzo del día;
3. referencia de balance/equity y tratamiento del flotante;
4. límites fijos o trailing;
5. depósitos, retiros y resets;
6. fórmulas y reglas de agregación para cuenta y portfolio; el scope primario de
   performance de EA ya se fijó como bot dentro de una cuenta concreta.

Luego implementar DDD y Max DD como cálculos versionados con fixtures y casos límite.

## Incremento 2 — Persistencia mínima

Solo cuando el contrato de métricas históricas lo requiera:

1. definir frecuencia y retención necesarias;
2. evaluar SQLite append-only frente a segmentos inmutables en `_storage/`;
3. implementar idempotencia y recuperación tras reinicio;
4. conservar procedencia y payload crudo necesario;
5. agregar compactación o downsampling únicamente si el volumen medido lo exige.

## Incremento 3 — Riesgo histórico y visualizaciones

Las decisiones y ejemplos pendientes se recopilan en la
[guía de métricas](guia-metricas-para-el-socio.md).

1. Aprobar VaR, volatilidad, covarianza, riesgo de portfolio, MDD histórico y Sharpe.
2. Definir retornos, ventanas, pesos, horizonte, confianza y tasa de referencia.
3. Incorporar Apache ECharts como dependencia local fijada.
4. Agregar distribuciones, heatmap de covarianza y gráficos comparativos.
5. Validar resultados contra ejemplos suministrados por el socio.

## Incremento 4 — StocksTrader

1. Obtener token de una cuenta demo.
2. Confirmar permisos o scopes read-only con el proveedor.
3. Implementar cliente GET con hosts y rutas permitidos explícitamente.
4. Mapear el contrato mínimo sin forzar semántica MT5.
5. Resolver identidad de bot o estrategia en StocksTrader.
6. Comparar frescura y consistencia con su plataforma web.

## Seguimiento de robustez

La revisión de solo lectura de PR #48 (commit `a1d6959`) documenta cinco
hallazgos abiertos, prioridades y criterios de aceptación en
[Revisión de robustez — 2026-10-28](robustness-review-2026-10-28.md). Las
soluciones son propuestas y aún no están implementadas.

Se prepararon el [contrato v2 propuesto](../architecture/telemetry-v2-contract.md),
ADR-0011 y ejemplos sintéticos. El validador y la admisión v2 aislados cubren
credencial/fuente/cuenta/rol, identidad MT5, reintentos, conflictos, secuencia
estricta y recuperación histórica fuera de orden. No están conectados al receptor
v1. La [persistencia y composición v2](telemetry-v2-persistence.md) agregan una
base opt-in separada, recuperación durable y una vista de referencia. Migración,
proyecciones, receptor v2, collector de actividad y despliegue piloto ya están
operativos; el contraste formal contra el reporte MT5 y la cobertura visible ya
están resueltos. Falta la promoción fuera de la cuenta demo. V1 conserva el estado vivo; v2 es la
fuente durable de actividad y ciclos.

Antes de implementar nuevos collectors, revisar la
[separación de responsabilidades](../architecture/collector-responsibilities.md):
dos productores (estado vivo y actividad), diagnóstico integrado y piloto en la
terminal actual. Contrato, identidades, admisión, persistencia, migración,
receptor v2 y composición ya tienen fixtures y regresiones. El contraste del
piloto contra MT5 y la cobertura visible quedaron completados el 2026-10-28.
No se adoptará una proyección histórica acumulativa en memoria. La frecuencia de
un segundo y SSE quedan condicionados a mediciones; no requieren terminal adicional.

La [revisión del 21 de octubre de 2026](system-review-2026-10-21.md) reúne el
cierre de cinco bugs y los hallazgos medidos de performance y seguridad.
Consultar allí las prioridades, criterios de aceptación y la cadencia de revisión
cada seis PRs mergeados. El endurecimiento separa la autenticación humana del
token del EA, protege `/dashboard` y `/api/state` con sesiones locales y rechaza
autoridades HTTP ajenas. La remediación siguiente impide redirecciones y proxies
implícitos del cliente local y aplica admisión acotada y plazo por conexión al
servidor web; quedó integrada mediante PR #26. Continúan pendientes las mejoras de performance.
Ningún control actual autoriza ampliar la exposición del piloto.

## Fuera del piloto

- exposición pública o dentro de la LAN;
- ejecución o modificación de operaciones;
- PostgreSQL, TimescaleDB, colas o microservicios;
- autenticación multiusuario;
- fórmulas inferidas de ejemplos de Gemini;
- Excel como salida principal.

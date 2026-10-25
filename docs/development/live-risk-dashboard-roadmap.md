# Roadmap — Dashboard local de riesgo

**Fecha:** 2026-10-14

**Estado:** collector MT5 adoptado; promoción operativa pendiente

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
el contrato. También se medirá la ventana necesaria y se validará la zona horaria
del servidor antes de agregar paginación o persistencia.

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

1. validar campos y operaciones reales contra MT5 o una captura Python aislada;
2. validar la zona horaria del servidor antes de mostrar timestamps y deals;
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

Pendiente:

4. Validar en una segunda terminal el procedimiento manual reproducible ya
   documentado para compilar, instalar, configurar, verificar, actualizar y
   retirar un collector con aprobación humana. Automatizar solo después de
   conocer sus excepciones reales.
5. Diseñar cómo presentar y alternar varias fuentes en una misma interfaz sin
   asumir todavía una base, cola o despliegue remoto. Nota: la interfaz ya
   presenta una fuente con su `source_id`, versión del colector y salud del
   receptor local; la alternancia entre varias fuentes sigue pendiente.
6. Completar la validación acotada con operaciones antes de usar cuentas reales.

## Prioridad inmediata — Historial y comparación por EA

Esta prioridad precede nuevas ampliaciones de telemetría v2 y se rige por
[ADR-0012](../adr/0012-durable-operation-history.md).

1. **Implementado:** exponer desde la SQLite actual una consulta de deals
   históricos paginada y de solo lectura, con filtros por cuenta, periodo y
   Magic Number. La cuenta se resuelve mediante la fuente autorizada.
2. **Primer corte implementado:** vista de historial de deals con períodos de 1,
   7 y 30 días, Magic Number opcional y paginación manual. Órdenes históricas,
   posiciones y trades reconstruidos siguen pendientes y no se mezclan con deals.
3. Mostrar cobertura, truncamiento y periodos sin datos junto al resultado.
4. **Primer corte implementado:** calcular y visualizar por período y Magic Number
   las fórmulas `partner-workbook-v1` observadas en el Excel del socio. Se incluyen
   tarjetas y las cuatro curvas de referencia con ECharts local. Cada cierre MT5
   sigue siendo una fila; la comparación entre bots y la reconstrucción de trades
   con múltiples deals esperan definición con el socio.
   También queda pendiente acordar si la interfaz debe presentar la hora del
   broker/MT5, la hora local del usuario o ambas; hasta entonces no se usará esa
   escala temporal para calcular cortes diarios.
5. Crear tablas derivadas durables e índices mediante una migración explícita
   cuando la consulta real o una prueba sintética representativa demuestre esa
   necesidad. No conservar el historial creciente en memoria.
6. Considerar una caché acotada únicamente después de medir consultas repetidas;
   SQLite seguirá siendo la fuente de verdad.

Criterio del primer corte alcanzado en código: se puede abrir el historial
persistido, paginarlo y filtrar un EA por Magic Number sin cargar todos los
mensajes en memoria ni depender de v2. Falta la validación visual manual contra la
base piloto real.

## Incremento 1 — Contrato de control operativo

Guía para la conversación: [Métricas de riesgo para acordar con el socio](guia-metricas-para-el-socio.md).

Resolver con el socio:

1. definición exacta del método DDD/WSF;
2. timezone y comienzo del día;
3. referencia de balance/equity y tratamiento del flotante;
4. límites fijos o trailing;
5. depósitos, retiros y resets;
6. scope por cuenta, bot o portfolio.

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

Se prepararon el [contrato v2 propuesto](../architecture/telemetry-v2-contract.md),
ADR-0011 y ejemplos sintéticos. El validador y la admisión v2 aislados cubren
credencial/fuente/cuenta/rol, identidad MT5, reintentos, conflictos, secuencia
estricta y recuperación histórica fuera de orden. No están conectados al receptor
v1. La [persistencia y composición v2](telemetry-v2-persistence.md) agregan una
base opt-in separada, recuperación durable y una vista de referencia. Migración,
proyecciones incrementales, receptor v2, collectors y despliegue siguen pendientes.
Estos trabajos mejoran la captura futura, pero no bloquean la prioridad de historial
sobre los datos v1 ya persistidos.

Antes de implementar nuevos collectors, revisar la
[separación de responsabilidades](../architecture/collector-responsibilities.md):
dos productores (estado vivo y actividad), diagnóstico integrado y piloto en la
terminal actual. Contrato, identidades, admisión, persistencia y composición de
referencia ya tienen fixtures y regresiones. El próximo incremento define
provisión/migración y proyecciones durables antes de conectar un receptor v2.
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

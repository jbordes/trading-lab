# ADR-0012: Historial durable de operaciones como siguiente producto

**Estado:** accepted

**Fecha:** 2026-10-22

## Contexto

TradingLab ya recibe y conserva en SQLite mensajes validados que incluyen deals
históricos y Magic Number. El siguiente valor visible esperado es consultar el
historial de operaciones y entender cómo se comportan los EAs. El trabajo sobre
telemetría v2 todavía no entrega esa vista y no debe convertirse en un requisito
previo para aprovechar los datos existentes.

Una proyección que retenga observaciones históricas sin límite en memoria crecería
durante toda la vida del laboratorio, aumentaría el riesgo de agotar la RAM de la
VPS y obligaría a reproducir un volumen creciente después de cada reinicio. Medir
solo la base pequeña del piloto tampoco representaría meses o años de captura.

## Alternativas consideradas

1. Mantener todo el historial proyectado en memoria. Simplifica la lectura, pero
   traslada el crecimiento completo a la RAM y no resuelve el gobierno del dato.
2. Completar primero contrato, receptor, collectors y migración v2. Ordena la
   captura futura, pero posterga una necesidad que los datos v1 ya permiten iniciar.
3. Usar SQLite como fuente durable, consultar primero el journal existente y crear
   tablas derivadas e índices mediante migraciones explícitas solo cuando las
   consultas concretas del historial lo requieran.

## Decisión

Adoptar la tercera alternativa. La prioridad de producto será una vista paginada
del historial disponible, con periodo, cuenta y Magic Number como filtros. La
primera entrega mostrará entidades MT5 con su tipo real; un deal no se presentará
como trade completo cuando existan entradas, salidas parciales, múltiples fills o
movimientos no comerciales pendientes de clasificación.

SQLite será la fuente de verdad local para la historia. El journal de mensajes
validados se conserva como evidencia. La primera consulta reutilizará esos datos.
Cuando la forma o el coste de las consultas lo justifiquen, se incorporarán tablas
durables para deals, órdenes, trades reconstruidos, series de cuenta o agregados
por EA, con versión de esquema, procedencia, idempotencia e índices explícitos.

No se mantendrá una proyección histórica sin límites en memoria. Una caché futura
solo podrá acelerar consultas comprobadas, tendrá límites de bytes o entradas y
tiempo de vida, será descartable y siempre podrá reconstruirse desde SQLite.

La comparación de bots utilizará Magic Number dentro del contexto de una cuenta y
un periodo. Los rankings y métricas se añadirán después de acordar con el socio la
reconstrucción de trades, costes, depósitos/retiros, cierres parciales y horizonte
de comparación. Hasta entonces se mostrarán datos observados sin calificar un EA
como mejor o peor mediante una fórmula implícita.

La telemetría v2 puede continuar como mejora de captura y separación de flujos,
pero no bloquea el historial basado en evidencia v1 ya persistida.

## Consecuencias

- El siguiente incremento produce una vista útil antes de ampliar la plataforma.
- La paginación y los filtros evitan cargar el historial completo en el backend o
  el navegador.
- Las migraciones responden a una consulta demostrada y conservan rollback y
  compatibilidad; no se crean tablas por anticipación.
- Datos sintéticos de volumen servirán para validar índices y límites sin esperar
  meses, pero no sustituirán la validación semántica con operaciones reales.
- El gráfico reciente puede conservar su buffer acotado actual; esta decisión se
  refiere al historial creciente y a las comparaciones de largo plazo.

## Reemplaza

No reemplaza ADR-0002 ni ADR-0006. Precisa que sus buffers en memoria deben ser
acotados y que el journal SQLite será el punto de partida del historial durable.

# Informe automatizado de incubación MT5 — Análisis

**Fecha:** 2026-10-14

**Estado:** Validación funcional parcial; respuestas del socio incorporadas

**Alcance:** captura completa del ciclo operativo y generación diaria de un Excel por estrategia

## 1. Objetivo y entregable de referencia

Automatizar el informe que hoy se mantiene en Excel para los bots incubados en MetaTrader 5. El entregable principal de la primera versión será un libro por estrategia, compatible con el archivo de referencia y con ambos identificadores en el nombre:

```text
encubadora_<strategy_id>_<magic_number>.xlsx
```

El ejemplo concreto `encubadora_3.95.48_11122.xlsx` es el objetivo funcional y visual. `incubator_master.xlsx` es un antecedente útil para estudiar trazabilidad y reconciliación, pero no es el formato al que debe apuntar la primera versión ni un entregable obligatorio.

El socio confirmó que el Magic Number se asigna manualmente al entrar en incubación, identifica al bot y se conserva si el mismo bot corre en varias cuentas. El otro identificador lo asigna SQX durante el minado y puede repetirse. La captura y la lógica de negocio no dependerán de Excel: deben conservar toda la información disponible aunque el workbook inicial muestre una selección, y más adelante los mismos datos deberán poder persistirse en una base propia sin reescribir el núcleo.

No forman parte de esta etapa la ejecución de órdenes, el despliegue de bots, una base de datos productiva, un dashboard ni un consolidado master nuevo.

## 2. Evidencia analizada

Se inspeccionaron localmente, sin modificarlos ni incorporarlos a Git:

- el libro objetivo `encubadora_3.95.48_11122.xlsx`;
- un `ReportHistory-<account>.xlsx` exportado por MT5;
- `incubator_master.xlsx`, solo como antecedente;
- el prototipo histórico `build_incubator_database.py` y su documentación.
- las respuestas funcionales del socio sobre identidad, contenido, horario, correcciones, fallos y retención.

Los datos sensibles y rutas locales no se reproducen aquí. Los reportes completos y futuros outputs permanecerán fuera de Git; solo se versionarán contratos, código, fixtures mínimos anonimizados y documentación.

## 3. Contrato observado del libro objetivo

El libro es deliberadamente simple: una hoja `TRADES`, una cabecera y siete operaciones cerradas de ejemplo. No contiene fórmulas, gráficos, tablas estructuradas, vínculos externos ni macros. Tiene autofiltro sobre el rango usado, primera fila congelada, anchos de columna definidos y dos estilos.

La hoja tiene exactamente 37 columnas, de `A` a `AK`, en este orden:

| Grupo | Columnas |
|---|---|
| Identidad | `trade_uid`, `data_source`, `strategy_id`, `comment_raw` |
| Cuenta y procedencia | `account_id`, `account_name`, `broker`, `source_file`, `source_account`, `source_account_id`, `source_sha256`, `source_row` |
| IDs MT5 | `position_id`, `opening_order_id`, `closing_order_id`, `opening_deal_id`, `closing_deal_id` |
| Operación | `symbol`, `side`, `open_datetime`, `open_price`, `volume`, `stop_loss`, `take_profit`, `close_datetime`, `close_price` |
| Resultado | `commission`, `swap`, `gross_profit`, `net_profit`, `holding_seconds`, `timezone` |
| Control | `assignment_status`, `reconstruction_status`, `validation_status`, `possible_duplicate`, `notes` |

Observaciones relevantes:

- `trade_uid` sigue el patrón `INCUBATOR-<account>-<position>`.
- Las siete filas pertenecen a `strategy_id = 3.95.48` y preservan el comentario crudo.
- `net_profit` equivale a `gross_profit + commission + swap` en los ejemplos.
- `closing_order_id` y `closing_deal_id` están vacíos porque la fuente histórica utilizada no los aportó; la ausencia se conserva en vez de inventar IDs.
- `timezone` figura como `UNKNOWN`, por lo que la semántica temporal todavía debe acordarse.
- Los estados de asignación, reconstrucción, validación y posible duplicado son explícitos.
- El Magic Number `11122` aparece en la carpeta y el nombre del archivo, pero no dentro del workbook.

Ese último punto es una brecha del contrato actual. El Magic Number es el identificador operativo del bot y debe poder utilizarse para filtrar el listado. Por lo tanto, el contrato v1 agregará `magic_number` inmediatamente después de `strategy_id`, llevando la hoja a 38 columnas. También se conservará en el nombre del archivo y en el manifest de captura, pero ninguno de esos dos lugares sustituye la columna filtrable.

Como regla de negocio de TradingLab, un Magic Number corresponde a un único bot y puede aparecer en varias cuentas cuando ese mismo bot está desplegado en ellas. El registro de bots deberá detectar colisiones en vez de reasignarlas silenciosamente. Las órdenes, deals y posiciones seguirán calificándose con la cuenta porque sus IDs técnicos y su ejecución pertenecen a una cuenta concreta.

La grafía `encubadora` se mantendrá inicialmente por compatibilidad, aunque el término correcto sea “incubadora”.

## 4. Referencia histórica: consolidado master

El master observado contiene vistas de trades, posiciones, órdenes, deals, estrategias, fuentes, incidencias y reconciliación. Es valioso como evidencia de reglas y como oráculo de paridad del prototipo, pero no debe dirigir el diseño del Excel v1.

Su información más útil para el nuevo pipeline es:

- conservación de filas nativas y hashes de fuente;
- reconciliación de conteos y resultados económicos;
- registro explícito de incidencias;
- separación entre evidencia cruda y trade reconstruido.

Estas capacidades pertenecerán al dataset canónico, manifests, validaciones y logs. No requieren reproducir las múltiples hojas del master en cada libro entregado al socio.

## 5. Reporte XLSX de MT5

El ejemplo contiene secciones de posiciones cerradas, órdenes históricas, deals, posiciones abiertas, órdenes de trabajo, snapshot de cuenta y resultados agregados.

Los rótulos dependen del idioma y se observaron caracteres dañados en algunos textos. Un parser basado solo en etiquetas visibles sería frágil ante idioma, versión o configuración del terminal.

La posición cerrada no expone siempre la identidad de estrategia en sus columnas visibles. La asociación aparece en comentarios de órdenes o deals y debe reconciliarse mediante IDs nativos. La API ofrece además `magic`, que debería formar parte de la identidad del deployment cuando pueda mapearse confiablemente.

## 6. Prototipo histórico encontrado

Existe un script local de 677 líneas que procesa reportes HTML de MT5. Detecta posiciones, órdenes y deals; normaliza comentarios; calcula hashes; deduplica; reconcilia; y genera master, libros por estrategia, log y SQLite.

Esto demuestra que una parte importante de las reglas ya fue explorada. No debe copiarse como implementación final porque mezcla parseo, dominio, persistencia y presentación, elimina outputs obsoletos y carece de una suite de tests. Se reutilizarán sus invariantes comprobadas y sus resultados como oráculo de paridad.

La SQLite existente es un output experimental, no una autorización para diseñar ahora la base productiva.

## 7. Integración oficial con MetaTrader 5

El paquete oficial de Python permite conectar con un terminal mediante `initialize()` y cerrar la sesión con `shutdown()`. Para una captura de solo lectura resultan relevantes:

- `account_info()` y `terminal_info()`;
- `history_orders_get()` y `history_deals_get()`;
- `positions_get()` y `orders_get()`;
- `last_error()` para diagnóstico.

Referencias oficiales: [integración Python de MetaTrader 5](https://www.mql5.com/en/docs/python_metatrader5), [`initialize`](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py), [`history_orders_get`](https://www.mql5.com/en/docs/python_metatrader5/mt5historyordersget_py), [`history_deals_get`](https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py) y [`positions_get`](https://www.mql5.com/en/docs/python_metatrader5/mt5positionsget_py).

Una resolución en seco realizada en Windows con Python 3.14.7 encontró `MetaTrader5 5.0.6231`. La captura en vivo seguirá siendo específica de una máquina Windows con terminal MT5 disponible; normalización, pruebas y generación de Excel deben permanecer portables.

El adaptador será estrictamente de lectura y no expondrá `order_send()` ni equivalentes.

La API Python permite consultar el estado actual de posiciones y órdenes, y el historial de órdenes y deals. Esto no garantiza reconstruir después todos los estados intermedios de una posición. MT5 expone cambios en tiempo real mediante [`OnTradeTransaction`](https://www.mql5.com/en/docs/event_handlers/ontradetransaction), pero capturarlos exhaustivamente requeriría un componente MQL5 activo en el terminal. La v1 comenzará con historial más snapshots diarios; el spike determinará si esa evidencia alcanza o si se justifica un colector de eventos posterior.

## 8. Fuente primaria y arquitectura propuestas

Se propone trabajar inicialmente con dos adaptadores:

1. `Mt5ApiSource`: fuente diaria preferida para historial y estado vivo.
2. `Mt5ReportSource`: importador para backfill, contingencia y reconciliación durante el piloto.

Ambos producen el mismo modelo intermedio. Cada captura guardará fuera de Git evidencia inmutable —por ejemplo JSON normalizado más manifest y SHA-256— antes de generar reportes.

```text
MT5 API -----------+
                   +--> evidencia --> normalización --> reconstrucción --> dataset canónico
Reporte MT5 -------+                         |                 |
                                             |                 +--> validación/incidencias
                                             +--> strategy_id + magic_number

dataset canónico --> encubadora_<strategy_id>_<magic_number>.xlsx
                 --> futuro repositorio de base de datos
```

Componentes:

- `sources`: adaptadores de API y reportes; no conocen el Excel de salida.
- `domain`: cuenta, orden, deal, posición, deployment y captura.
- `bot_registry`: relación versionada entre Magic Number, bot, identificador SQX, estrategia y cuentas observadas.
- `normalization`: convierte campos MT5 a tipos canónicos sin perder originales.
- `reconstruction`: agrupa deals por `account_id + position_id` y contempla cierres parciales.
- `strategy_resolution`: resuelve `strategy_id + magic_number` mediante mapping explícito y evidencia.
- `evidence`: conserva captura, manifest, hashes, versión y ventana temporal.
- `reporting`: proyecta una vista seleccionada del dataset al contrato `TRADES`; no consulta MT5.
- `orchestration`: coordina locking, reintentos y publicación atómica.

Un futuro repositorio de base de datos consumirá el mismo dataset que el escritor Excel; no se introducirá un ORM ni una base simulada en esta etapa.

## 9. Identidad, tiempo y deduplicación

- `magic_number` es el identificador manual, estable y filtrable del bot en incubación; `strategy_id` conserva el identificador asociado a la estrategia/SQX.
- El mismo Magic Number puede aparecer en varias cuentas únicamente cuando representa al mismo bot.
- El registro autoritativo indicará la relación entre bot, Magic Number, identificador SQX, estrategia, cuentas y vigencia.
- El archivo se agrupa por estrategia; la regla para una estrategia que tenga más de un Magic Number a lo largo del tiempo todavía debe acordarse.
- IDs nativos siempre se califican con la cuenta.
- La clave de posición será al menos `account_id + position_id`.
- Deals y órdenes se deduplicarán por tickets nativos, preservando conflictos como incidencias.
- Se almacenarán timestamps UTC y valores crudos; la ejecución diaria se programará a las 20:00 de `Europe/Madrid`, aplicando automáticamente el horario de verano.
- Los importes se tratarán con `Decimal` y tolerancias documentadas.
- Las capturas y observaciones serán inmutables. Una corrección descubierta después se registrará como una nueva revisión enlazada con la anterior, sin borrar evidencia publicada.

## 10. Excel v1 propuesto

La primera versión debe conservar la forma del archivo objetivo:

- un archivo por estrategia;
- nombre `encubadora_<strategy_id>_<magic_number>.xlsx`;
- inicialmente una hoja `TRADES` con el mismo formato de la referencia;
- las 37 columnas de referencia más `magic_number` inmediatamente después de `strategy_id`;
- autofiltro sobre las 38 columnas, fila congelada, anchos y tipos compatibles con la referencia;
- campos vacíos cuando la fuente no aporta un dato, con estado de validación explícito;
- publicación mediante archivo temporal, validación y reemplazo atómico.

El pipeline capturará órdenes, deals, posiciones cerradas, posiciones abiertas, órdenes activas y snapshots disponibles, aunque el Excel inicial no los exponga todos. El workbook se generará desde evidencia canónica; no será la fuente utilizada para reconstruir operaciones ni detectar cambios.

Las filas ya publicadas no se editarán silenciosamente. Si se detecta una corrección, se conservará la observación anterior y se agregará una revisión con fecha de detección actual. Antes de implementar falta acordar cómo se enlazan y muestran esas revisiones para que no parezcan trades duplicados.

No se agregarán por defecto hojas de resumen, abiertos, pendientes, fuentes o incidencias. Esos datos pueden capturarse para trazabilidad y futuro uso, pero solo llegarán al workbook si el socio confirma que los necesita. El master queda diferido.

La elección entre `openpyxl` y XlsxWriter se realizará después de validar si hay que preservar exactamente estilos o contenido manual. Dado que la referencia no contiene fórmulas ni celdas manuales aparentes, regenerar el archivo es la opción más robusta.

## 11. Operación diaria y seguridad

- Ejecutar diariamente a las 20:00 de `Europe/Madrid` en el equipo Windows que contiene el terminal autorizado.
- Configurar rutas, terminales, cuentas y mappings fuera del código.
- Procesar cuentas secuencialmente o de forma aislada y cerrar siempre MT5.
- Usar un lock por terminal/cuenta.
- Capturar una ventana solapada y deduplicar.
- Escribir evidencia y reportes en temporales, validar y reemplazar al final.
- Conservar la última salida válida ante fallos.
- No borrar capturas ni reportes: se conservarán indefinidamente y dejarán de producirse cuando el proceso migre a la base, salvo que se decida mantenerlos como vista.
- Registrar conteos, duración e incidencias sin exponer secretos. En la primera etapa, los fallos se consultarán en los logs; las alertas para usuarios no técnicos quedan diferidas.

## 12. Decisiones confirmadas y aclaraciones pendientes

Confirmado por el socio:

- conservar `encubadora_<strategy_id>_<magic_number>.xlsx`;
- generar un archivo por estrategia;
- tratar el Magic Number manual como ID estable del bot, compartido por sus despliegues en distintas cuentas;
- mantener inicialmente el formato del workbook y disponer internamente de toda la información recuperable;
- ejecutar a las 20:00 hora de Madrid con ajuste estacional;
- conservar lo publicado y registrar posteriormente cualquier corrección detectada;
- usar logs como mecanismo inicial de diagnóstico y no eliminar reportes.

Aclaraciones todavía necesarias:

1. ¿Dónde se mantendrá el registro autoritativo Magic Number ↔ bot ↔ ID SQX ↔ estrategia, y quién lo actualiza?
2. ¿Puede una estrategia recibir más de un Magic Number a lo largo del tiempo y, en ese caso, cómo se nombra y agrupa su único archivo?
3. ¿La primera versión del Excel seguirá mostrando solo cerradas o también incorporará abiertas y pendientes? La captura interna conservará todas en cualquier caso.
4. ¿Cómo debe verse una corrección en el Excel y qué campos identificarán la revisión y la fila reemplazada?
5. ¿El archivo por estrategia es acumulativo y se reemplaza diariamente, o además se conserva una copia fechada de cada publicación?
6. ¿La ejecución se realiza todos los días, incluidos fines de semana, y qué debe ocurrir si el equipo o MT5 no están disponibles exactamente a las 20:00?
7. ¿En qué ruta se publican los Excel y las copias históricas?

## 13. Riesgos principales

| Riesgo | Mitigación propuesta |
|---|---|
| Magic Number solo en el nombre | Columna `magic_number` obligatoria y filtrable, más manifest |
| Comentarios inconsistentes | Mapping autoritativo + estado `UNRESOLVED` |
| Un bot desplegado en varias cuentas | Magic Number estable para el bot; operaciones calificadas por cuenta |
| Corrección confundida con duplicado | Revisiones enlazadas e historial inmutable |
| Cambios intradiarios no recuperables | Spike de API; evaluar colector `OnTradeTransaction` solo si es necesario |
| Entradas/salidas parciales | Reconstrucción por deals y `position_id` |
| Cambios de idioma/formato | API primaria y adapters versionados con fixtures |
| Timezone ambiguo | UTC crudo + zona operativa explícita |
| Duplicados | Claves nativas calificadas e idempotencia |
| Excel corrupto | Regeneración, validación y reemplazo atómico |
| Pérdida antes de la DB | Capturas inmutables, manifests y hashes fuera de Git |
| Diferencias API/reporte | Shadow run y reconciliación antes de automatizar |

## 14. Conclusión

La meta concreta es actualizar diariamente un libro por estrategia con nombre `encubadora_<strategy_id>_<magic_number>.xlsx`, evolucionando el contrato observado a 38 columnas para incluir el identificador filtrable del bot. El master histórico sigue siendo útil para validar reglas internas, no como formato de salida.

La implementación debe capturar más información de la que inicialmente presenta Excel, preservar cada observación y permitir una futura base sin reescribir el dominio. Antes de programar deben resolverse las siete aclaraciones operativas de la sección 12 y comprobar en un spike qué historia de cambios entrega realmente MT5.

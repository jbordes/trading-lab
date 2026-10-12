# Informe automatizado de incubación MT5 — Análisis

**Fecha:** 2026-10-12

**Estado:** Propuesto; requiere validación funcional con el socio

**Alcance:** captura, reconstrucción de operaciones y generación diaria de un Excel por estrategia y Magic Number

## 1. Objetivo y entregable de referencia

Automatizar el informe que hoy se mantiene en Excel para los bots incubados en MetaTrader 5. El entregable principal de la primera versión será un libro por combinación de estrategia y Magic Number, compatible con el archivo de referencia:

```text
encubadora_<strategy_id>_<magic_number>.xlsx
```

El ejemplo concreto `encubadora_3.95.48_11122.xlsx` es el objetivo funcional y visual. `incubator_master.xlsx` es un antecedente útil para estudiar trazabilidad y reconciliación, pero no es el formato al que debe apuntar la primera versión ni un entregable obligatorio.

La captura y la lógica de negocio no dependerán de Excel: más adelante los mismos datos deberán poder persistirse en una base propia sin reescribir el núcleo.

No forman parte de esta etapa la ejecución de órdenes, el despliegue de bots, una base de datos productiva, un dashboard ni un consolidado master nuevo.

## 2. Evidencia analizada

Se inspeccionaron localmente, sin modificarlos ni incorporarlos a Git:

- el libro objetivo `encubadora_3.95.48_11122.xlsx`;
- un `ReportHistory-<account>.xlsx` exportado por MT5;
- `incubator_master.xlsx`, solo como antecedente;
- el prototipo histórico `build_incubator_database.py` y su documentación.

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

Ese último punto es una brecha del contrato actual. La automatización necesita representar el Magic Number como dato confiable, no deducirlo indefinidamente de una ruta. Se recomienda agregar `magic_number` junto a `strategy_id`, lo que llevaría el contrato evolucionado a 38 columnas, o conservar las 37 columnas y registrar el mapping en un manifest versionado. La opción debe validarse con el socio para no romper una dependencia oculta de su Excel.

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
- `normalization`: convierte campos MT5 a tipos canónicos sin perder originales.
- `reconstruction`: agrupa deals por `account_id + position_id` y contempla cierres parciales.
- `strategy_resolution`: resuelve `strategy_id + magic_number` mediante mapping explícito y evidencia.
- `evidence`: conserva captura, manifest, hashes, versión y ventana temporal.
- `reporting`: proyecta trades cerrados al contrato `TRADES`; no consulta MT5.
- `orchestration`: coordina locking, reintentos y publicación atómica.

Un futuro repositorio de base de datos consumirá el mismo dataset que el escritor Excel; no se introducirá un ORM ni una base simulada en esta etapa.

## 9. Identidad, tiempo y deduplicación

- `strategy_id` y `magic_number` representan dimensiones distintas y ambas deben conservarse.
- Una misma estrategia puede aparecer con distintos Magic Numbers, cuentas o deployments; no se fusionarán silenciosamente.
- El mapping autorizado indicará qué combinación genera cada archivo.
- IDs nativos siempre se califican con la cuenta.
- La clave de posición será al menos `account_id + position_id`.
- Deals y órdenes se deduplicarán por tickets nativos, preservando conflictos como incidencias.
- Se almacenarán timestamps UTC y valores crudos; la zona de negocio debe acordarse explícitamente.
- Los importes se tratarán con `Decimal` y tolerancias documentadas.

## 10. Excel v1 propuesto

La primera versión debe conservar la forma del archivo objetivo:

- un archivo por combinación autorizada de estrategia y Magic Number;
- nombre `encubadora_<strategy_id>_<magic_number>.xlsx`;
- una única hoja `TRADES` con operaciones cerradas;
- orden de columnas, autofiltro, fila congelada, anchos y tipos compatibles con la referencia;
- campos vacíos cuando la fuente no aporta un dato, con estado de validación explícito;
- publicación mediante archivo temporal, validación y reemplazo atómico.

El workbook se regenerará desde evidencia canónica en cada ejecución. No se usará el Excel anterior como base incremental: la idempotencia y la deduplicación ocurren antes de escribirlo.

No se agregarán por defecto hojas de resumen, abiertos, pendientes, fuentes o incidencias. Esos datos pueden capturarse para trazabilidad y futuro uso, pero solo llegarán al workbook si el socio confirma que los necesita. El master queda diferido.

La elección entre `openpyxl` y XlsxWriter se realizará después de validar si hay que preservar exactamente estilos o contenido manual. Dado que la referencia no contiene fórmulas ni celdas manuales aparentes, regenerar el archivo es la opción más robusta.

## 11. Operación diaria y seguridad

- Ejecutar en el equipo Windows que contiene el terminal autorizado.
- Configurar rutas, terminales, cuentas y mappings fuera del código.
- Procesar cuentas secuencialmente o de forma aislada y cerrar siempre MT5.
- Usar un lock por terminal/cuenta.
- Capturar una ventana solapada y deduplicar.
- Escribir evidencia y reportes en temporales, validar y reemplazar al final.
- Conservar la última salida válida ante fallos.
- No borrar capturas ni reportes anteriores hasta definir retención y backup.
- Registrar conteos, duración e incidencias sin exponer secretos.

## 12. Decisiones a validar con el socio

1. ¿La compatibilidad exige exactamente las 37 columnas o se puede agregar `magic_number` como columna explícita?
2. Si no se agrega, ¿se aprueba un manifest versionado como fuente autoritativa del mapping?
3. ¿Se conserva el nombre `encubadora_<strategy_id>_<magic_number>.xlsx` y la grafía actual?
4. ¿El archivo debe contener solo trades cerrados, como la referencia?
5. ¿Deben preservarse exactamente orden, nombres, filtro, fila congelada y anchos?
6. ¿Dónde se publica cada archivo y qué ocurre si una estrategia usa varios Magic Numbers o cuentas?
7. ¿Cuál es la fuente autoritativa del mapping Strategy ID ↔ Magic Number?
8. ¿Qué zona horaria representa el reporte y cuál define el corte diario?
9. ¿Se permite corregir o completar históricamente un trade ya publicado?
10. ¿Qué alerta y retención se requieren ante una captura o validación fallida?

## 13. Riesgos principales

| Riesgo | Mitigación propuesta |
|---|---|
| Magic Number solo en el nombre | Columna explícita o manifest versionado aprobado |
| Comentarios inconsistentes | Mapping autoritativo + estado `UNRESOLVED` |
| Múltiples deployments de una estrategia | Clave y archivo por `strategy_id + magic_number` |
| Entradas/salidas parciales | Reconstrucción por deals y `position_id` |
| Cambios de idioma/formato | API primaria y adapters versionados con fixtures |
| Timezone ambiguo | UTC crudo + zona operativa explícita |
| Duplicados | Claves nativas calificadas e idempotencia |
| Excel corrupto | Regeneración, validación y reemplazo atómico |
| Pérdida antes de la DB | Capturas inmutables, manifests y hashes fuera de Git |
| Diferencias API/reporte | Shadow run y reconciliación antes de automatizar |

## 14. Conclusión

La meta concreta ya no es un master genérico: es reproducir y actualizar diariamente el libro `encubadora_<strategy_id>_<magic_number>.xlsx`, empezando por el contrato observado de 37 columnas y una hoja `TRADES`. El master histórico sigue siendo útil para validar reglas internas, no como formato de salida.

La implementación debe ser un pipeline auditable con Excel como proyección reemplazable. El primer gate es confirmar con el socio cuánto del contrato debe permanecer idéntico y cómo hacer explícito el Magic Number. Luego se demostrará paridad entre reporte, API y archivo objetivo antes de automatizar la ejecución diaria.

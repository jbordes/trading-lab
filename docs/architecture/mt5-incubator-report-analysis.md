# Informe automatizado de incubación MT5 — Análisis

**Fecha:** 2026-10-12

**Estado:** Propuesto; requiere validación funcional con el socio

**Alcance:** captura de datos de cuentas de incubación, reconstrucción de operaciones y generación diaria de Excel

## 1. Objetivo

Automatizar el informe que hoy se mantiene en Excel para los bots incubados en MetaTrader 5. La primera entrega debe producir libros utilizables por el socio, pero la captura y la lógica de negocio no pueden depender de Excel: más adelante los mismos datos deberán persistirse en un catálogo o base propia sin reescribir el núcleo.

No forman parte de esta etapa la ejecución de órdenes, el despliegue de bots, una base de datos productiva ni un dashboard.

## 2. Evidencia analizada

Se inspeccionaron localmente, sin modificarlos ni incorporarlos a Git:

- un libro de una estrategia con una hoja `TRADES` y siete operaciones;
- `incubator_master.xlsx`, consolidado de referencia;
- un `ReportHistory-<account>.xlsx` exportado por MT5;
- el prototipo histórico `build_incubator_database.py` y su documentación.

Los nombres de personas, cuentas y rutas locales observados no se reproducen en este documento. Los reportes completos y futuros outputs permanecerán fuera de Git; solo se versionarán contratos, código, fixtures mínimos anonimizados y documentación.

## 3. Estructura observada

### Libro por estrategia

El ejemplo contiene una hoja `TRADES` con 41 columnas. Conserva identidad estable, procedencia, cuenta, IDs nativos, precios, volumen, costes, beneficio, duración, estado de asignación y validación.

### Consolidado maestro

El master contiene:

| Hoja | Filas observadas | Función |
|---|---:|---|
| `TRADES_MASTER` | 155 trades + cabecera | Vista canónica de posiciones cerradas |
| `POSITIONS_RAW` | 155 + cabecera | Filas nativas de posiciones |
| `ORDERS_RAW` | 14.393 + cabecera | Órdenes históricas y de trabajo |
| `DEALS_RAW` | 317 + cabecera | Transacciones atómicas |
| `STRATEGIES` | 27 estrategias + cabecera | Resumen de identidad y cobertura |
| `SOURCES` | 3 fuentes + cabecera | Procedencia, hashes y conteos |
| `ISSUES` | Solo cabecera | Incidencias de parseo o reconciliación |
| `RECONCILIATION` | 21 controles + cabecera | Comparación contra totales informados |

No tiene fórmulas ni tablas estructuradas: es principalmente una salida de datos auditable, no todavía un informe de negocio terminado.

### Reporte XLSX de MT5

El ejemplo contiene una hoja con secciones localizadas:

- posiciones cerradas;
- órdenes históricas;
- transacciones o deals;
- posiciones abiertas;
- órdenes de trabajo;
- snapshot de balance, equity, margen y beneficio flotante;
- métricas agregadas y gráficos.

Los rótulos dependen del idioma y se observaron caracteres dañados en algunos textos. Un parser basado solo en etiquetas visibles sería frágil ante idioma, versión o configuración del terminal.

La posición cerrada no expone el identificador de estrategia en sus columnas visibles. En el reporte, la asociación aparece en comentarios de órdenes, deals o posiciones abiertas y debe reconciliarse mediante IDs nativos. La API ofrece además el campo `magic`, que debería ser la identidad primaria cuando el deployment permita mapearlo de forma confiable.

## 4. Prototipo histórico encontrado

Existe un script local de 677 líneas que procesa reportes HTML de MT5 mediante biblioteca estándar. El prototipo:

- detecta posiciones, órdenes y deals;
- normaliza comentarios `Strategy 1.2.3` y variantes;
- calcula hashes y conserva filas originales;
- deduplica por cuenta e ID nativo;
- reconcilia cantidad de posiciones, beneficio y balances;
- genera master, libros por estrategia, log y SQLite;
- produjo 155 trades de 27 estrategias sin diferencias de reconciliación en su corrida registrada.

Esto demuestra que una parte importante de las reglas ya fue explorada. No debe copiarse como implementación final porque mezcla parseo, dominio, persistencia y presentación; escribe archivos directamente, elimina outputs obsoletos y carece de una suite de tests. Se reutilizarán sus invariantes comprobadas y los resultados como oráculo de paridad.

La SQLite existente es un output experimental del prototipo, no una autorización para diseñar ahora la base productiva.

## 5. Integración oficial con MetaTrader 5

El paquete oficial de Python permite conectar con un terminal mediante `initialize()` y cerrar la sesión con `shutdown()`. Para una captura de solo lectura resultan relevantes:

- `account_info()` y `terminal_info()` para contexto de la captura;
- `history_orders_get()` para órdenes históricas;
- `history_deals_get()` para deals históricos;
- `positions_get()` para posiciones abiertas;
- `orders_get()` para órdenes activas;
- `last_error()` para diagnóstico.

Referencias oficiales: [integración Python de MetaTrader 5](https://www.mql5.com/en/docs/python_metatrader5), [`initialize`](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py), [`history_orders_get`](https://www.mql5.com/en/docs/python_metatrader5/mt5historyordersget_py), [`history_deals_get`](https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py) y [`positions_get`](https://www.mql5.com/en/docs/python_metatrader5/mt5positionsget_py).

Una resolución en seco realizada en Windows con Python 3.14.7 encontró `MetaTrader5 5.0.6231`, por lo que no aparece una incompatibilidad inmediata con el toolchain actual. La captura en vivo seguirá siendo específica de una máquina Windows con terminal MT5 disponible; normalización, pruebas y generación de Excel deben permanecer portables.

El adaptador será estrictamente de lectura y no expondrá `order_send()` ni operaciones equivalentes.

## 6. Fuente primaria propuesta

Se propone trabajar inicialmente con dos adaptadores:

1. `Mt5ApiSource`: fuente diaria preferida para historial y estado vivo.
2. `Mt5ReportSource`: importador del reporte exportado, usado para backfill, contingencia y reconciliación durante el piloto.

Ambos producen el mismo modelo intermedio. El Excel de entrada no debe transformarse directamente en el Excel final, y el Excel final nunca será la única fuente de verdad.

Cada captura guardará fuera de Git una evidencia inmutable —por ejemplo JSON normalizado más manifest y SHA-256— antes de generar reportes. Hasta que exista una base, esas capturas permiten regenerar el Excel, detectar correcciones del broker y evitar que una edición manual destruya el historial.

## 7. Arquitectura propuesta

```text
MT5 API -----------+
                   +--> captura cruda --> normalización --> reconstrucción --> dataset canónico
Reporte MT5 -------+                              |                 |
                                                  |                 +--> incidencias/reconciliación
                                                  |
                                                  +--> resolución strategy_id

dataset canónico --> Excel por estrategia
                 --> master opcional
                 --> futuro repositorio de base de datos
```

### Componentes

- `sources`: adaptadores de API y reportes; no conocen Excel de salida.
- `domain`: modelos tipados de cuenta, orden, deal, posición, snapshot y estrategia.
- `normalization`: convierte campos MT5 a tipos y unidades canónicas sin perder el valor original.
- `reconstruction`: agrupa deals por `account_id + position_id`, contempla entradas/salidas parciales y deriva ciclos de posición.
- `strategy_resolution`: prioriza mapping explícito de Magic Number; usa comentario como evidencia secundaria y nunca adivina silenciosamente.
- `evidence`: conserva captura, manifest, hash, versión del parser y ventana temporal.
- `reporting`: transforma el dataset canónico en libros; no consulta MT5.
- `orchestration`: coordina la ejecución diaria, locking, reintentos y publicación atómica.

Las fronteras serán interfaces Python pequeñas. Un futuro `DatabaseRepository` consumirá el mismo dataset que el escritor Excel; no se introducirá una base simulada ni un ORM en esta etapa.

## 8. Modelo mínimo

### Registros históricos

- `AccountRef`: identidad de cuenta, broker, moneda y tipo, sin credenciales.
- `RawOrder`: ticket, posición relacionada, Magic Number, comentario, tipo, estado, precios y tiempos.
- `RawDeal`: ticket, orden, posición, entrada/salida, costes, beneficio y tiempo en milisegundos cuando esté disponible.
- `PositionLifecycle`: posición reconstruida con colecciones de deals, no solo un opening/closing deal singular.
- `StrategyAssignment`: estrategia, método de asignación, evidencia y confianza.

### Snapshots diarios

- `AccountSnapshot`: balance, equity, margen, margen libre y beneficio flotante.
- `OpenPositionSnapshot`: estado de cada posición abierta al momento de captura.
- `PendingOrderSnapshot`: órdenes activas al momento de captura.
- `CollectionRun`: ID, terminal, cuenta, ventana solicitada, instante UTC, versión, estado, conteos y hashes.

Historial y snapshots no deben mezclarse: un deal es un evento durable; balance, posiciones abiertas y órdenes pendientes son observaciones en un instante.

## 9. Identidad, tiempo y deduplicación

- IDs nativos siempre se califican con la cuenta: `account_id + ticket`.
- La clave de posición será al menos `account_id + position_id`.
- Deals y órdenes se deduplicarán por sus tickets nativos, preservando conflictos como incidencias.
- La estrategia se resolverá preferentemente desde `magic`; el comentario se conservará crudo y se parseará mediante reglas versionadas.
- Se almacenarán timestamps UTC y valores crudos de tiempo. La jornada de negocio y la zona del servidor/broker deben acordarse explícitamente.
- No se inferirá timezone desde la computadora. El reporte inspeccionado incluso contiene eventos posteriores a su fecha visible de generación, señal de que hay que validar la semántica temporal.
- Importes se tratarán con `Decimal` en el dominio; los `float` de la API se convertirán de forma explícita y se reconciliarán con tolerancias documentadas.

## 10. Excel propuesto

El formato final debe confirmarse con el socio. Como base, cada estrategia podría contener:

- `SUMMARY`: métricas acumuladas y fecha de actualización;
- `TRADES`: posiciones cerradas reconstruidas;
- `OPEN_POSITIONS`: último snapshot;
- `PENDING_ORDERS`: último snapshot;
- `DAILY_SNAPSHOTS`: evolución diaria;
- `SOURCES`: procedencia y hashes;
- `ISSUES`: asignaciones o reconciliaciones pendientes.

Se recomienda regenerar el libro completo desde evidencia canónica y publicarlo mediante reemplazo atómico, en vez de usar el propio Excel como base incremental. Esto evita duplicados, permite backfill y prepara la migración futura a base de datos.

La elección entre `openpyxl`, XlsxWriter o un escritor OOXML propio se realizará después de acordar si hay que preservar una plantilla editable. Si el libro se regenera, XlsxWriter es una opción; si se deben conservar fórmulas o celdas manuales existentes, deberá evaluarse `openpyxl`.

## 11. Operación diaria y seguridad

- Ejecutar en la VPS o equipo Windows que contiene el terminal autorizado.
- Configurar rutas, alias de terminal y cuentas fuera del código; credenciales solo en almacenamiento local seguro.
- Procesar cuentas secuencialmente o en procesos aislados, cerrando siempre la conexión MT5.
- Usar un lock por terminal/cuenta para evitar capturas simultáneas.
- Capturar una ventana solapada y deduplicar, en vez de confiar únicamente en el último timestamp exitoso.
- Escribir captura y reportes en temporales, validar y reemplazar al final.
- No borrar reportes anteriores hasta definir retención y backup.
- Registrar conteos, duración, última operación, incidencias y resultado sin exponer cuenta completa ni información personal en logs compartidos.

## 12. Preguntas que debe responder el socio

1. ¿El entregable normal es un libro por estrategia, un master, o ambos?
2. ¿Qué hojas, columnas, fórmulas, filtros, colores y métricas utiliza realmente para decidir?
3. ¿Existen celdas manuales que deban preservarse?
4. ¿La identidad confiable de cada bot es Strategy ID, Magic Number, comentario o una tabla de mapping?
5. ¿Qué cuentas y terminales participan y pueden mezclar estrategias?
6. ¿Qué define el corte diario: hora Madrid, hora broker o una hora operativa específica?
7. ¿Deben aparecer posiciones abiertas y órdenes pendientes o solo trades cerrados?
8. ¿Cómo se corrigen reasignaciones de estrategia o datos históricos?
9. ¿Dónde se publican los Excel y cuánto historial debe conservarse?
10. ¿Qué alerta necesita cuando una captura, asignación o reconciliación falla?

## 13. Riesgos principales

| Riesgo | Mitigación propuesta |
|---|---|
| Comentarios inconsistentes | Magic Number + mapping versionado + estado `UNRESOLVED` |
| Entradas/salidas parciales | Reconstrucción por deals y `position_id`, no emparejado simple |
| Cambios de idioma/formato del reporte | API primaria y adapters versionados con fixtures |
| Timezone ambiguo | UTC crudo + zona operativa explícita + reconciliación |
| Duplicados por ventana solapada | Claves nativas calificadas por cuenta e idempotencia |
| Excel corrupto o parcialmente escrito | Regeneración y reemplazo atómico |
| Pérdida antes de implementar DB | Capturas inmutables, manifests y hashes fuera de Git |
| Diferencia entre API y reporte | Shadow run y tablas de reconciliación antes de automatizar |
| Dependencia del terminal Windows | Adaptador MT5 aislado; dominio y reporting portables |

## 14. Conclusión

La tarea es viable y existe un prototipo valioso para acelerar el trabajo. La implementación correcta no es “actualizar una planilla”: es construir un pipeline de captura auditable con Excel como primera proyección. El primer gate no es técnico sino funcional: acordar con el socio el contrato del informe y la identidad de estrategia. Después debe demostrarse paridad entre reporte, API y resultados históricos antes de programar la ejecución diaria.

# Referencia provisional de métricas del workbook del socio

**Fecha de observación:** 2026-10-17

**Estado:** descripción de una copia en trabajo; no es un contrato de métricas aprobado.

## Revisión e implementación del 2026-10-24

Se volvió a inspeccionar el workbook en uso, todavía abierto por Excel y por ello
sin hash certificable. En esta revisión el selector contenía el Magic Number
11131 y 16 resultados. La hoja había cambiado: incorporaba `Expectancy neta R`
como promedio del resultado dividido por 200, desplazaba la desviación estándar
y mantenía las cuatro curvas descriptas abajo. Esto confirma que el archivo es
una referencia mutable y que cada interpretación debe conservar una versión.

TradingLab implementa el primer adaptador como `partner-workbook-v1`. Selecciona
solo deals comerciales MT5 de compra/venta que sean salidas, salidas parciales o
reversiones; excluye aperturas y movimientos contables. Una orden pendiente no
puede ingresar porque no es un deal. El resultado neto suma profit, comisión,
swap y fee. Los cierres parciales siguen siendo filas independientes y no se
presentan como trades reconstruidos.

El dashboard calcula y muestra, para el período y Magic Number elegidos, resultado
neto, cantidad de cierres, Profit Factor, porcentaje ganador, promedio, drawdown
máximo y actual con sus porcentajes, Return/DD, expectancy neta y desviación
estándar. También muestra ganancia acumulada, drawdown, resultado por cierre y
media móvil de 20 cierres. `Average Trade (bene x trade)` no se duplica porque su
fórmula coincide con Average Trade. Trades por mes espera una procedencia válida
para la fecha de activación de cada EA. La consulta está limitada a 500 deals y
falla explícitamente si el período excede ese límite, en vez de cargar un histórico
creciente en memoria. Apache ECharts 6.1.0 se distribuye localmente con su licencia;
el dashboard no depende de una CDN.

Esta versión sigue siendo provisional: usa capital de referencia 100000 y riesgo
de referencia 200 porque son las constantes observadas. El socio deberá confirmar
si corresponden globalmente, por cuenta, por EA o por configuración. También sigue
pendiente decidir cómo reconstruir trades con múltiples deals y qué hora mostrar.

## Decisión posterior sobre métricas definitivas (2026-10-27)

`partner-workbook-v1` permanece como reproducción versionada de la referencia y
no se reinterpretará silenciosamente. La métrica definitiva de autonomía de un EA
no contará cada salida como un trade independiente: utilizará ciclos completos de
posición agrupados por `account_id + position_id`, de acuerdo con
[ADR-0014](../adr/0014-unified-trading-activity-and-position-cycle-metrics.md).

Solo serán elegibles los ciclos cerrados de principio a fin, con resultado neto
definitivo, cobertura completa y atribución inequívoca a un único EA. Posiciones
abiertas, evidencia incompleta, intervención externa y colisiones de Magic Numbers
se excluirán de las métricas individuales sin eliminarse del historial. Las salidas
por Stop Loss o Take Profit propias de la operación no son intervenciones por sí
mismas. En cuentas netting no se repartirá de forma sintética el resultado de una
posición compartida entre EAs.

## Fuente y alcance

Archivo local `orders-scalping_1 (2).csv.xlsx`, en el Escritorio. Se inspeccionaron
los XML de hojas, fórmulas, valores calculados guardados y gráficos, sin ejecutar
Excel, modificar el archivo ni consultar MT5. El workbook y sus datos no se
incorporan a Git. Las fórmulas siguientes corresponden a la lectura de esta
jornada; el archivo puede cambiar posteriormente. Al documentar se intentó
obtener su SHA-256, pero estaba ocupado por otro proceso. No hay hash ni copia
congelada que permitan certificar que una revisión futura sea idéntica.

El socio decide cómo analizar las estrategias y mantiene este Excel. TradingLab
documenta y verifica el comportamiento técnico; no convierte automáticamente los
posibles errores del workbook en reglas de producto ni corrige su archivo.
La [guía de métricas](guia-metricas-para-el-socio.md) conserva los acuerdos
pendientes de riesgo; este ejemplo no define DDD ni límites de cuenta.

## Selección y datos de entrada

- Hoja de exportación: `orders-scalping_1 (2)`, columnas A:W.
- Hoja de análisis: `111111`. Su nombre no identifica al EA seleccionado.
- A3 es el selector variable de Magic Number. Tenía 11132 durante la lectura.
- B4 contiene `FILTER('orders-scalping_1 (2)'!A:W,
  'orders-scalping_1 (2)'!U:U=A3,"No matches")`, almacenada con prefijos internos
  de Excel. No filtra estado ni ordena por fecha.
- La columna O del origen (Net profit) pasa a P en la hoja de análisis.
- Se observaron 141 registros: 128 `Closed position`, 6 `Open position` y
  7 `Pending order`; las demás filas hasta la 221 no eran registros de operaciones.
- Los 128 registros cerrados cumplen `Net profit = Profit + Swap + Commission`
  con tolerancia numérica de 0,00001. No demuestra completitud de costes del broker.

El usuario confirmó que el selector cambia para examinar diferentes EA. También
transmitió que el socio detectó un registro pending que no debía entrar en las
métricas. En esta lectura, el filtro de 11132 produjo 13 cerradas y una abierta,
no una pendiente. No se afirma que sea el mismo registro señalado por el socio.
El filtro será revisado por él; la población definitiva de cada métrica sigue
pendiente. «Evaluar trades» no resuelve por sí solo cómo incluir estados abiertos.

## Fórmulas observadas

Notación: `p[i]` es Net profit numérico de cada fila seleccionada, en su orden
actual; `n` es su cantidad; `S[i]` es su suma acumulada. `C = 100000` es una
constante del workbook, no capital asignado al bot confirmado. Se define
`E[i] = C + S[i]`, `H[i] = max(C, E[1], ..., E[i])` y `D[i] = H[i] - E[i]`.
Los nombres internos de las fórmulas no implican que E sea equity observada.

| Celda | Nombre en Excel | Cálculo observado |
|---|---|---|
| Y4 | Ganancia acumulada | `SCAN` suma Net profit no vacío de P4:P9999 |
| Z4 | Drawdown Curve | `D[i]`, con máximo inicial de 100000 |
| AA4 | Profit per Trade | Valores de P4:P9999 convertidos a número |
| AB4 | Rolling Avg Trade (20) | Media de `p[max(1,i-19):i]`; usa menos de 20 al comienzo |
| AD4 | Número de trades | Número de filas de la serie Y4, no conteo por estado |
| AE4 | Profit Factor | Suma de p positivos / valor absoluto de la suma de p negativos; `IFERROR` devuelve `N/A` |
| AF4 | Winning Percentage | Cantidad de p estrictamente positivos / n; ceros cuentan en el denominador |
| AG4 | Average Trade | Último S / n |
| AH4 | Max Drawdown | Máximo D |
| AI4 | Max Drawdown % | AH4 / 100000 |
| AJ4 | Drawdown actual | Máximo de C y de toda E, menos último E |
| AK4 | Drawdown actual % | AJ4 / máximo de C y de toda E |
| AL4 | Return / DD Ratio | Último S / AH4; sin guarda explícita de división por cero |
| AM4 | Average Trade (bene x trade) | Misma fórmula que AG4 |
| AN4 | Average Trades per Month | n / (`YEARFRAC(A6, MAX(origen!K:K), 1)` × 12) |
| AO4 | Desviación estándar | `STDEV.S` de Net profit no vacío de P4:P10000, muestral |

En AN4, A6 es la fecha manual de activación y el final es la mayor fecha de cierre
de toda la exportación, no solo del bot. No es un promedio de conteos por meses
calendario. AO4 usa una fila más de rango que las otras series. Las conversiones
`NUMBERVALUE` especifican punto decimal y coma de agrupación.

## Gráficos observados

| Gráfico | Serie | Referencia guardada |
|---|---|---|
| chart1 | Ganancia acumulada | Rango fijo Y4:Y17 |
| chart2 | Drawdown | Nombre `drawdown_curve`, rango dinámico de Z4 |
| chart3 | Profit/Loss per Trade | Nombre `profit_per_trade`, rango dinámico de AA4 |
| chart4 | Rolling Avg Trade (20) | Rango fijo AB4:AB17 |

Los rangos fijos pueden quedar cortos al seleccionar otro EA o agregar filas.
Las series siguen el orden de los registros; no representan por sí mismas una
serie temporal intratrade ni el peor flotante alcanzado durante cada operación.

## Comprobación numérica de esta lectura

Los Net profit filtrados coinciden con los valores guardados en la segunda hoja.
Se recalcularon independientemente suma, Profit Factor, ganadoras, promedio,
drawdown monetario, Return/DD y desviación estándar, con coincidencia salvo
redondeo de punto flotante. No se recalculó el libro mediante Excel ni se verificó
de forma independiente YEARFRAC. AN4 tenía guardado 21,2916667.

| Resultado | Valor de las 14 filas seleccionadas |
|---|---|
| Neto acumulado | 211,58 |
| Profit Factor | 1,29858877 |
| Ganadoras | 10 / 14 = 71,428571 % |
| Promedio por fila | 15,11285714 |
| Máximo drawdown monetario | 228,27 |
| Máximo drawdown / capital fijo | 0,22827 % |
| Drawdown actual | 0 |
| Return / DD | 0,92688483 |
| Desviación estándar muestral | 166,06555617 |

Como contraste técnico, las 13 cerradas suman -209,44 y su Profit Factor es
0,70443127. La fila abierta aporta 421,02. Esto ilustra el impacto de la selección;
no aprueba excluir o incluir esa fila ni evalúa la calidad del bot.

## Aspectos a conservar explícitos antes de implementar

1. Selector variable de Magic Number y cuenta como contexto de las operaciones.
2. Estados admitidos y tratamiento de posiciones abiertas/órdenes pendientes,
   según la revisión del socio; nunca asumir una fila equivalente a un trade cerrado.
3. Orden de los registros: el filtro no usa `SORT`; la muestra completa seleccionada
   no tiene cierre cronológico creciente. Debe acordarse qué orden alimenta la curva.
4. Capital de referencia y denominador de porcentajes: AI4 y AK4 usan bases diferentes.
5. Ventanas iniciales menores de 20 y ausencia de datos, pérdidas o drawdown;
   prever resultados no disponibles, sin inventar ceros.
6. Diferenciar drawdown de esta curva de resultados del drawdown real de equity
   y de límites operativos DDD/Max DD de cuenta.

Cuando el socio ajuste el Excel, comparar fórmulas, rangos, filtros y ejemplos;
documentar la revisión y su aprobación antes de cambiar el cálculo del producto.
La primera implementación podrá contrastarse con ejemplos aprobados, usando datos
sintéticos en tests. Esta documentación no instala dependencias ni introduce métricas.

## Archivos EA revisados

En la carpeta `MQL5/Experts/Advisors` del terminal indicado se encontraron fuentes
y binarios `ExpertMACD`, `ExpertMAMA`, `ExpertMAPSAR` y `ExpertMAPSARSizeOptimized`,
con cabeceras MetaQuotes y Magic Numbers de fuente 10981, 12003, 14598 y 27893.
No coinciden con los del workbook. Esto no identifica los EA activos ni demuestra
que los bots del socio no existan en otras carpetas. No se ejecutaron binarios ni
se modificó la terminal.

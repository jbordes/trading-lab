# Inventario inicial de bots para revisar con el socio

**Fecha:** 2026-10-17

**Estado:** inventario documental; vigencia de los bots pendiente de confirmar.

## Criterios confirmados

- El rendimiento del EA se evaluará a partir de sus trades.
- Magic Number es el identificador del bot, asignado manualmente al incubarlo.
- Según las respuestas del socio, un Magic Number corresponde al mismo bot aun
  cuando opere en varias cuentas. La cuenta identifica dónde ocurrió cada trade;
  no cambia la identidad del bot. El identificador de SQX puede repetirse.
- Estas decisiones no fijan todavía fórmulas ni el tratamiento de cierres
  parciales. Se prepararán ejemplos de esos casos cuando aparezcan en los datos.

Fuentes: aclaraciones del usuario del 2026-10-17 y archivo local no versionado
`docs/development/respuestas del socio.md`.

## Alcance y lectura del listado

Revisión de solo lectura de
`C:\TradingLab\SQX\PROJECTS\Scalping 9 robots\Estrategias`.
No es un inventario de todos los proyectos ni una consulta a terminales MT5.
No certifica bots activos, ejecutables compilados, calidad o disponibilidad para
operar. Se encontraron 13 fuentes `.mq5` y 13 workbooks individuales de incubación.

Los 13 Magic Numbers están comprobados en la declaración `input int MagicNumber`
del fuente. Es el valor por defecto del archivo, no una verificación del parámetro
usado actualmente en MT5. Las referencias SQX de la primera tanda se deducen del
nombre del workbook; requieren confirmación de correspondencia con el fuente.

En la tabla, «Sí» para un reporte significa que existe un archivo con nombre
compatible: todavía no se reconciliaron sus trades ni sus parámetros internos.
Todos tienen un workbook `encubadora_<referencia SQX>_<magic>.xlsx`.

| Magic Number | Referencia SQX candidata | Tanda | Reporte SQX HTML | Retest MT5 por nombre | Observación |
|---|---|---|---|---|---|
| 11111 | 1.11.68 | Primera | Sí, nombrado 11111 | No localizado | Excel auxiliar `SQX_Backtest_1111.xlsx`: falta un dígito respecto al Magic |
| 11112 | 3.14.77 | Primera | Sí, nombrado 11112 | No localizado | Excel auxiliar `SQX_Backtest_1112.xlsx` |
| 11113 | 4.32.86 | Primera | Sí, nombrado 11113 | No localizado | Excel auxiliar `SQX_Backtest_11113.xlsx` |
| 11114 | 3.31.49 | Primera | Sí, nombrado 11114 | No localizado | Excel auxiliar `SQX_Backtest_1114.xlsx` |
| 11121 | 2.62.51 | Segunda | Sí | Sí | Carpeta dice `2.62.5`; contiene además retest y `.set` de 11125 |
| 11122 | 3.95.48 | Segunda | Sí | Sí | Candidato principal por disponibilidad documental |
| 11123 | 3.85.59 | Segunda | En carpeta de 11124 | Sí | Contiene además retest y `.set` de 11125 |
| 11124 | 3.54.59 | Segunda | Sí | Sí | Contiene también reporte SQX de 3.85.59 y archivos de 11125 |
| 11125 | 3.63.65 | Segunda | Sí | Sí | Alternativa al piloto 11122 |
| 11131 | 1.94.53 | Tercera | Sí | Sí | Conjunto documental candidato |
| 11132 | 2.55.82 | Tercera | Sí | Nombre diferente | Retest y `.set` dicen `2.22.82`; `.set` confirma Magic 11132 |
| 11133 | 5.19.54 | Tercera | Sí | Sí | Reporte guardado en subcarpeta `MT5` |
| 11134 | 5.55.47 | Tercera | Sí | No localizado | No asumir que nunca se hizo retest |

Los workbooks accesibles contienen una hoja `TRADES`. El de 11122 estaba ocupado
por otro proceso y no pudo abrirse en esta revisión; no se cerró ni modificó.
No se usaron las dimensiones de las hojas para inferir cantidades de trades.
Los HTML colectivos de `encubadora/` y el master antiguo se localizaron, pero no
se atribuyeron automáticamente a cada bot.

## Evidencia para el candidato principal

Rutas relativas a la carpeta revisada:

- `2daTanda/11122_3.95.48/Strategy 3.95.48.mq5`: declara Magic Number 11122.
- `2daTanda/11122_3.95.48/SQX 3.95.48/Strategy 3.95.48.html`.
- `2daTanda/11122_3.95.48/Retest MT5/ReportTester_11122_3.95.48.html`.
- `2daTanda/11122_3.95.48/Retest MT5/11122_3.95.48.set`: declara Magic 11122.
- `2daTanda/11122_3.95.48/encubadora_3.95.48_11122.xlsx`.

Recomendación: comenzar la revisión con 11122, por tener fuente, parámetros,
reporte SQX, retest y workbook identificables. No implica que sea el mejor bot.
Si el socio indica que dejó de ser representativo, revisar 11125 como alternativa.

## Preguntas concretas para la conversación

1. ¿El bot 11122 sigue siendo un ejemplo útil de lo que estamos incubando?
2. ¿Los archivos listados de 11122 corresponden a la misma versión y configuración?
   Si alguno quedó viejo, ¿cuál usamos como referencia?
3. ¿Qué periodo de incubación quieren comparar y dónde está su historial completo?
4. Para cada fila: ¿el bot está incubando, pausado, descartado o todavía en pruebas?
5. ¿El retest `2.22.82` de 11132 pertenece a `2.55.82` o es otra versión?

Las inconsistencias de carpetas se presentan como hallazgos, no como errores
confirmados. No se movieron, renombraron ni eliminaron archivos.

## Próximo paso después de la confirmación

Reconciliar los trades de un solo bot con su reporte de referencia. Preparar una
ficha de ejemplo con periodo, costes y cobertura explícitos; presentar al socio
cualquier cierre parcial o reversión que requiera una definición adicional.
La selección de API Python o collector no es necesaria para esta revisión de
reportes exportados. Las fórmulas continúan sujetas a la
[guía de métricas](guia-metricas-para-el-socio.md).

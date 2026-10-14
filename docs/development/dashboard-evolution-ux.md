# Dashboard local de riesgo — Análisis de UX y diseño en evolución

**Fecha:** 2026-10-15

**Estado:** guía de diseño del prototipo, vigente hasta que el contrato de métricas (incremento 1) introduzca los valores reales.

**Documentos relacionados:** [Dashboard local de riesgo](../architecture/live-risk-dashboard.md), [Roadmap](live-risk-dashboard-roadmap.md), [Guía de métricas para el socio](guia-metricas-para-el-socio.md).

## 1. Rol de esta pantalla dentro del laboratorio

El dashboard es el primer producto de observabilidad del piloto (mod. 2.4): la ventana de confianza entre el laboratorio y las personas. No es una app de trading ni el sistema; el sistema es la trazabilidad de extremo a extremo desde la idea SQX hasta la decisión de incubación. Tres ejes de diseño sobreviven a todos los incrementos:

1. **Honestidad como lenguaje**: nunca ocultar datos obsoletos, nunca mostrar una métrica cuya fórmula no haya aprobado el socio, distinguir lo verificado de lo declarado.
2. **Dos audiencias, una pantalla**: el trader (detalle operativo, trazabilidad) y el socio no técnico (riesgo en castellano llano).
3. **El diseño es un contrato más**: cada valor derivado debe poder remitir a su fuente (run, deployment, evidence bundle) cuando exista el catálogo.

## 2. Estado del prototipo (octubre 2026)

A partir de tres análisis previos (UX, diseño visual, performance en navegador) se aplicaron en fases:

- Corrección del doble encoding UTF-8 y guarda de mojibake en el harness.
- Números como tablero financiero: signo y color en P&L, ceros neutros, agrupación de miles, locale `es-AR`, formatters `Intl` cacheados.
- Gráfico honesto: sin letterbox, etiquetas de máximo/mínimo, horas de inicio/fin, ventana temporal, línea de referencia del balance inicial.
- Frescura visible: chip relativo con tinte al envejecer, atenuación de datos obsoletos, banner de error con mensaje humano y detalle técnico colapsado.
- Menos churn: guard por `observed_at`, polling encadenado a la cadencia del servidor con timeout y backoff, firmas de render por datos y filtro, sin re-render de vistas ocultas.
- Historial incremental (`?since=`) con cache de estáticos (ETag/304), HTTP/1.1 y gzip condicional en el servidor local.
- Panel de riesgo con estructura del incremento 1 y valores ilustrativos solo para la demo (badge "Contrato pendiente · valores ilustrativos", alcance deshabilitado, reloj del reset diario).
- Vista de operaciones agrupable por bot (prototipo del pendiente 4 de 0C), vista de actividad con resultado neto de la ventana y filtro por resultado.
- Accesibilidad: patrón real de tabs con navegación por flechas, `aria-live` acotado, `caption` y `scope` en tablas.
- Fuente demo determinista más realista: balance con deriva, seis operaciones y fallo de captura simulado cada 24 lecturas para validar los estados degradados.

## 3. Evolución por incremento

### Incremento 1 — Contrato DDD / Max DD

- El panel de riesgo pasa de placeholder a protagonista del Resumen: es el número por el que el socio pregunta todos los días.
- Semántica de riesgo propia, distinta de profit/loss: uso del límite en porcentaje, estados verde/ámbar/rojo por umbrales del contrato, y siempre texto además de color.
- El "día" como objeto visible: barra de progreso hacia el límite y tiempo real hasta el reset (timezone Madrid).
- Scope por bot/portfolio: si el contrato lo exige, la agrupación por bot deja de ser un filtro de comodidad y pasa a ser navegación. Una vista "Riesgo" dedicada se justifica cuando haya que comparar límites entre varios bots.
- Los valores simulados del prototipo (`DEMO_RISK` en `app.js`) se reemplazan por datos del snapshot calculados con fórmula aprobada.

### Incremento 2 — Persistencia mínima

- El gráfico deja de perder la ventana al reiniciar: continuidad visual con gaps honestos (un hueco de captura es información, no un defecto).
- Rango temporal seleccionable (última hora / día / semana) recién cuando exista dato histórico.
- Los períodos degradados se sombrean apenas, sin ruido visual.

### Incremento 3 — Riesgo histórico y visualizaciones (ECharts)

- Vista "Riesgo" dedicada con sub-navegación interna; los tabs principales no superan los cuatro.
- ECharts como dependencia local fijada y themada con los tokens del design system desde el día uno.
- Cada visualización técnica (VaR, covarianza, Sharpe) entra con su "frase" en castellano para el socio: la interpretación que hoy hace el trader en su cabeza, la pantalla la escribe.

### Incremento 4 — StocksTrader

- Selector de fuente visible en el topbar (el pill actual es su preparación) y vocabulario adaptado por fuente, sin forzar semántica MT5.
- Estados de captura por fuente: la conexión pasa de booleano a resumen de N fuentes.
- No superponer en el mismo gráfico datos de fuentes distintas sin aviso explícito.

## 4. Decisiones de diseño tomadas

- **Dark único**: es un terminal; sin light mode hasta que exista una necesidad real.
- **Locale `es-AR`** con hora 24 h, agrupación de miles consistente y signo explícito en resultados.
- **Fuente del sistema**: sin fuentes descargadas; el sistema operativo provee la tipografía (sin `@font-face` ni dependencias).
- **Sin dependencias externas ni build**: HTML/CSS/JS/SVG servidos por la biblioteca estándar; ECharts se incorpora solo en el incremento 3 como archivo local fijado.
- **Navegación**: Resumen, Operaciones, Actividad y (incremento 3) Riesgo — estable a lo largo del tiempo.
- **Filtros que no recargan**: match exacto por Magic Number, agrupación por bot, filtro por resultado; vista y filtros persisten entre recargas.

## 5. Lo que NO se construye antes de su gate

- Alertas push, multi-cuenta, autenticación: fuera del piloto.
- Métricas históricas sin contrato aprobado: ni en prototipo, salvo los valores ilustrativos explícitos de la demo.
- Vista de portfolio, rangos temporales y gaps del gráfico: esperan persistencia (incremento 2).
- Selector de fuente completo: espera StocksTrader (incremento 4).

## 6. Riesgos de diseño a vigilar

1. **Regresión a "Excel mental"**: si el socio pide "el número de siempre", resistir con panel, no con planilla.
2. **Sobrecarga en incremento 3**: diez visualizaciones técnicas sin capa de lenguaje espantan al socio; cada gráfico entra con su frase.
3. **Demo como espejo falso**: todo prototipo debe contrastarse con datos reales del terminal antes de darse por cerrado.
4. **Métricas no aprobadas presentadas como válidas**: hasta el contrato, placeholder honesto o "—".

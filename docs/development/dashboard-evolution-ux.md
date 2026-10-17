# Dashboard local de riesgo — Análisis de UX y diseño en evolución

**Fecha:** 2026-10-15

**Estado:** guía de diseño del prototipo, vigente hasta que el contrato de métricas (incremento 1) introduzca los valores reales.

**Documentos relacionados:** [Dashboard local de riesgo](../architecture/live-risk-dashboard.md), [Roadmap](live-risk-dashboard-roadmap.md), [Guía de métricas para el socio](guia-metricas-para-el-socio.md).

## 1. Rol de esta pantalla dentro del laboratorio

El dashboard es el primer producto de observabilidad del piloto (mod. 2.4): la ventana de confianza entre el laboratorio y las personas. No es una app de trading ni el sistema; el sistema es la trazabilidad de extremo a extremo desde la idea SQX hasta la decisión de incubación. Tres ejes de diseño sobreviven a todos los incrementos:

1. **Honestidad como lenguaje**: nunca ocultar datos obsoletos, nunca mostrar una métrica cuya fórmula no haya aprobado el socio, distinguir lo verificado de lo declarado.
2. **Dos audiencias, una pantalla**: el trader (detalle operativo, trazabilidad) y el socio no técnico (riesgo en castellano llano).
3. **El diseño es un contrato más**: cada valor derivado debe poder remitir a su fuente (run, deployment, evidence bundle) cuando exista el catálogo.

## 2. Estado del prototipo (actualizado 17 de octubre de 2026)

A partir de tres análisis previos (UX, diseño visual, performance en navegador) se aplicaron en fases y, en octubre de 2026, un rediseño completo según el ADR-0005:

- Página de proyecto en `/` (qué es TradingLab, pipeline, estado y límites) y panel en `/dashboard`, con navegación cruzada.
- Tema claro y oscuro con tokens `light-dark()`: paleta cálida tipo reporte y oscuro neutro sin negro puro, validada en WCAG AA; elección persistida sin flash al recargar; superficies planas separadas por bordes de 1px, sin gradientes, sombras ni mayúsculas sostenidas.
- Resumen curado: equity protagonista en tono neutral, resultado abierto con signo,
  color y palabra, balance y margen secundarios, franja de origen con fuente,
  `source_id` y versión del collector, y nota honesta de riesgo sin estimaciones.
- Operaciones con tabla de cinco columnas y detalle expandible por operación;
  Magic Number visible, filtros por Magic y tipo, estado del detalle y foco
  conservados entre actualizaciones; "No informada" en timestamps no validados y
  filas apiladas sin scroll horizontal en viewports chicos.
- Actividad y estado de la fuente: primero una conclusión en lenguaje llano; el
  diagnóstico desplegable separa la salud global del receptor de la actualización
  de la vista y conserva los contadores técnicos cuando hacen falta.
- Salud de fuente en `/api/state` (`source_health` aditivo, schema v3): el navegador sigue haciendo una única llamada y el token no sale del backend.
- Se conservan del pulido previo: números como tablero financiero, historial
  incremental, ETag/304, accesibilidad de tabs y tablas y demo determinista. El
  gráfico usa ahora el tiempo observado en el eje horizontal y corta la línea en
  interrupciones; la frescura sigue avanzando aunque el servicio local no responda.
- El panel de riesgo ilustrativo con valores simulados fue reemplazado por la nota honesta de contrato pendiente: nada de estimaciones sin fórmula aprobada.

## 3. Evolución por incremento

### Incremento 1 — Contrato DDD / Max DD

- El panel de riesgo pasa de placeholder a protagonista del Resumen: es el número por el que el socio pregunta todos los días.
- Semántica de riesgo propia, distinta de profit/loss: uso del límite en porcentaje, estados verde/ámbar/rojo por umbrales del contrato, y siempre texto además de color.
- El "día" como objeto visible: barra de progreso hacia el límite y tiempo real hasta el reset (timezone Madrid).
- Scope por bot/portfolio: si el contrato lo exige, la agrupación por bot deja de ser un filtro de comodidad y pasa a ser navegación. Una vista "Riesgo" dedicada se justifica cuando haya que comparar límites entre varios bots.
- La nota de contrato pendiente se reemplaza por datos del snapshot calculados con
  fórmula aprobada.

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

- **Tema claro y oscuro**: ambos usan los mismos tokens semánticos y respetan la
  preferencia del sistema; la elección manual se conserva localmente.
- **Locale `es-AR`** con hora 24 h, agrupación de miles consistente y signo explícito en resultados.
- **Fuente del sistema**: sin fuentes descargadas; el sistema operativo provee la tipografía (sin `@font-face` ni dependencias).
- **Sin dependencias externas ni build**: HTML/CSS/JS/SVG servidos por la biblioteca estándar; ECharts se incorpora solo en el incremento 3 como archivo local fijado.
- **Navegación**: Resumen, Operaciones, Actividad y (incremento 3) Riesgo — estable a lo largo del tiempo.
- **Filtros que no recargan**: match exacto por Magic Number y selección de
  posiciones u órdenes; se persisten por fuente para no arrastrar silenciosamente
  un filtro entre cuentas. La agrupación por bot sigue diferida.

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

# Dashboard local de riesgo — Análisis de UX y diseño en evolución

**Fecha:** 2026-10-15

**Estado:** guía de diseño del prototipo, vigente hasta que el contrato de métricas (incremento 1) introduzca los valores reales.

**Documentos relacionados:** [Dashboard local de riesgo](../architecture/live-risk-dashboard.md), [Roadmap](live-risk-dashboard-roadmap.md), [Guía de métricas para el socio](guia-metricas-para-el-socio.md).

**Actualización de navegación (19 de octubre de 2026):**
[análisis visual y adaptación](adaptive-navigation-visual-analysis.md).

## 1. Rol de esta pantalla dentro del laboratorio

El dashboard es el primer producto de observabilidad del piloto (mod. 2.4): la ventana de confianza entre el laboratorio y las personas. No es una app de trading ni el sistema; el sistema es la trazabilidad de extremo a extremo desde la idea SQX hasta la decisión de incubación. Tres ejes de diseño sobreviven a todos los incrementos:

1. **Honestidad como lenguaje**: nunca ocultar datos obsoletos, nunca mostrar una métrica cuya fórmula no haya aprobado el socio, distinguir lo verificado de lo declarado.
2. **Dos audiencias, una pantalla**: el trader (detalle operativo, trazabilidad) y el socio no técnico (riesgo en castellano llano).
3. **El diseño es un contrato más**: cada valor derivado debe poder remitir a su fuente (run, deployment, evidence bundle) cuando exista el catálogo.

## 2. Estado del prototipo (actualizado 18 de octubre de 2026)

A partir de tres análisis previos (UX, diseño visual, performance en navegador) se aplicaron en fases y, en octubre de 2026, un rediseño completo según el ADR-0005:

- Inicio en `/`: presentación del proyecto y una entrada al panel, sin formar
  parte de su navegación interna. Las capacidades actuales se separan del roadmap;
  la arquitectura queda en un desplegable secundario. El bloque lateral editorial
  se omite en móvil para priorizar la presentación y el acceso principal.
- Tema claro y oscuro con tokens `light-dark()`: fondo neutro, acento verde apagado,
  fuentes del sistema y superficies planas. Elección persistida sin flash al recargar.
  No se declara conformidad WCAG integral: falta validación con tecnologías de
  asistencia y dispositivos físicos.
- Resumen curado: equity protagonista en tono neutral, resultado abierto con signo,
  color y palabra, balance y margen secundarios en una banda sin tres cajas.
  Fuente resumida, gráfico reciente y contexto de la cuenta; identificador y versión
  del collector en diagnóstico. Nota desplegable de riesgo sin estimaciones.
- Operaciones con tabla de seis columnas en escritorio y composición de tarjeta
  bajo 900 px: instrumento/resultado primero, Magic visible, dirección/volumen y
  detalle secundario. Hora y comentario completos quedan en el detalle móvil.
  Barra de filtros arriba de los resultados, conteos en una línea, sin tarjetas.
  Selector nativo de Magic con «Todos los bots», selección exacta como texto y
  opción retenida «sin operaciones» si desaparece el bot filtrado. Usa navegación
  nativa de teclado; búsqueda avanzada se evaluará si el volumen la justifica.
  Los nodos se actualizan por tipo/ticket sin reconstruir la tabla completa;
  detalle y foco se conservan. Sin scroll interno de altura fija.
- Actividad y estado de la fuente: primero una conclusión en lenguaje llano; el
  diagnóstico desplegable separa la salud global del receptor de la actualización
  de la vista y conserva los contadores técnicos cuando hacen falta.
- Salud de fuente en `/api/state` (`source_health` aditivo, schema v3): el navegador sigue haciendo una única llamada y el token no sale del backend.
- Demo marcada en todas las vistas. Esperar la primera lectura no equivale a cero
  operaciones. Desconexión, antigüedad y recuperación afectan también al resumen
  de salud. El reloj visual no se anuncia cada segundo al lector de pantalla.
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
- Vista de portfolio y rangos temporales: esperan persistencia (incremento 2).
  Los gaps de la ventana actual ya se muestran; no requieren persistencia.
- Selector de fuente completo: espera StocksTrader (incremento 4).

## 6. Riesgos de diseño a vigilar

1. **Regresión a "Excel mental"**: si el socio pide "el número de siempre", resistir con panel, no con planilla.
2. **Sobrecarga en incremento 3**: diez visualizaciones técnicas sin capa de lenguaje espantan al socio; cada gráfico entra con su frase.
3. **Demo como espejo falso**: todo prototipo debe contrastarse con datos reales del terminal antes de darse por cerrado.
4. **Métricas no aprobadas presentadas como válidas**: hasta el contrato, placeholder honesto o "—".

## 7. Verificación reproducible de la interfaz

`tests/browser/dashboard-smoke.cjs` es un check opcional con Node y Chrome aislado
con depuración remota (puerto 9340); no son dependencias del producto ni del
harness rápido. Requiere iniciar primero `scripts/live_dashboard.py --demo --port
8786`. Ejecutar `node tests/browser/dashboard-smoke.cjs`; rechaza una fuente que
no sea demo y limita las direcciones a `127.0.0.1`. Nunca conectar el script al
perfil habitual de Chrome. Para iniciar un perfil de pruebas, pasar a Chrome
`--headless=new --remote-debugging-port=9340` y un `--user-data-dir` nuevo bajo
`_storage/`; al finalizar cerrar solo ese proceso aislado.

Comprueba 32 composiciones (cuatro vistas, dos temas, 1440/768/390/320 px), ancho
real del documento, pie debajo de la tabla, filtros exactos/persistidos, detalle
y foco durante refresh, carga/vacío/desconexión/recuperación y listas largas con
Magic de 64 bits. Guarda capturas y resultados en `_storage/product-design-review/`.
Las pruebas son de Chromium en escritorio con viewport emulado, no certifican
Safari/iOS, lector de pantalla ni Core Web Vitals de usuarios reales.

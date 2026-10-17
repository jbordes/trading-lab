# ADR-0005: Salud de fuente en el dashboard y página de proyecto

**Fecha:** 2026-10-17

**Estado:** proposed

## Contexto

El dashboard mostraba la fuente como una etiqueta de texto sin contexto: en modo
telemetría no se veía el `source_id`, la versión del colector ni la salud del
receptor local, cuyos contadores ya existían en `GET /health` del receptor sin
ser consumidos. Además, el frontend era oscuro únicamente y la única página era
el panel; no existía una entrada que explicara el proyecto a una persona no
técnica.

El usuario pidió una web simple, minimalista y de bajo esfuerzo visual, con tema
claro y oscuro, una página de proyecto además del panel, y que la salud real de
la fuente fuera visible.

## Alternativas consideradas

1. Dejar la UI como estaba y consultar el receptor manualmente cuando hiciera
   falta: no cumple el objetivo de observabilidad para el socio.
2. Exponer la salud del receptor como nuevo endpoint del dashboard y consultarlo
   desde el navegador: introduce una segunda llamada por poll y acopla el
   navegador a la topología del receptor.
3. Agregar `source_health` como campo de `/api/state`, poblado por el propio
   adaptador de telemetría: mantiene una sola llamada, el token sigue fuera del
   navegador y el contrato del dashboard sigue siendo la única frontera visible.

Se eligió la opción 3.

## Decisión

- `/api/state` agrega un campo aditivo `source_health` con `availability`
  (`available`, `unavailable`, `not_applicable`), `source_id`, `collector_version`,
  `checked_at`, `error` y `receiver` (aceptados, duplicados, secuencias
  faltantes, retenidos, sesiones retenidas y `history_status`). `schema_version`
  permanece en `live-dashboard-state-v3`: el cambio es compatible y no obliga a
  adaptar clientes.
- El servicio consulta la salud en cada poll de forma independiente de la
  captura: una falla de salud nunca degrada la captura de cuenta y viceversa.
  Sin proveedor (demo) la salud es `not_applicable` con valores nulos; nunca se
  inventan ceros.
- El frontend se organiza en dos páginas servidas por el mismo proceso: `/`
  (proyecto) y `/dashboard` (panel), con navegación cruzada.
- El sistema de diseño usa tokens `light-dark()` con dos temas completos, un
  script externo bloqueante (`/assets/theme.js`) que aplica la elección guardada
  antes del primer pintado, y CSP intacta (sin estilos ni scripts inline).
- La vista Actividad separa la salud del receptor (global, acumulada desde su
  inicio) de la actualización de la vista (polling del dashboard), y rotula los
  contadores para no confundirlos con salud de una cuenta aislada.

## Consecuencias

- Positivas: la fuente se vuelve observable de extremo a extremo sin relajar la
  CSP ni exponer el token; la página de proyecto da contexto al socio; el tema
  claro cubre preferencias de lectura y el oscuro conserva el modo de terminal.
- Negativas: `light-dark()` requiere navegadores modernos (Chrome 123+, Safari
  17.5+); el frontend suma una página y un script más que mantener; los
  contadores del receptor son globales y su interpretación exige el rótulo
  correspondiente.
- Neutral: la alternancia entre varias fuentes en la interfaz sigue pendiente
  (0E); este ADR no la habilita ni la bloquea.

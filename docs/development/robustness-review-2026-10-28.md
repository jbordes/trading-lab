# Revisión de robustez — 2026-10-28

**Alcance:** lectura de PR #48, commit `a1d6959`. El documento conserva los
hallazgos y propuestas originales; su resolución se registra al final.

## ROB-01 — Alta: plazo efectivo de consulta de historial

**Problema y evidencia:** `account_history` en `sqlite_store.py:429` comparte el
lock con las operaciones `accept/latest` de `persistent_receiver.py:80`. El
plazo de 2 segundos se aplica entre consultas; no interrumpe una consulta SQL ni
la espera por el lock. La simulación con reloj mock de 3 segundos devuelve éxito,
pero no prueba carga real.

**Impacto:** una consulta lenta puede demorar la ingesta y el plazo anunciado no
limita realmente la espera ni la consulta.

**Solución propuesta:** usar una conexión de lectura separada por solicitud en
modo `readonly`, evitar mantener el lock escritor durante consultas, y acotar
tanto la espera mediante `busy_timeout` como el tiempo SQL mediante
`progress_handler`; aplicar además admisión y concurrencia acotadas.

**Aceptación:** la ingesta continúa durante una consulta lenta; al vencer el
plazo se cancela la consulta y no se devuelve una respuesta parcial.

## ROB-02 — Alta: filtrar Magic antes del límite de ciclos

**Problema y evidencia:** en `web.py:334`, `magic_numbers` se aplica después del
límite de 500. El listado de `app.js:811` consulta y filtra en cliente, también
hasta 500 ciclos.

**Impacto:** cuentas con más de 500 ciclos pueden devolver una comparación
incompleta para un EA y la paginación puede omitir filas coincidentes.

**Solución propuesta:** aplicar filtros de cuenta y Magic antes de paginar y
calcular métricas, preservando cobertura y elegibilidad. Resolver el
descubrimiento de EAs con una consulta aparte y acotada.

**Aceptación:** con más de 500 ciclos en la cuenta, filtrar el EA 10 devuelve sus
10 ciclos elegibles; comparación exacta y paginación no omiten resultados.

## ROB-03 — Media: cargo `fee` no visible en el detalle

**Problema y evidencia:** `trade_details.py` incluye `fee` en el neto, pero el
detalle de `app.js:1449` muestra bruto, swap y comisión, no el cargo `fee`.

**Impacto:** los componentes visibles no explican el neto mostrado.

**Solución propuesta:** mostrar el cargo `fee` cuando no sea cero, cuidando no
contabilizarlo dos veces.

**Aceptación:** en un fixture, la suma de los componentes visibles coincide con
el neto del ciclo.

## ROB-04 — Media: indicador de frescura

**Problema y evidencia:** `app.js:1588` calcula frescura con el reloj del
navegador y un intervalo de polling de 5 segundos; el umbral de 10 segundos no
representa la frecuencia del collector. Esta mecánica está confirmada por el
código, pero la causa del comportamiento en vivo no está confirmada.

**Impacto:** «Actualizado hace…» rara vez vuelve a cero o parece desfasado. Que
no vuelva a cero no constituye por sí solo un bug.

**Solución propuesta:** definir la frescura a partir de la captura esperada y su
tolerancia de latencia, distinguir edad de lectura y edad de captura, y combinar
una referencia de edad del servidor con reloj monotónico del cliente.

**Aceptación:** con collector cada 20 segundos y polling cada 5, no se marca
falso estado obsoleto; una caída real sí degrada el indicador.

## ROB-05 — Baja: hora local ausente en detalle de cerradas

**Problema y evidencia:** el detalle de operaciones cerradas en `app.js:1404`
omite la hora local de apertura y cierre, aunque está acordado mostrar las
referencias Broker y Local.

**Impacto:** dificulta interpretar cierres cerca de la medianoche local.

**Solución propuesta:** restaurar la hora local de apertura y cierre en el
detalle, etiquetar ambas referencias y usar un fallback si el offset no se
conoce, sin agrandar la fila principal.

**Aceptación:** un caso que cruza medianoche muestra ambas fechas y referencias;
si falta el offset, queda indicado sin inferirlo.

## Resolución implementada — 2026-10-29

- **ROB-01:** lector SQLite `mode=ro` independiente, `busy_timeout`,
  `progress_handler` y admisión acotada; la ingesta ya no comparte el lock de
  la consulta histórica.
- **ROB-02:** `owner_magics` llega hasta SQLite y se aplica antes del cursor y el
  límite. El descubrimiento usa una consulta `DISTINCT` autenticada y acotada a
  100 Magic Numbers.
- **ROB-03:** el detalle muestra `fee` junto a Swap y Comisión, incluso cuando
  vale cero, sin recalcular ni duplicar el resultado neto.
- **ROB-04:** el servidor publica cadencia de captura, tolerancia y edad. El
  navegador incrementa esa edad con reloj monotónico y ya no usa su reloj civil.
- **ROB-05:** la fila conserva la hora del broker y el detalle agrega hora local
  de apertura y cierre, con fallback explícito cuando falta el offset.

Validación específica: 67 pruebas unitarias afectadas, smoke test de navegación
y filas expandibles, sintaxis JavaScript y Ruff. La suite completa queda en el
CI del pull request según el harness 0.2.

## Cobertura y siguiente paso

En las rutas revisadas no se identificó bypass de autenticación, inyección SQL
ni exposición del token. Esto no equivale a una auditoría de CVEs, dependencias,
carga exhaustiva o de toda la aplicación.

Los cinco hallazgos quedaron implementados en
`fix/pr48-robustness-findings`. La revisión de CVEs, carga exhaustiva y
exposición fuera de loopback continúa fuera del alcance de esta tanda.

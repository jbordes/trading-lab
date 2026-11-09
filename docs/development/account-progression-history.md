# Historial de progresión de cuenta

## Dirección vigente: histórico diario observado

La [ADR-0023](../adr/0023-daily-observed-account-history.md) reemplaza la prioridad
de reconstrucción descrita más abajo. El objetivo es un único gráfico con puntos
diarios observados de balance/equity y muestras recientes, desde el inicio del
seguimiento definitivo. La historia anterior no es requisito actual.

Primer paso terminado: `daily_account_history.py` selecciona el último dato real
de cada día cerrado del broker y sus extremos observados en memoria constante.
Mantiene fechas reales, separa cuentas, tolera reenvíos y recepción desordenada,
y rechaza cierres contradictorios. Un día sin capturas no genera un punto falso.
El PnL de la captura es flotante; el realizado se calcula por separado del ledger.

Estado por pasos:

1. Persistencia diaria y migración explícita 7 → 8: implementadas y probadas en
   bases temporales; [detalle y operación](daily-account-history-storage.md).
2. Consolidación y retención transaccionales: implementadas con vista previa,
   siete fechas recientes, preservación de cierres e identidades de deduplicación.
   La compactación no se activó sobre el piloto ni como tarea automática.
3. Consulta unificada y gráfico: implementados, aún sin activar sobre el piloto.
   `/api/accounts/evolution` combina cierres diarios y el último día observado.
   El Resumen usa una sola evolución de balance/equity, sin selector de
   reconstrucciones. Los períodos van de un día a doce meses.
4. Mantenimiento integrado: el job existente admite consolidación/retención
   opcionales por cuenta, tras una copia verificada, con límites y estados de
   trabajo pendiente. El plan de tarea Windows incluye esa opción explícita.
   Pendientes: migración, actualización supervisada de componentes, instalación
   de la programación y pruebas del flujo/visuales. Todavía no está activo.

Este paso no modifica bases reales, servicios en ejecución ni collectors
instalados. La implementación previa sigue disponible temporalmente durante
la transición; no se ejecuta ni amplía su reconstrucción como parte de este paso.

La consulta es de solo lectura. Los días antiguos que aún no se consolidaron se
informan con `unconsolidated_history`, no se reconstruyen durante cada visita al
dashboard. Si no hay hora del broker verificable, las muestras recientes usan
una ventana explícita de las últimas 24 horas observadas, sin asignarles un día
del broker supuesto. La gráfica mantiene huecos y no crea equity anterior.

## Implementación previa y transición

Estado: código implementado en rama; instalación y aceptación visual pendientes.
Decisión: [ADR-0022](../adr/0022-account-ledger-progression.md).

## Qué muestra el Resumen

El gráfico «Evolución de cuenta» permite elegir:

- **Balance / equity observados:** las capturas realmente guardadas. El contexto
  indica desde cuándo hay muestras en el período. No rellena períodos anteriores.
- **Balance reconstruido:** saldo derivado de movimientos y una referencia
  verificable de saldo. No es una muestra histórica de equity.
- **PnL realizado:** resultado acumulado desde el primer tramo cubierto dentro
  del período pedido, sin sumar depósitos/retiros como ganancias.

Las dos reconstrucciones usan **hora del broker**; las observaciones conservan
UTC. No se mezclan ambas escalas en una misma serie ni se aplica el offset
actual a todo el historial, ya que puede haber cambios horarios estacionales.
Un período solicitado anterior a la cobertura no implica saldo cero ni PnL cero.
Si no está configurado el offset actual del broker, la consulta financiera pide
una fecha de cierre explícita del broker; no supone que su reloj sea UTC.

Los números actuales de balance, equity y PnL flotante del encabezado siguen
siendo los informados por MT5. Las métricas de EAs siguen usando ciclos cerrados
elegibles: esta nueva proyección es del conjunto de la cuenta, incluidas sus
operaciones manuales y los costes contabilizados de posiciones aún abiertas.

## API y definición inicial

```http
GET /api/accounts/progression?source_id=SOURCE&from_server_msc=START&to_server_msc=END
Authorization: Bearer <credencial de lectura de cuenta>
```

`START` es inclusivo y `END` exclusivo; ambos son milisegundos en la escala del
broker, no instantes UTC inferidos. Solo se admite la fuente snapshot autorizada.
Hasta 366 días, 480 puntos y 100.000 movimientos leídos con presupuesto de tres
segundos. No recorre órdenes para calcular saldo y no mantiene un ledger entero
en memoria. Los tickets se resuelven con las mismas reglas durables del registro.

Campos principales:

- `calculation_version: account-ledger-v1`, `time_basis: broker_wall_clock`.
- `status: complete|partial` describe cobertura del período, no calidad del EA.
- `pnl_from_server_msc` declara el inicio efectivo de acumulación de PnL.
- `balance_status` puede ser `available`, `missing_anchor`, `ambiguous_anchor`
  o `incomplete_ledger`; `anchor_server_msc` solo se expone cuando es válida.
- `points`: fecha de fin de intervalo, PnL realizado, flujo neto de capital,
  correcciones y balance reconstruido. Los valores desconocidos son `null`.

Para cada movimiento se utiliza `profit + commission + swap + fee`, con
aritmética decimal durante la agregación. La clasificación inicial es:

| Tipos MT5 | Tratamiento |
| --- | --- |
| Compra/venta (0, 1) | Neto contabilizado como PnL; no se deduplica por Magic ni se filtra intervención manual |
| Cargos, comisiones, intereses, dividendos e impuestos (4, 7–12, 15–17) | Neto contabilizado como PnL de cuenta |
| Balance y bonus (2, 6) | Principal como flujo de capital; costes separados como PnL |
| Corrección (5) | Principal como ajuste explícito; no se cuenta como ganancia de trading |
| Crédito (3) | Principal excluido del balance/PnL; costes contabilizados por separado |
| Deals cancelados (13, 14) o tipos no soportados | Requieren reconciliación; no se publica una reconstrucción como completa |

Esta versión no es una definición definitiva de todas las métricas ni una
atribución de comisiones globales a EAs. Cambios de interpretación requieren
versionar el cálculo y agregar casos de prueba. La reconstrucción depende de
que el broker entregue todos los movimientos de cuenta necesarios.

## Referencia de saldo y compatibilidad

Telemetry `0.3.1` (`#property 1.101`) añade la referencia opcional
`payload.server_time_msc` a snapshots. El campo no cambia SQLite ni las rutas
de ingesta. Mensajes sin el campo siguen aceptándose; no sirven por sí solos
para asociar un saldo con la escala horaria histórica del broker.

El productor evita marcar capturas con reloj de cotización atrasado o que
crucen segundos. La API rechaza formatos inválidos o tiempos separados más de
14 horas y dos segundos del instante UTC de captura. El lector verifica el
hash de la muestra y revisa como máximo las últimas 64 capturas de esa fuente.
Además exige cobertura y ausencia de movimientos dentro del segundo de la
referencia. No supone que `HistoryStartServerTime` sea un saldo inicial.

Con el collector actual `0.3.0`, el PnL puede estar disponible y el balance
reconstruido quedar en `missing_anchor`. Es esperado y explícito, no una razón
para borrar cursores, bases o inventar un depósito inicial.

## Activación supervisada

1. Conservar los binarios actuales y su configuración privada. No rotar tokens,
   renombrar fuentes ni reiniciar EAs de trading para esta funcionalidad.
2. Actualizar API y relay antes de conectar mensajes con el campo nuevo. La API
   debe publicar `/api/accounts/progression` en su OpenAPI; reiniciar el dashboard
   para cargar el adaptador y refrescar el navegador para cargar sus assets.
3. Probar el compilado de Telemetry `0.3.1` en Juampi con supervisión. El test
   nativo actualizado verifica guardas del reloj; compilar no equivale a ejecutarlo.
4. Comprobar ACK central, cobertura de Activity y una referencia válida. No
   reiniciar Activity ni borrar su cursor para crear una referencia de saldo.
5. Verificar las tres series y contrastar balance reconstruido/PnL con un reporte
   MT5 del mismo período, incluidos movimientos de capital si existen.

Los nuevos compilados están aislados bajo
`_storage/collector-builds/20261106-account-progression/` en el workspace raíz.
Telemetry y su test nativo compilaron con cero errores y cero advertencias usando
exclusivamente MetaEditor RoboForex. No se instalaron durante la implementación.

No se importaron las capturas de las bases anteriores. Esa operación, con
identidad, hashes y deduplicación verificadas, queda separada y requiere aprobación.

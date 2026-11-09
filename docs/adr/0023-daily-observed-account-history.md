# ADR-0023: evolución de cuenta observada con histórico diario

**Estado:** accepted
**Fecha:** 2026-11-06

## Contexto

El alcance inicial necesita seguir la cuenta desde el comienzo de la operación
con las estrategias seleccionadas, no reconstruir toda su historia anterior.
El selector entre saldo observado y reconstruido añade complejidad innecesaria.
Conservar indefinidamente todas las capturas frecuentes tampoco es necesario
para mostrar la evolución diaria de la cuenta.

## Decisión

La dirección vigente del gráfico principal es una única evolución de balance y
equity **observados**: puntos diarios anteriores más muestras recientes del día
en curso. Esta decisión reemplaza el uso prioritario de las tres series definido
en la [ADR-0022](0022-account-ledger-progression.md); la reconstrucción histórica
queda diferida, no es requisito para activar el seguimiento definitivo.

- Una fila diaria por cuenta y fecha del broker, con la última captura disponible
  y sus horas reales UTC y broker. No se etiqueta como cotización de medianoche.
- Conservar también mínimos y máximos de balance/equity observados ese día.
  No equivalen a extremos exactos del mercado ni permiten deducir drawdown
  intradía completo u orden de máximos y mínimos.
- El PnL flotante pertenece a la captura. El PnL realizado diario procede del
  ledger de transacciones y su cobertura; no se calcula restando balances.
- No consolidar como cerrado el día actual, inventar días sin observaciones ni
  asumir que la fecha local del servidor es la fecha del broker.
- Capturas tardías pueden corregir el punto diario de manera idempotente.
- La consolidación y retención viven en el backend central, no en los collectors
  ni en el navegador; se conserva una sola base de negocio.
- Antes de eliminar muestras se confirma su consolidación durable. Mantener
  inicialmente un margen de siete días de muestras recientes; el inicio efectivo
  de la eliminación requiere implementar y validar la guarda transaccional.
- No eliminar órdenes, deals, cobertura ni identidades de deduplicación como
  parte de esta política de muestras de cuenta.

## Alternativas consideradas

- Retener todo indefinidamente: innecesario para el gráfico diario solicitado.
- Reconstruir balance y equity desde transacciones: más complejidad; el equity
  pasado no se recupera fielmente solo con deals.
- Crear otro collector o base: duplica responsabilidades sin necesidad.
- Guardar solo el último valor: impide observar el progreso histórico.

## Consecuencias

Primer paso implementado: reducción pura de un día cerrado en memoria constante,
independiente del orden de recepción, con separación de cuentas y rechazo de
valores no finitos o cierre ambiguo. No persiste ni borra datos todavía.

Siguientes pasos: tabla diaria en SQLite central con migración explícita;
consolidación durable y limpieza protegida; consulta que combine diario y
reciente sin duplicar días; simplificación del gráfico; activación supervisada.
No se despliega, migra ni elimina información operativa en este primer paso.

El cambio de collector para aportar fecha del broker sigue pendiente de
instalación. Capturas sin referencia temporal válida no se asignan a un día del
broker mediante offsets actuales supuestos. La definición del comienzo del
seguimiento definitivo se mantiene separada de los datos de prueba actuales.

# ADR-0022: progresión histórica de cuenta sin inventar equity

**Estado:** accepted
**Fecha:** 2026-11-06
- Alcance: implementación en `feature/account-progression-history`, sin desplegar
  automáticamente ni importar datasets anteriores.

## Contexto

Recuperar órdenes y deals no recupera las muestras históricas de equity. La
base nueva del piloto conserva snapshots desde el 06/11, aunque su ledger de
actividad cubre octubre. Una cuenta conectada después de comenzar a operar
debe poder mostrar evolución histórica sin confundir movimientos de capital,
beneficios, muestras observadas y reconstrucciones.

## Decisión

Conservar la API de muestras observadas y añadir una proyección de ledger de
cuenta, calculada en lectura sobre la misma SQLite central. No se crea otra
base de negocio, caché en memoria permanente ni migración de esquema.

- `/api/accounts/history` conserva balance/equity observados en UTC.
- `/api/accounts/progression` presenta PnL realizado, flujos de capital,
  correcciones y, cuando sea verificable, balance reconstruido.
- La progresión usa la escala de reloj del broker y lo indica explícitamente;
  no deduce offsets históricos ni inventa conversión UTC/local.
- El cálculo se identifica como `account-ledger-v1`. Es por cuenta, no sustituye
  las métricas por EA basadas en ciclos cerrados elegibles.
- No se reconstruye equity desde deals ni se deriva drawdown de equity de esta
  proyección. La ausencia de observaciones históricas queda visible.

El balance necesita una referencia de saldo con fecha del broker. Telemetry
`0.3.1` añade `payload.server_time_msc` de forma opcional, compatible con mensajes
anteriores. Se publica solo si los relojes de cotización/servidor coinciden y la
captura no cambia de segundo. El receptor valida forma y plausibilidad temporal.
El proyector descarta como referencia un segundo en el que exista un movimiento:
la resolución del reloj no permite afirmar si el saldo es anterior o posterior.
La cobertura debe alcanzar también el segundo de referencia.

Ausencia de referencia, huecos, conflictos o movimientos cuya semántica no
esté soportada producen estados explícitos y valores `null`, nunca ceros o
equity fabricada. Una referencia anterior al fin pedido no extrapola saldos
posteriores. El PnL comienza en el primer tramo cubierto y declara esa fecha.

## Alternativas consideradas

- Usar solo snapshots: no permite analizar cuentas anteriores a TradingLab.
- Sumar trades sobre un saldo inicial supuesto: confunde capital y beneficio.
- Equiparar balance con equity en períodos sin capturas: información falsa.
- Reconstruir equity con cotizaciones históricas: simulación independiente,
  fuera del alcance; necesitaría precios, costes y reglas de valoración fiables.
- Importar las capturas anteriores: conserva evidencia útil donde exista,
  pero requiere una operación separada y aprobada; no resuelve períodos nunca
  observados ni se ejecuta implícitamente.

## Consecuencias

La respuesta está acotada a 480 puntos, hasta 366 días, lectura paginada y plazo
cooperativo de tres segundos. El coste depende del ledger; superar presupuesto
produce indisponibilidad explícita, no una curva parcial declarada completa.
La instalación de Telemetry nuevo requiere actualizar primero API y relay para
aceptar el campo opcional; nunca se sustituye un collector activo automáticamente.

Definición y límites operativos: [historial de cuenta](../development/account-progression-history.md).

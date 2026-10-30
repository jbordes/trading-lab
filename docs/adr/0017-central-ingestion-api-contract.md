# ADR-0017: Contrato central y transporte durable de telemetría

**Estado:** accepted

**Fecha:** 2026-10-30

## Contexto

El programa remoto alojará inicialmente API y SQLite en una Mac; los EAs siguen
en la VPS. La desconexión entre máquinas exige distinguir recepción local de
persistencia central.

## Alternativas consideradas

1. Envío directo del EA a la Mac: menos procesos, pero sin cola local durable.
2. Relay con outbox durable: permite confirmar localmente y reintentar tras cortes.
3. SQLite compartida por red: introduce dependencia del filesystem remoto.

## Decisión

Adoptar como objetivo el relay local y API central con SQLite local a su backend.
Preservar los contratos HTTP v1/v2, identidad original e idempotencia. Separar
ACK local y central; provisionar identidades fuera de la ingesta. No ofrecer
operaciones de trading ni bajas arbitrarias a los collectors.

El [contrato central](../architecture/central-ingestion-api-contract.md) define
los requisitos y distingue capacidades existentes de las todavía pendientes.
Cada receptor ofrece documentación estática en `/docs` y catálogo en `/docs.json`.

## Consecuencias

- El relay requiere disco, límites y diagnóstico de atrasos.
- Separación de credenciales v1 y admisión de backlog deben resolverse antes del
  transporte remoto. No basta con cambiar la dirección de escucha.
- Este ADR no activa servicios ni migra datos; esos pasos requieren validación
  y aprobación operativa posterior.

## Reemplaza

No reemplaza ADR previos. Amplía la dirección de despliegue; conserva las reglas
de retención y la operación local hasta completar el programa remoto.

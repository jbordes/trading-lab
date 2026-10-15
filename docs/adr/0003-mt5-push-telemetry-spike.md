# ADR-0003: Spike de telemetría push desde MT5

**Estado:** accepted

**Fecha:** 2026-10-16

## Contexto

El adaptador Python actual consulta un terminal MT5 co-localizado mediante IPC y
es adecuado para el dashboard local. La arquitectura futura mantiene TradingLab
y las terminales del socio en zonas separadas, sin administración remota entre
ellas. Un colector MQL5 ejecutado dentro del terminal puede emitir observaciones
por HTTPS y reaccionar a cambios sin depender exclusivamente del polling Python.

El colector compilado estudiado como referencia declara ser de solo lectura, pero
sin su fuente no puede auditarse y su intervalo de dos minutos no sirve para el
control operativo de drawdown buscado por TradingLab.

## Alternativas consideradas

1. Conservar exclusivamente la API Python: mínima complejidad, pero exige
   co-localización y mantiene la dependencia del IPC del terminal.
2. Adoptar el `.ex5` de referencia: acelera la prueba, pero no permite verificar
   permisos, payload ni ausencia de acciones de trading.
3. Construir un spike propio con fuente `.mq5`, receptor loopback separado y
   contrato mínimo versionado, para compararlo con Python antes de decidir una
   topología remota.

## Decisión

Se ejecutará la tercera alternativa como experimento reversible. El spike solo
admitirá una terminal demo, un endpoint loopback, memoria acotada y un token de
ingestión. El dashboard conservará su frontera HTTP exclusivamente de lectura.

La fuente MQL5 no contendrá funciones de trading, DLLs ni comandos entrantes. El
receptor validará autenticación, tamaño, schema, identificadores, secuencias e
idempotencia. Ningún endpoint público, persistencia productiva o despliegue en la
VPS del socio forma parte de esta decisión.

## Consecuencias

- Se podrá medir completitud, latencia y recuperación frente al adaptador Python.
- MQL5 se incorpora de forma acotada porque es el runtime nativo del terminal.
- Será necesario mantener un contrato entre dos lenguajes y compilar con
  MetaEditor durante la prueba manual.
- Un resultado negativo permite retirar el componente sin afectar el dashboard.
- Adoptar telemetría remota requerirá aceptar un ADR posterior con autenticación,
  transporte, retención y operación definidos.

## Reemplaza

No aplica. Complementa ADR-0002 sin modificar su frontera read-only.

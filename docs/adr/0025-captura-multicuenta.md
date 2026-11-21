# ADR-0025 · Atribución de telemetría durante la captura

**Estado:** proposed

**Fecha:** 2026-11-20

## Contexto

La misma terminal de MT5 puede rotar entre cuentas registradas. El relay puede entregar un lote después de un cambio de sesión. El instalador anterior requería configurar una cuenta en los presets de cada EA.

## Decisión

En esta versión el catálogo central identifica cada cuenta con servidor y login completo. El modo se comprueba al resolver la identidad. Un collector que observa una sesión válida obtiene una fuente para esa cuenta y conserva esa fuente en el lote. La cola durable asocia la fuente al destino. La credencial del collector acredita su terminal y rol ante el relay. El relay se autentica ante la API con una credencial de su instalación para cada contrato.

El dashboard usa el catálogo central y solicita los datos de una sola cuenta por vista. La API abre una base nueva con el catálogo y las tablas de historial. El esquema anterior sigue disponible para las herramientas que lo usan.

## Alternativas consideradas

Se consideró exigir una asignación de cuenta a terminal. La identidad que MT5 entrega al capturar y la comprobación del catálogo permiten operar con las cuentas registradas desde distintas terminales sin mantener esa asignación.

## Consecuencias

Agregar una cuenta permite capturarla desde cualquier terminal preparada. Las cuentas desconocidas requieren alta manual. La fecha de inicio de Activity y el cursor son propios de la cuenta. El operador puede distribuir servicios usando URLs completas y mantener un relay de loopback en cada equipo con MT5. El reemplazo de la instalación estable queda sujeto a aceptación manual.

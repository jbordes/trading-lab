# Persistencia y composición aisladas de telemetría v2

**Estado:** implementado como componente opt-in; no conectado al receptor ni al
dashboard.

## Objetivo y límites

Este incremento convierte las reglas de admisión v2 en evidencia durable y permite
componer una cuenta sin mezclar estado vivo con actividad histórica. No migra ni
modifica bases v1, no instala collectors, no abre rutas HTTP y no cambia la base
operativa. `create_v2_database` solo crea un archivo nuevo solicitado
explícitamente y nunca reemplaza uno existente.

El esquema vive en `src/tradinglab/telemetry/sqlite_store_v2.py`, usa
`PRAGMA user_version = 2` y se abre únicamente si coincide exactamente con el
esquema esperado. Una base v1 no se acepta como v2. La estrategia de migración se
definirá antes de activar el nuevo receptor; crear una base de prueba no constituye
una migración de producción.

## Identidades y seguridad

SQLite conserva cuentas internas, identidad MT5 enmascarada y dos fuentes con rol
`live` o `activity`. Existe como máximo un productor primario por cuenta y rol;
cuenta y rol de una fuente son inmutables. Los tokens nunca se guardan en la base.
La autenticación permanece en `V2ProducerDirectory` y la escritura durable vuelve
a comprobar cuenta, fuente, rol e identidad sobre el mensaje revalidado.

## Escritura transaccional

Cada mensaje se canoniza y guarda con hash SHA-256, captura, recepción y procedencia.
La transacción `BEGIN IMMEDIATE` decide de manera atómica:

- reintento idéntico: devuelve `duplicate` sin cambiar la recepción original;
- misma fuente/sesión/secuencia con otro contenido: conflicto y rollback;
- `live_snapshot` o `heartbeat` desconocido por debajo del máximo: rechazo;
- `activity_batch` histórico desconocido: aceptación fuera de orden;
- salto hacia delante: aceptación con cantidad de secuencias faltantes como
  diagnóstico, nunca como cobertura.

Las pruebas cubren concurrencia y fallos antes o después de un commit. Si la
confirmación fue ambigua, reabrir y reenviar produce exactamente una fila.

## Lectura y composición por cuenta

`account_evidence` lee fuentes y mensajes dentro de una única transacción y antes
de devolverlos verifica contrato, hash, columnas, identidad y rol. La composición
pura de `composition_v2.py` produce:

- estado vivo más reciente admisible, independiente de heartbeat;
- diagnóstico de ambos flujos y heartbeat por rol;
- órdenes y deals históricos por ticket, sin mezclarlos entre sí;
- correcciones por tiempo de observación, sin retroceder por orden de llegada;
- cobertura unida solo desde colecciones `complete`;
- estados `error` y `truncated` sin extender cobertura;
- conflictos entre sesiones, conservando la última evidencia no ambigua;
- rechazo de capturas futuras para estado y cobertura.

La composición no afirma que ambos flujos formen una fotografía atómica. Una orden
cancelada sigue siendo actividad, no un trade ni P/L. Las fórmulas de métricas y
agrupación de ejecuciones continúan dependiendo del contrato acordado con el socio.

## Restricción de rendimiento

La lectura actual verifica y compone todos los mensajes de la cuenta. Es adecuada
para demostrar semántica con fixtures y volúmenes piloto, pero es O(n) y no debe
ejecutarse en cada refresco del dashboard cuando la historia crezca. Antes de
conectar HTTP se diseñarán proyecciones incrementales o cursores durables, con
pruebas que demuestren equivalencia respecto de esta composición de referencia.

## Próximos pasos seguros

1. Diseñar provisión y migración explícitas para una base piloto, sin tocar v1.
2. Añadir proyecciones incrementales y medir lectura/escritura con datos realistas.
3. Exponer un receptor v2 opt-in con credenciales separadas, manteniendo v1 activo.
4. Implementar los dos collectors y validarlos primero en demo con rollback.
5. Adaptar la API del dashboard después de aprobar su contrato de vista.

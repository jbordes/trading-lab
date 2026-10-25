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
como referencia semántica, pero es O(n) y no debe ejecutarse en cada refresco del
dashboard. Las vistas históricas crecientes se resolverán con consultas paginadas
y, cuando haga falta, proyecciones durables actualizadas de forma idempotente. No
se mantendrá todo el historial proyectado en RAM. Una caché futura deberá ser
acotada, descartable y reconstruible desde SQLite.

## Próximos pasos seguros

1. La provisión piloto aislada ya está implementada con vista previa y creación
   explícita. La transición desde v1 y cualquier migración siguen pendientes.
2. Diseñar proyecciones durables solo para consultas v2 concretas y validarlas con
   datos sintéticos de volumen y operaciones reales anonimizadas.
3. El receptor v2 opt-in ya expone `/v2/telemetry` solo en loopback, con
   credenciales separadas en variables de entorno y sin modificar el receptor v1.
   Falta conectarlo a collectors v2 y exponer lecturas para el dashboard.
4. Implementar los dos collectors y validarlos primero en demo con rollback.
5. Adaptar la API del dashboard después de aprobar su contrato de vista.

## Operación piloto

La provisión se revisa primero sin crear archivos:

```text
uv run python scripts/provision_telemetry_v2_db.py [metadatos y fuentes]
```

`--apply` crea una base nueva bajo `_storage/`; nunca abre ni migra una base v1.
El receptor requiere esa ruta y la cuenta interna mediante `--sqlite-db` y
`--account-id`. Lee credenciales ASCII distintas, de al menos 24 caracteres,
desde `TRADINGLAB_TELEMETRY_LIVE_TOKEN` y
`TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN`, y las conserva solo en memoria:

```text
uv run python scripts/telemetry_receiver_v2.py --sqlite-db <ruta> --account-id <id>
```

La ingesta vive en `http://127.0.0.1:8777/v2/telemetry` por defecto y salud en
`/health`. Este procedimiento prepara el backend; no instala collectors ni
genera actividad por sí solo.

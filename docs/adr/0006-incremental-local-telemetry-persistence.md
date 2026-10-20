# ADR-0006: Persistencia local incremental de telemetría

**Estado:** accepted

**Fecha:** 2026-10-20

## Contexto

El buffer actual del receptor no conserva observaciones tras reiniciar. El usuario
aprobó comenzar con SQLite y avanzar por bloques pequeños, sin modificar las
terminales ni anticipar las fórmulas de métricas pendientes del socio.

## Alternativas consideradas

1. Mantener solo memoria: simple, pero pierde las observaciones al reiniciar.
2. Crear ahora una base remota y un modelo completo de trades: añade operación y
   obliga a resolver reglas de negocio que todavía no están aprobadas.
3. Incorporar SQLite local, primero como componente aislado y luego como journal
   de mensajes validados, separado de las proyecciones de análisis.

## Decisión

Adoptar la tercera alternativa. La primera entrega crea únicamente el esquema
versionado de cuentas, fuentes y mensajes, sin conectar persistencia al receptor.
La creación exige una ruta nueva explícita; nunca sobrescribe bases existentes
ni ejecuta migraciones implícitas. Los datos operativos vivirán en `_storage/`.

Una cuenta conserva identidad independiente de la terminal. Una fuente vincula
una instalación del collector con una cuenta y no se reasigna. Alternar cuentas
requiere seleccionar explícitamente su fuente y abrir una nueva sesión de captura.
Esto precisa ADR-0004, sin habilitar cambios automáticos de cuenta ni escritura MT5.

La ingesta durable, autorización por fuente, provisión operativa, recuperación,
retención y backups siguen siendo entregas pendientes. No afirmar que la captura
actual persiste por el solo hecho de disponer del esquema.

## Consecuencias

No se agrega una dependencia externa: se usa sqlite3 de Python. El esquema impone
relaciones y unicidad, pero no sustituye la validación del contrato ni la futura
API de almacenamiento. Cada conexión futura deberá activar claves foráneas.

La creación usa una transacción y synchronous FULL; la política de apertura,
concurrencia y recuperación se verificará antes de integrar el receptor. Las
pruebas del primer bloque usan exclusivamente bases temporales. No hay todavía
garantía probada frente a corte eléctrico ni recuperación histórica completa.

El alcance y próximos pasos están en el
[diseño de persistencia](../development/mt5-sqlite-field-map.md).

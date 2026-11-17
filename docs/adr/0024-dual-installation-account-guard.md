# ADR-0024: Instalaciones paralelas con guarda de cuenta

**Estado:** proposed
**Fecha:** 2026-11-17

La implementación está en ramas. El flujo estable local fue probado manualmente en demo; la validación con cuenta real y la integración mediante PR siguen pendientes. La variante remota queda aplazada.

## Contexto

Las ramas paralelas preparan dos topologías piloto: stable local con dos bases y remote con base central y relay durable. Ambas necesitan configuración reproducible, continuidad segura de instalaciones y conexión manual de los collectors a MT5.

## Decisión

- Compartir el contrato editable y la CLI bootstrap, manteniendo un adaptador por arquitectura. El JSON editable tiene exactamente `login_id`, `server`, `currency`, `account_mode`, `snapshot_port`, `activity_port`, `dashboard_port`, `central_port`, `broker_utc_offset_minutes` e `history_date`; el archivo se llama `<login_id>.json`. `login_id` contiene el login completo por solicitud explícita del usuario. No incluye `label`, `account_id`, `source_id` ni `login_masked`.
- Autodescubrir archivos JSON con nombre base numérico en `_storage/installation` dentro del repositorio o en su carpeta padre solo cuando haya exactamente uno; con cero o varios resultados, el usuario selecciona **Abrir JSON**.
- Derivar internamente la etiqueta nueva del login completo y crear IDs `mt5-{login}-{sha256(server)[:8]}-{state|live|activity}` para distinguir brokers. Al reanudar una instalación existente, conservar sus IDs y etiqueta heredados, sus bases y sus tokens; validar únicamente los valores públicos del runtime. No tomar secretos del JSON editable.
- Persistir el identificador de layout y rechazar al arrancar una instalación que no corresponda al checkout. Las bases, endpoints e instalaciones de stable y remote no se intercambian; no se define migración.
- Una configuración nueva del asistente usa REAL por defecto; marcar **Es Cuenta Demo** selecciona DEMO. JSON cargado e instalaciones existentes conservan su modo. Los collectors siguen teniendo DEMO por defecto; la CLI exige `--allow-real-account` para REAL y los presets autorizan la identidad exacta.
- Exigir coincidencia exacta de login y servidor con la identidad de MT5. Mantener `ExpectedDemoLogin` y `ExpectedDemoServer` por compatibilidad. Los collectors son de solo lectura y no invocan APIs de trading.
- Mantener secretos de tokens únicamente en presets privados y configuración de entorno. No imprimirlos ni copiarlos desde archivos `.env` existentes. El login completo sí forma parte del JSON editable solicitado.
- La interfaz muestra progreso en consola. El usuario confirmó el flujo completo en demo el 2026-11-17; la prueba con cuenta real y en otro servidor sigue pendiente.

## Alternativas consideradas

- Duplicar instaladores por sistema operativo: rechazado; el contrato Python/CLI común cubre los servicios portables y conserva diferencias con adaptadores.
- Migrar ahora main a la plataforma remote: rechazado; las topologías y sus pruebas siguen en ramas paralelas hasta revisión e integración humana.
- Inferir o solicitar login enmascarado: rechazado; el usuario pidió el login completo en el JSON editable, mientras que los presets y tokens permanecen protegidos.

## Consecuencias

- Los cambios al contrato común deben replicarse en ambas ramas y cada adaptador requiere sus propias pruebas.
- La unificación futura requiere revisar layout, almacenamiento, endpoints y compatibilidad de datos.
- Esta decisión no declara el despliegue realizado ni que CI full haya pasado. La validación humana y la integración del piloto continúan pendientes.

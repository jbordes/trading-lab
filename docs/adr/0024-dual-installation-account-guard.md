# ADR-0024: Instalaciones paralelas con guarda de cuenta

**Estado:** proposed
**Fecha:** 2026-11-17

La implementación está en ramas y pendiente de validación humana.

## Contexto

Las ramas paralelas `main` y PR 67 preparan dos topologías piloto distintas: una instalación local stable con dos bases y otra remote con base central y relay durable. Ambas necesitan un procedimiento seguro y reproducible de instalación y de conexión del collector a MT5.

## Decisión

- Compartir un contrato de configuración `installation.example.json` y una CLI bootstrap; mantener un adaptador de backend por arquitectura.
- Persistir un identificador de layout y rechazar al arrancar una instalación cuyo layout no corresponda al checkout. Bases, endpoints e instalaciones de las dos arquitecturas no se intercambian; no se define migración entre ellas.
- Usar DEMO como único modo predeterminado. Una cuenta REAL requiere `--allow-real-account` explícito tanto al instalar como `AllowRealAccount=true` en el EA.
- Exigir coincidencia exacta del login y servidor esperados con la identidad del terminal. Mantener los nombres `ExpectedDemoLogin` y `ExpectedDemoServer` por compatibilidad. Los collectors son de solo lectura y no invocan APIs de trading.
- Crear tokens solo en el destino nuevo, privado y fuera de Git. No imprimir secretos ni copiar credenciales de archivos `.env` existentes.

## Alternativas consideradas

- Duplicar instaladores por sistema operativo: rechazado; el contrato Python/CLI común cubre los servicios portables y conserva diferencias mediante adaptadores.
- Migrar ahora `main` a la plataforma remote: rechazado; las topologías y sus pruebas siguen en ramas paralelas hasta revisión e integración humana.
- Habilitar cuentas reales sin opt-in explícito: rechazado por el riesgo de adjuntar el collector a una cuenta no prevista.

## Consecuencias

- Las correcciones al contrato común deben replicarse en ambas ramas y cada adaptador requiere sus propias pruebas.
- La unificación futura no será automática: requiere revisar el layout, almacenamiento, endpoints y compatibilidad de datos.
- Esta decisión no afirma que el despliegue esté realizado ni que CI full haya pasado. La validación humana y la integración del piloto continúan pendientes.

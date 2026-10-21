# ADR-0009: Postergar backup externo y restauración hasta producción

**Estado:** accepted

**Fecha:** 2026-10-21

## Contexto

El piloto demo ya dispone de persistencia SQLite, copia local verificable y una
retención conservadora. Todavía no usa información crítica y sus datos pueden
descartarse y volver a generarse. Configurar ahora un proveedor externo y ensayar
una restauración retrasaría la validación del flujo real sin reducir un riesgo
operativo relevante para esta etapa.

## Alternativas consideradas

1. Exigir backup externo y restauración antes de cualquier captura persistente.
2. Permitir el piloto demo con copia local y tratar sus datos como descartables;
   reservar el backup externo y la restauración para la preparación productiva.
3. Omitir indefinidamente ambos controles.

## Decisión

Se adopta la segunda alternativa. El piloto puede usar SQLite con datos demo sin
backup fuera de la VPS ni prueba de restauración. La pérdida de esos datos se
acepta explícitamente y no debe bloquear el desarrollo ni las pruebas.

Antes de usar cuentas reales, declarar datos irremplazables o depender del
histórico para decisiones operativas, se deberán seleccionar un destino externo,
proteger sus credenciales, definir RPO/RTO y completar una restauración verificada.
Esos controles siguen siendo obligatorios para producción.

Esta decisión no autoriza borrados automáticos. Continúan vigentes la retención
del piloto, las copias locales antes de migraciones y la aprobación humana para
eliminar datos.

## Consecuencias

La validación SQLite puede comenzar con operaciones demo disponibles. Una falla
de la VPS puede obligar a repetir el piloto. La documentación debe distinguir
claramente evidencia descartable de piloto y datos protegidos de producción.

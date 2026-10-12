# ADR-0001: Harness portable y flujo de cambios controlado

**Estado:** accepted

**Fecha:** 2026-10-12

## Contexto

TradingLab comienza a incorporar scripts y código después de una fase documental. Su operación principal ocurre en Windows, pero el repositorio también se utilizará desde macOS o Linux. El laboratorio necesita controles tempranos sobre secretos, artefactos pesados, documentación y trazabilidad sin copiar un harness diseñado para una aplicación web diferente.

## Alternativas consideradas

1. Copiar el harness completo de Fenix: ofrecía más automatización inmediata, pero incorporaba Node.js, Docker, agentes y procedimientos ajenos al laboratorio.
2. Implementar el núcleo en PowerShell: simplificaba la VPS actual, pero trasladaba fricción a macOS y Linux.
3. Usar Python con uv y validaciones incrementales: agrega un bootstrap pequeño, pero mantiene una única implementación portable y sirve como base para futuros manifests, hashes e importadores.

## Decisión

Adoptar Python 3.14 administrado mediante uv como núcleo del Harness 0.1. Los cambios se realizan en ramas cortas, se validan localmente y en CI sobre Windows, macOS y Linux, y llegan a `main` mediante pull request y merge humano.

La bitácora registra la jornada con independencia de las features y se mantiene directamente en `main` mediante una excepción limitada a archivos fechados el día actual. Las entradas anteriores son inmutables. Las decisiones durables se registran como ADR y las acciones sensibles continúan requiriendo aprobación humana.

## Consecuencias

- Existe un único comportamiento de validación entre sistemas operativos.
- La VPS y cada equipo deben preparar uv una vez; uv puede provisionar Python.
- CI consume tres jobs paralelos, inicialmente pequeños.
- La bitácora conserva el trabajo diario sin contaminar ni quedar acoplada a las ramas de código.
- Backups, schemas, fixtures y controles de artefactos se incorporarán cuando existan objetos reales sobre los cuales validarlos.

## Reemplaza

No aplica.

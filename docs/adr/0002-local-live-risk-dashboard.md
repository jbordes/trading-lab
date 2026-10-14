# ADR-0002: Dashboard local de riesgo con fuentes de solo lectura

**Estado:** accepted

**Fecha:** 2026-10-14

## Contexto

El informe Excel de incubación dejó de ser el entregable prioritario. Los socios necesitan observar cuentas y bots con pocos segundos de demora y ampliar progresivamente las métricas. Las fuentes iniciales no son uniformes: algunas cuentas se consultarán mediante un terminal MT5 y otras podrán usar la API REST de StocksTrader.

El piloto tiene pocos datos y un único usuario local. Crear desde el inicio PostgreSQL, TimescaleDB, un modelo completo de trading y un frontend con build agregaría mantenimiento antes de validar las fuentes y las definiciones de riesgo. Las fórmulas definitivas serán provistas por el socio.

## Alternativas consideradas

1. Continuar con Excel como producto principal: simple para el procedimiento anterior, pero inadecuado para observación frecuente e integración de múltiples fuentes.
2. Construir desde el inicio base productiva, modelo canónico amplio y frontend especializado: habilita escala, con un coste prematuro de diseño y operación.
3. Implementar un corte vertical local con adaptadores de solo lectura, contrato mínimo de snapshot, memoria acotada y evolución guiada por métricas confirmadas.

## Decisión

Se adopta la tercera alternativa.

El primer incremento será una aplicación enlazada exclusivamente a `127.0.0.1`. Consultará MT5 mediante una interfaz que solo expone `initialize`, `account_info`, `positions_get`, `orders_get`, `last_error` y `shutdown`. No contendrá operaciones de trading. Se recomendará usar contraseña de inversor incluso cuando el código ya limite su superficie a lecturas.

El estado reciente se conservará en un buffer en memoria. La persistencia histórica se decidirá cuando las fórmulas aprobadas demuestren qué frecuencia y retención necesitan; SQLite será la primera opción local y PostgreSQL quedará reservado para concurrencia o centralización real.

El segundo adaptador será StocksTrader REST. No se asumirá streaming ni acceso a cuentas MT5 mediante esa API. Antes de cuentas reales se deberá confirmar o compensar la ausencia de credenciales con privilegios exclusivamente de lectura.

Las métricas se implementarán solo desde definiciones aprobadas por el socio. La interfaz inicial mostrará observaciones directas. Apache ECharts es la opción prevista cuando se incorporen distribuciones y matrices; el primer gráfico simple puede usar SVG local para no introducir todavía un toolchain JavaScript ni código remoto.

## Consecuencias

- Se obtiene valor visible y comprobable sin desplegar infraestructura ni administrar una base.
- MT5 y StocksTrader permanecen detrás de adaptadores diferentes y reemplazables.
- Reiniciar el MVP descarta su buffer visual; esto es deliberado y se documentará en la interfaz.
- Las métricas históricas requerirán persistencia antes de considerarse productivas.
- La aplicación no se expondrá en red ni se usará con cuentas reales hasta completar autenticación, secretos, retención y revisión de permisos.
- El Excel queda como posible exportación futura, no como fuente de verdad ni entregable prioritario.

## Reemplaza

Reemplaza la decisión operativa de usar el workbook de incubación como entregable v1 descrita en `docs/architecture/mt5-incubator-report-analysis.md`.

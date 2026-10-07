# Bitácora — Cobertura de TradingLab 1.0 en la arquitectura propuesta

**Fecha:** 8 de octubre de 2026

**Objetivo:** comparar las capacidades observadas en TradingLab 1.0 con la Arquitectura 2.2 y comprobar que el modelo propuesto no omita información o procedimientos necesarios para el trabajo real.

## Trabajo realizado

- Se revisaron conjuntamente la estructura histórica, los proyectos SQX, el expediente de estrategias, el pipeline de incubación y la documentación de arquitectura 2.2.
- Se construyó una matriz de cobertura por capacidad, evitando equiparar carpetas con responsabilidades.
- Se clasificaron las prácticas de 1.0 entre capacidades valiosas, problemas accidentales y material que requiere migración controlada.
- Se identificaron huecos de representación y se incorporaron formalmente a Arquitectura 2.3.
- Se creó un documento independiente de comparación para revisión con los socios.

## Cobertura que ya existía en 2.2

- proyectos, estrategias, versiones, experimentos y runs;
- datasets, engines, environments, métricas y artefactos;
- manifiestos reproducibles, hashes e ingestión idempotente;
- preparación, compilación y validación SQX–MT5;
- BotBuild, Deployment, JobPackage y EvidenceBundle;
- separación de las VPS y MT5 Runner local;
- Google Drive como transporte no autoritativo;
- seguridad, backups, ADR, bitácoras, API/CLI/MCP y plan incremental.

## Huecos detectados en 2.2

1. Las etapas del embudo SQX y sus conteos no tenían entidad explícita.
2. Las cohortes, snapshots de databank, selecciones y portfolios no podían versionarse como conjuntos.
3. Magic Numbers, IDs SQX y nombres históricos no tenían un modelo de aliases con alcance y vigencia.
4. Las decisiones humanas de selección, rechazo o invalidación estaban documentadas, pero no modeladas uniformemente.
5. Los outputs derivados como XLSX, SQLite y resúmenes no tenían lineage formal hacia todas sus fuentes.
6. Una incubación prolongada necesitaba admitir varios lotes de evidencia sin representar cada snapshot como una incubación nueva.
7. El registro manual ligero y el workspace operativo, incorporados en la guía 1.3, aún no figuraban en el documento principal.
8. La promoción desde un proyecto hacia conocimiento, plantillas, componentes o estrategias reutilizables requería un procedimiento explícito.

## Cambios formalizados en Arquitectura 2.3

- `StageRun` para etapas como Build, OOS, HBP, Monte Carlo, SPP o RTRS.
- `StrategySet` y membresías para cohortes, selecciones y portfolios.
- `Assessment` para decisiones humanas o automáticas y su supersesión.
- `ExternalIdentifier` para aliases externos sin convertirlos en claves primarias.
- `ArtifactLineage` para originales, transformaciones y derivados.
- Múltiples evidence bundles u observation batches en una incubación.
- `projects/<slug>/records/` durante el piloto y `_storage/projects/<slug>/` como workspace humano no versionado.
- Procedimientos para workflow manual por etapas, portfolio, evidencia incremental y promoción de activos.
- Nuevos criterios de aceptación del piloto y decisiones abiertas.

## Documentos creados o modificados

- `docs/architecture/tradinglab-architecture-v2.md`: versión 2.2 → 2.3.
- `docs/architecture/tradinglab-architecture-v2.pdf`: regenerado desde la versión 2.3.
- `docs/architecture/architecture-v1-vs-v2.3-coverage.md`: nuevo.
- `docs/architecture/architecture-v1-vs-v2.3-coverage.pdf`: generado en esta sesión.
- `README.md`: arquitectura vigente y enlaces actualizados.

## Conclusión

Todas las capacidades observadas en TradingLab 1.0 tienen ahora un destino y una fuente de autoridad en la arquitectura propuesta. La cobertura documental no reemplaza la validación operativa: el control definitivo será migrar una estrategia real de punta a punta y hacer que el socio complete su checklist con la nueva estructura.

## Próximo paso recomendado

Elegir una estrategia de `Scalping 9 robots` que tenga resultados SQX, fuente MQL5, retest MT5 e incubación. Migrar solo ese expediente y utilizarlo para cerrar los schemas piloto antes de crear el catálogo completo.

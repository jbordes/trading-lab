# TradingLab — Comparación de arquitectura 1.0 y 2.3

**Versión:** 1.0

**Estado:** Análisis de cobertura para validación de socios

**Fecha:** 8 de octubre de 2026

**Arquitectura evaluada:** TradingLab 2.2, corregida como 2.3 a partir de este análisis

## 1. Objetivo

Comprobar que la arquitectura propuesta no pierda capacidades reales del workspace `C:\TradingLab` y distinguir entre:

- capacidades que deben conservarse;
- problemas accidentales de la organización 1.0 que no deben replicarse;
- capacidades nuevas necesarias para seguridad, reproducibilidad y automatización;
- decisiones que siguen abiertas y deben validarse durante el piloto.

La comparación analiza comportamiento y responsabilidades, no solo nombres de carpetas.

## 2. Evidencia revisada

Se inspeccionaron en modo de solo lectura:

- README, arquitectura, reglas, lifecycle y guías de SQX de TradingLab 1.0;
- proyectos `Scalping 9 robots`, `XAUUSD M30 FTMO` y `XAUUSD H4 solo compras`;
- configuraciones Builder/Retester, snapshots, reportes diarios y reportes de proyecto;
- estrategias de distintas tandas, selecciones Long/Short y evidencia de correcciones;
- expedientes con `.sqx`, `.mq5`, `.set`, `.ex5`, HTML, PNG y XLSX;
- pipeline que consolida reportes MT5 en XLSX y SQLite;
- documentación oficial, fuentes aportadas, herramientas y Library;
- arquitectura TradingLab 2.2 y sus documentos de pipeline y MT5 Runner.

El área SQX observada contiene aproximadamente 971 archivos y 1,26 GiB. `Scalping 9 robots` concentra 870 archivos y aproximadamente 1,21 GiB. Estas cifras describen el workspace revisado el 8 de octubre de 2026; no son requisitos de capacidad permanentes.

## 3. Resumen ejecutivo

TradingLab 1.0 demuestra un proceso de investigación valioso y detallado, pero sus reglas viven parcialmente en documentos, nombres de carpetas y conocimiento del operador. El workspace funciona como un expediente humano y conserva mucha evidencia, aunque mezcla fuentes, configuraciones, estado de herramientas, resultados, derivados y conocimiento.

TradingLab 2.2 ya cubría correctamente repositorio, catálogo, storage, reproducibilidad, datasets, métricas, build SQX–MT5, VPS aislada, Google Drive y MT5 Runner. Sin embargo, el contraste reveló seis capacidades insuficientemente explícitas:

1. embudos SQX divididos en etapas con cohortes y conteos reconciliables;
2. selecciones y portfolios versionados;
3. aliases externos como ID SQX, Magic Number y nombres históricos;
4. decisiones humanas y automáticas aplicadas a candidatos;
5. lineage de workbooks, SQLite, resúmenes y otros derivados;
6. evidencia incremental durante incubaciones prolongadas.

También faltaba incorporar en el documento principal el registro manual ligero y el workspace humano ya definidos en la guía del repositorio. Estos huecos se corrigieron en Arquitectura 2.3.

## 4. Comparación general

| Dimensión | TradingLab 1.0 observado | TradingLab 2.3 | Cobertura |
| --- | --- | --- | --- |
| Organización general | Directorios globales `DOCUMENTATION`, `SQX`, `MT5`, `TOOLS` | Monorepo por responsabilidades: `docs`, `projects`, `apps`, `packages`, `db`, `infra`, `tools` | Cubierta con separación más clara |
| Proyecto de investigación | README, CONFIG, RESULTS, DOCUMENTATION y NOTES | `projects/<slug>/` con README, docs, configs, records y platforms | Cubierta |
| Operación manual | Expediente autocontenido por tanda/estrategia | `records/` como plano de control y `_storage/projects/` como expediente de artefactos | Cubierta desde 2.3 |
| Bitácora | Reporte diario central, reportes de proyecto e índice | `docs/sessions/`, enlaces a entidades, runs, ADR y commits | Cubierta; el índice podrá generarse |
| Configuración SQX | XML, CFX, SQB y snapshots detallados | Configuración canónica en Git; original inmutable en storage; hash en manifiesto | Cubierta |
| Workflow por etapas | Build, OOS, HBP, capital, descarte, MC, SPP, RTRS y broker final | Workflow versionado + `StageRun` por etapa | Cubierta desde 2.3 |
| Databanks y cohortes | Carpetas/databanks y conteos en reportes | `StrategySet` de entrada/salida, membresía y reconciliación | Cubierta desde 2.3 |
| Selección manual | CSV, inventarios, comparaciones y carpetas de candidatos | `StrategySet` tipo selection/portfolio + `Assessment` | Cubierta desde 2.3 |
| Portfolio de robots | Implícito en proyecto, tanda, Magic Numbers y hojas | Set versionado con miembros, roles, pesos/riesgo y evidencia | Cubierta desde 2.3 |
| Identidad de estrategia | IDs SQX, nombres, carpetas y Magic Numbers | ID interno estable + `ExternalIdentifier` con namespace/alcance/vigencia | Cubierta desde 2.3 |
| Resultados negativos | Conservados en proyectos y sesiones | Runs/assessments fallidos, rechazados, invalidados o superseded sin borrado | Cubierta |
| Correcciones posteriores | README/reportes corrigen interpretaciones previas | Supersesión e invalidación auditables con motivo, autor y fecha | Cubierta |
| Datos de mercado | Archivos e información de Data Manager | `DatasetVersion`, storage, hash, zona horaria, transformaciones y licencia | Cubierta |
| Backtests SQX | Reportes, XML, HTML, CSV, PNG y XLSX | Artefactos originales en storage + métricas normalizadas | Cubierta |
| Retests MT5 | Carpetas junto a cada estrategia | Run MT5, Environment, BotBuild, EvidenceBundle y artifacts | Cubierta |
| Preparación de bots | Manual, distribuida entre archivos y conocimiento humano | Pipeline formal, receta versionada, build manifest y gates | Cubierta y mejorada |
| Compilados `.ex5` | Presentes dentro de expedientes | Fuera de Git, inmutables en storage, identificados por hash | Cubierta y corregida |
| Incubación | HTML periódicos, screenshots y planillas | Deployment + run de incubación + múltiples lotes de evidencia | Cubierta desde 2.3 |
| Consolidación | Script Python, XLSX y SQLite derivados | `packages/ingestion`/`reporting`; original preservado; artifact lineage | Cubierta desde 2.3 |
| Reconciliación | Implementada en pipeline de incubadora | Ingestión idempotente, issues, niveles de verificación y reconciliación | Cubierta |
| Trazabilidad de derivados | Parcialmente en README, hashes y columnas de origen | `ArtifactLineage` obligatorio para derivados | Cubierta desde 2.3 |
| Library/promoción | Strategies, snippets, custom blocks, analysis y templates | Promoción explícita a knowledge, platforms o packages sin borrar origen | Cubierta desde 2.3 |
| Fuentes y material oficial | PDFs y fuentes dentro de proyectos/documentación | Artifact de referencia con procedencia/licencia; conocimiento autorizado en Git | Cubierta desde 2.3 |
| Herramientas | PowerShell/Python generales y scripts dentro de proyectos | `tools`, `packages`, `apps/cli` o skills según estabilidad/responsabilidad | Cubierta |
| MCP/Codex | Integración directa con SQX y reglas AGENTS | MCP fino sobre servicios; AGENTS breve; skills para procedimientos probados | Cubierta y endurecida |
| Base/catálogo | SQLite puntual y estructura principalmente documental | Catálogo transaccional con migraciones; PostgreSQL al escalar | Cubierta y ampliada |
| Storage | Archivos dentro del mismo workspace | Storage separado, URI portable, hash, retención e integridad | Cubierta y ampliada |
| Backup | No uniforme | Backup coordinado de catálogo/storage y pruebas de restauración | Cubierta como requisito; pendiente implementar |
| Seguridad MT5 | Límite operativo informal | VPS separada, sin acceso remoto, runner local y paquetes verificados | Cubierta y ampliada |
| Intercambio | Compartición manual por Google Drive | Canal de transporte no autoritativo con inbox/quarantine/checksums | Cubierta y ampliada |
| Git | Parte pequeña del workspace versionada; binarios mezclados localmente | Política explícita de contenido versionable y excluido | Cubierta y ampliada |
| Auditoría | Reportes detallados pero convenciones variables | IDs estables, UTC, manifests, estados, approvals y logs estructurados | Cubierta y ampliada |

## 5. Capacidades de 1.0 que deben preservarse

### 5.1 Expediente comprensible para el operador

El socio debe poder abrir una estrategia o run y localizar configuración, SQX, MT5, comparación e incubación sin consultar directamente PostgreSQL. `_storage/projects/<slug>/` mantiene esa vista operativa; `records/` o el catálogo evitan que la identidad dependa de la carpeta.

### 5.2 Fotografía exacta de configuración

Los documentos de 1.0 registran opciones activas, valores residuales, versiones, datasets y divergencias entre tareas. El manifiesto 2.3 debe conservar configuración efectiva y no limitarse a los parámetros que el operador recuerda haber activado.

### 5.3 Embudo y descartes

Los conteos entre etapas son evidencia del experimento. Una salida vacía, un descarte o una tanda invalidada no son basura: deben permanecer trazables. `StageRun`, `StrategySet` y `Assessment` formalizan esta memoria.

### 5.4 Revisión y decisión humana

La selección manual, interpretación de similitud, detección de dirección errónea y aprobación de incubación no se reducen a una métrica. Deben quedar como assessments auditables y seguir requiriendo aprobación humana mientras no exista una regla validada.

### 5.5 Preservación del original

El pipeline de incubadora 1.0 preserva reportes HTML, calcula SHA-256 y mantiene texto original. Esta práctica se convierte en regla general de ingestión y lineage.

### 5.6 Promoción, no movimiento automático

El lifecycle 1.0 distingue investigación activa de conocimiento o activos reutilizables. En 2.3 la promoción es explícita, versionada y no elimina el expediente del proyecto.

## 6. Aspectos de 1.0 que no deben replicarse

- Usar el nombre de una carpeta como única identidad de una estrategia.
- Mezclar `.sqx`, `.mq5`, `.ex5`, reportes, gráficos, bases y documentación en una misma capa.
- Mantener nombres ambiguos como `Nueva carpeta`, `Para codex` o variantes de capitalización.
- Duplicar originales sin manifiesto o relación de procedencia.
- Convertir hojas XLSX o SQLite reconstruibles en fuentes silenciosamente autoritativas.
- Conservar caches, `__pycache__`, temporales o snapshots completos dentro del expediente definitivo.
- Inferir dirección, timezone, estrategia o identidad a partir del nombre cuando la evidencia real no lo confirma.
- Versionar indiscriminadamente PDFs, reportes masivos, candidatos o ejecutables.

Estos elementos podrán conservarse durante la migración histórica, pero no definen la estructura objetivo.

## 7. Reglas de equivalencia para la migración

Una estrategia o tanda de 1.0 solo se considerará correctamente incorporada cuando:

1. tenga un ID interno y todos sus aliases conocidos;
2. su configuración canónica y snapshots originales estén identificados por hash;
3. cada etapa ejecutada tenga dataset, engine, filtros, fechas y conteos;
4. las cohortes de entrada y salida puedan reconstruirse o se declare explícitamente la limitación;
5. los artefactos originales tengan URI, tamaño, tipo y SHA-256;
6. los derivados indiquen fuentes y versión del proceso;
7. las decisiones de aceptación, rechazo, invalidación o selección tengan motivo y procedencia;
8. los backtests SQX, retests MT5 e incubación puedan distinguirse inequívocamente;
9. la estrategia pueda localizarse mediante sus nombres históricos y Magic Number sin usarlos como clave primaria;
10. el operador confirme que puede continuar su checklist manual con la nueva disposición.

## 8. Riesgos pendientes de implementación

La cobertura arquitectónica no significa que estas capacidades ya estén construidas. Permanecen pendientes:

- schemas concretos para records y catálogo;
- convención definitiva de IDs y namespaces;
- herramienta de inventario y migración con hashes;
- backup real de `_storage/` y prueba de restauración;
- parsers versionados para las variantes reales de SQX y MT5;
- definición de cierre y frecuencia de evidencia de incubación;
- política de licencia y acceso a documentación, cursos y datos;
- validación del workflow con el socio sobre un caso real.

## 9. Veredicto

La Arquitectura 2.2 no perdía los archivos principales, pero dejaba implícitas varias relaciones esenciales del trabajo real. Con las extensiones formalizadas en 2.3, todas las capacidades observadas en TradingLab 1.0 tienen un destino y una regla de autoridad.

No se afirma que toda excepción futura esté anticipada. La verificación definitiva exige migrar una estrategia real de principio a fin con el socio. El criterio correcto no será que todos los archivos antiguos hayan sido copiados, sino que ningún dato, decisión, etapa o evidencia necesaria para comprender y repetir el proceso quede sin representación.

## 10. Recomendación

Usar una estrategia de `Scalping 9 robots` que ya tenga SQX, MQL5, MT5 e incubación como piloto vertical. No migrar inicialmente el proyecto completo. El piloto debe ejercitar `StageRun`, dos o más `StrategySet`, aliases, un assessment manual, artifact lineage y al menos dos lotes de evidencia de incubación.

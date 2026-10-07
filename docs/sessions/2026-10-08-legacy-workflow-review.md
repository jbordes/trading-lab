# Bitácora — Análisis del workflow manual de TradingLab 1.0

**Fecha:** 8 de octubre de 2026

**Objetivo:** revisar el workspace histórico `C:\TradingLab`, comprender cómo se ejecutan y documentan manualmente la creación, validación e incubación de estrategias, y adaptar la guía de estructura de TradingLab 2.0 sin perder esa capacidad operativa.

## Material revisado

- estructura general, README y reglas del workspace TradingLab 1.0;
- arquitectura y lifecycle documentados para SQX;
- proyectos `Scalping 9 robots`, `XAUUSD M30 FTMO` y `XAUUSD H4 solo compras`;
- configuraciones Builder/Retester, experimentos, evidencias y reportes de sesión;
- carpetas de estrategias de primera, segunda y tercera tanda;
- expediente de incubación con reportes MT5, hojas de trabajo, SQLite y pipeline de consolidación;
- política `.gitignore` de TradingLab 1.0 y de TradingLab 2.0;
- versión 1.2 de `repository-structure-guide.md`.

No se modificó ningún archivo dentro de `C:\TradingLab`; se trató como fuente histórica de solo lectura.

## Observaciones verificadas

- El área SQX contiene aproximadamente 971 archivos y 1,26 GiB.
- La mayor parte del volumen corresponde a HTML, CSV, JSON y XML derivados de ejecuciones y análisis; también existen SQLite, XLSX, PNG, `.sqx`, `.mq5`, `.set` y `.ex5`.
- `Scalping 9 robots` concentra 870 archivos y aproximadamente 1,21 GiB.
- El procedimiento manual utiliza carpetas autocontenidas por tanda o estrategia con identificadores de SQX, Magic Numbers, fuentes, compilados, backtests SQX, retests MT5, gráficos y hojas de incubación.
- Las configuraciones efectivas y sus divergencias se documentan con mucho detalle, lo que aporta trazabilidad valiosa.
- La estructura actual mezcla en los mismos árboles conocimiento, configuración canónica, originales recibidos, artefactos generados y derivados analíticos.
- Los nombres de carpetas funcionan como parte de la identidad operativa, pero no siempre son estables o inequívocos.
- El pipeline de incubación existente ya aplica prácticas aprovechables: preservación de originales, SHA-256, IDs estables, normalización, reconciliación e idempotencia.

## Decisión

Se conservará la ergonomía del expediente manual, separando dos planos:

- **plano de control versionado:** README, configuraciones canónicas, manifiestos, identidad de estrategias, parámetros relevantes, hashes, resúmenes y decisiones;
- **plano de artefactos no versionado:** históricos, databanks, candidatos, compilados, reportes completos, gráficos, hojas de trabajo y bases derivadas.

Durante el piloto, `projects/<slug>/records/` proporcionará el registro manual ligero que posteriormente podrá importarse al catálogo. `_storage/projects/<slug>/` ofrecerá un espacio de trabajo humano por estrategia y run, reconocible para el socio, pero excluido de Git y respaldado por separado.

## Aclaraciones incorporadas

- `platforms/mt5/` no admite `.ex5`, históricos, cachés, reportes completos, packages de ejecución ni evidence bundles.
- `platforms/sqx/` no admite instalaciones, históricos, databanks, poblaciones, candidatos de una corrida, reportes masivos, bases locales, cachés ni exports generados.
- Una fuente `.mq5` experimental permanece en storage hasta ser promovida como código mantenido.
- Un `.sqx`, `.cfx`, `.sqb` o XML solo entra en Git cuando es una plantilla o configuración canónica pequeña, documentada y necesaria para reproducibilidad.
- La clasificación depende de la función y procedencia, no solo de la extensión.

## Estrategia de migración acordada

1. Mantener TradingLab 1.0 en solo lectura e inventariarlo con hashes.
2. Migrar un único proyecto piloto activo antes de tocar el resto.
3. Registrar estrategias y runs con IDs estables, conservando los nombres actuales como aliases.
4. Copiar artefactos preservando originales y validar sus hashes.
5. Comprobar con el socio que el checklist manual continúa siendo ejecutable y comprensible.
6. Automatizar primero manifiestos, inventarios e índices; mantener humanas las decisiones de selección.
7. Importar gradualmente los registros al catálogo cuando se implemente.

## Documento actualizado

- `docs/architecture/repository-structure-guide.md`: versión 1.2 → 1.3.
- `docs/architecture/repository-structure-guide.pdf`: regenerado desde la versión 1.3 y revisado visualmente.

## Pendientes

1. Elegir el primer proyecto piloto; `Scalping 9 robots` aporta el caso más completo, aunque su volumen aconseja migrar una sola estrategia o tanda inicialmente.
2. Definir los esquemas mínimos de `strategy record` y `run manifest`.
3. Definir la convención de IDs y aliases para IDs SQX y Magic Numbers actuales.
4. Establecer el mecanismo de backup de `_storage/`.
5. Crear un inventario de TradingLab 1.0 sin mover ni borrar archivos.

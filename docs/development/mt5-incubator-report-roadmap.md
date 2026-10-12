# Roadmap — Informe automatizado de incubación MT5

**Fecha:** 2026-10-12

**Estado:** Propuesto; pendiente de validación funcional

**Documento base:** [Análisis del informe automatizado de incubación MT5](../architecture/mt5-incubator-report-analysis.md)

## Principios de ejecución

- Entregable v1: un libro por `strategy_id + magic_number`, compatible con `encubadora_3.95.48_11122.xlsx`.
- El master anterior es referencia de validación, no entregable inicial.
- Captura MT5 estrictamente de solo lectura.
- Excel como proyección reemplazable, nunca como única fuente.
- Evidencia original fuera de Git; fixtures mínimos anonimizados dentro de Git.
- Idempotencia, hashes y reconciliación desde el primer incremento.
- Revisión independiente por tratar datos de trading y cálculos económicos.

## Fase 0 — Congelar el contrato con el socio

**Objetivo:** convertir el workbook objetivo en criterios de aceptación inequívocos.

Tareas:

1. Revisar `encubadora_3.95.48_11122.xlsx` como referencia principal.
2. Confirmar una hoja `TRADES` con las 37 columnas observadas más `magic_number` después de `strategy_id`.
3. Confirmar que el autofiltro cubra las 38 columnas y permita filtrar por bot.
4. Confirmar nombre, ruta y unidad de salida: estrategia + Magic Number.
5. Confirmar que v1 contiene solo trades cerrados.
6. Acordar mapping, timezone, corte diario, correcciones y retención.
7. Registrar expresamente que el master y hojas adicionales quedan fuera de v1.

**Salida:** contrato versionado y workbook esperado anonimizado.

**Gate:** el socio aprueba el ejemplo esperado y puede explicar el uso de cada campo requerido.

## Fase 1 — Golden dataset del archivo objetivo

**Objetivo:** convertir la referencia existente en una base de pruebas segura.

Tareas:

1. Construir un fixture mínimo a partir de las siete filas del workbook y su fuente MT5.
2. Anonimizar cuentas, personas e IDs sin romper relaciones.
3. Preservar casos de IDs de cierre ausentes, timezone desconocido y estados explícitos.
4. Incorporar Magic Numbers anonimizados que mantengan el mapping entre bot, estrategia y cuenta.
5. Verificar `trade_uid`, `magic_number`, beneficio neto, duración, orden de columnas y formatos.
6. Incorporar casos adicionales de duplicado, asignación no resuelta y cierre parcial.
7. Usar el prototipo y el master solo como oráculos secundarios de reglas y reconciliación.

**Salida:** fixtures mínimos y tests de contrato; no reportes operativos completos.

**Gate:** los resultados anonimizados reproducen estructura, trades, costes y beneficio esperados.

## Fase 2 — Núcleo y contratos

**Objetivo:** implementar el modelo independiente de API, Excel y futura base de datos.

Estructura orientativa:

```text
src/tradinglab/incubation/
├── domain.py
├── ports.py
├── normalization.py
├── reconstruction.py
├── strategy_resolution.py
└── reconciliation.py
```

Tareas:

1. Definir modelos tipados para órdenes, deals y ciclos de posición.
2. Modelar `magic_number` como ID operativo del bot y el deployment como `account_id + magic_number`, mapeado a `strategy_id`.
3. Definir puertos de fuente, evidencia y reporting.
4. Implementar claves estables e idempotencia.
5. Implementar reconstrucción con entradas/salidas parciales.
6. Implementar asignación con evidencia y estados explícitos.
7. Cubrir reglas puras con tests unitarios.

**Gate:** el núcleo procesa fixtures sin importar `MetaTrader5` ni una librería Excel.

## Fase 3 — Adaptador de reporte

**Objetivo:** soportar el archivo exportado de MT5 como entrada inicial y fallback.

Tareas:

1. Detectar estructura, idioma y secciones sin depender solo del texto visible.
2. Parsear posiciones cerradas, órdenes y deals necesarios para reconstruir `TRADES`.
3. Capturar abiertos, pendientes y snapshot como evidencia, sin agregarlos al Excel v1.
4. Conservar valores originales, fingerprint y versión del parser.
5. Emitir incidencias ante formatos desconocidos o datos insuficientes.
6. Comparar contra el golden dataset y, secundariamente, contra el prototipo.

**Gate:** reproduce el caso objetivo y rechaza entradas incompatibles sin publicar resultados parciales.

## Fase 4 — Spike de API MT5

**Objetivo:** probar lectura real y documentar límites del terminal.

Tareas:

1. Agregar `MetaTrader5` como dependencia opcional de Windows y fijarla en el lockfile.
2. Conectar a un terminal autorizado mediante configuración local.
3. Capturar cuenta, terminal, órdenes, deals, posiciones y órdenes activas.
4. Guardar respuesta serializable y `last_error` seguro.
5. Verificar timestamps, `magic`, `position_id`, tickets, comentarios y costes.
6. Validar el mapping hacia `strategy_id + magic_number`.
7. No exponer funciones de trading y ejecutar siempre `shutdown()`.

**Gate:** una captura repetible y sin efectos aporta los IDs necesarios para generar el golden dataset.

## Fase 5 — Evidencia e ingesta incremental

**Objetivo:** hacer segura la actualización diaria sin base de datos.

Tareas:

1. Crear `CollectionRun` y manifest versionado.
2. Guardar capturas inmutables en `_storage/` con SHA-256.
3. Registrar mappings de deployment utilizados en cada corrida.
4. Consultar ventanas solapadas y deduplicar por IDs nativos.
5. Implementar locking y recuperación frente a interrupciones.
6. Mantener backfill explícito separado de la actualización diaria.

**Gate:** ejecutar dos veces la misma ventana produce el mismo dataset y los mismos trades, sin duplicados.

## Fase 6 — Generador del workbook objetivo

**Objetivo:** reproducir el archivo por estrategia sin acoplarlo a la captura.

Tareas:

1. Elegir la librería Excel según el contrato aprobado.
2. Generar `encubadora_<strategy_id>_<magic_number>.xlsx` por cada mapping activo.
3. Implementar una hoja `TRADES` de 38 columnas, agregando `magic_number` después de `strategy_id`.
4. Reproducir nombres, orden, tipos, filtro sobre todas las columnas, fila congelada y anchos.
5. Regenerar desde el dataset canónico, validar y reemplazar atómicamente.
6. Probar valores y estructura OOXML relevante, no bytes completos del ZIP.
7. Verificar que una estrategia o Magic Number sin mapping no se mezcle ni se publique silenciosamente.

El master, los dashboards y las hojas adicionales quedan diferidos salvo nueva decisión funcional.

**Gate:** el socio compara el libro automático con `encubadora_3.95.48_11122.xlsx` y acepta la salida.

## Fase 7 — Shadow run y reconciliación

**Objetivo:** demostrar confiabilidad antes de abandonar la actualización manual.

Tareas:

1. Ejecutar API, reporte y procedimiento manual en paralelo durante un periodo acordado.
2. Comparar filas de `TRADES`, IDs, costes, beneficio, asignación y timestamps.
3. Confirmar qué ocurre con nuevos trades y correcciones históricas.
4. Clasificar diferencias como formato, timezone, mapping o dato faltante.
5. Convertir cada diferencia corregida en fixture de regresión.
6. Someter código y resultados a revisión independiente.

**Gate:** cero diferencias no explicadas durante las jornadas acordadas.

## Fase 8 — Automatización diaria

**Objetivo:** actualizar todos los libros activos sin intervención rutinaria y con fallos visibles.

Tareas:

1. Crear un comando `run-daily` idempotente y un `--dry-run`.
2. Cargar el inventario autorizado de estrategia, Magic Number, cuenta y destino.
3. Configurar el scheduler de Windows con usuario de mínimo privilegio.
4. Establecer timeout, reintentos limitados y bloqueo por terminal.
5. Publicar cada Excel solo tras captura, validación y reconciliación completas.
6. Conservar la última salida válida si una corrida falla.
7. Emitir resumen operativo y alerta sin secretos.
8. Documentar recuperación y ejecución manual.

**Gate:** una falla de MT5 o filesystem no corrompe el último informe ni pierde evidencia.

## Fuera de alcance de v1

- crear o mantener un nuevo `incubator_master.xlsx`;
- agregar dashboard, resumen u hojas de posiciones abiertas al entregable;
- implementar la base de datos productiva;
- ejecutar operaciones de trading;
- depender del Excel anterior para calcular el nuevo.

## Fase futura — Persistencia en base de datos

Cuando exista una decisión de catálogo:

1. Implementar un adapter del puerto de persistencia existente.
2. Importar manifests y capturas históricas.
3. Generar Excel desde el mismo dataset canónico persistido.
4. Comparar salidas antes y después de la migración.
5. Retirar archivos intermedios solo tras validar backup y restauración.

## Dependencias entre entregas

```text
Contrato del workbook objetivo
            |
      Golden dataset
            |
     Núcleo y contratos
           / \
    Reporte   API spike
           \ /
   Evidencia incremental
            |
   Generador por estrategia + magic
            |
       Shadow run
            |
   Automatización diaria
            |
   Base de datos futura
```

## Decisiones pendientes antes de implementar

- mapping autoritativo Strategy ID ↔ Magic Number ↔ cuenta;
- alcance de unicidad del Magic Number entre cuentas, terminales y entornos;
- compatibilidad exacta de nombre, ruta, estilos y anchos;
- tratamiento de una estrategia con múltiples deployments;
- zona horaria, corte diario y política de correcciones;
- API o reporte como fuente primaria durante el piloto;
- ubicación y retención de capturas y Excel;
- librería de escritura Excel;
- canal de alerta y duración del shadow run.

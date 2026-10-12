# Roadmap — Informe automatizado de incubación MT5

**Fecha:** 2026-10-12

**Estado:** Propuesto; pendiente de validación funcional

**Documento base:** [Análisis del informe automatizado de incubación MT5](../architecture/mt5-incubator-report-analysis.md)

## Principios de ejecución

- Entregas verticales y verificables, sin construir la base de datos futura.
- Captura de MT5 estrictamente de solo lectura.
- Excel como proyección reemplazable, nunca como única fuente.
- Evidencia original fuera de Git; fixtures mínimos y anonimizados dentro de Git.
- Idempotencia, hashes y reconciliación desde el primer incremento.
- Revisión independiente obligatoria por tratar datos de trading y reconstrucción económica.

## Fase 0 — Contrato con el socio

**Objetivo:** convertir el Excel actual en criterios de aceptación inequívocos.

Tareas:

1. Revisar juntos el libro por estrategia y el master.
2. Marcar hojas y columnas obligatorias, opcionales y obsoletas.
3. Definir métricas y fórmulas con ejemplos manuales.
4. Elegir Strategy ID/Magic Number/comment como mapping autoritativo.
5. Acordar corte diario, timezone, ubicación, nombres y retención.
6. Confirmar si el alcance incluye abiertos, pendientes y master.

**Salida:** contrato de informe versionado y un workbook esperado anonimizado.

**Gate:** el socio puede explicar cómo usa cada campo requerido y aprueba el ejemplo esperado.

## Fase 1 — Golden dataset y paridad histórica

**Objetivo:** convertir las referencias existentes en una base de pruebas segura.

Tareas:

1. Seleccionar una cuenta, estrategias y periodo pequeños pero representativos.
2. Anonimizar reporte, IDs personales y nombres sin romper relaciones.
3. Extraer del prototipo las reglas de comentario, net profit, deduplicación y reconciliación.
4. Registrar conteos y totales esperados del prototipo como golden results.
5. Incluir casos de estrategia sin resolver, duplicado y cierre parcial.

**Salida:** fixtures mínimos y tests de contrato, no reportes operativos completos.

**Gate:** los resultados anonimizados reproducen posiciones, costes y beneficio dentro de tolerancias acordadas.

## Fase 2 — Núcleo y contratos

**Objetivo:** implementar el modelo independiente de API, Excel y base de datos.

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

1. Definir modelos tipados para órdenes, deals, ciclos y snapshots.
2. Definir puertos de fuente, evidencia y reporting.
3. Implementar claves estables e idempotencia.
4. Implementar reconstrucción con entradas/salidas parciales.
5. Implementar Strategy Assignment con evidencia y estados explícitos.
6. Cubrir reglas puras con tests unitarios.

**Gate:** el núcleo procesa fixtures sin importar `MetaTrader5` ni una librería Excel.

## Fase 3 — Adaptador de reporte

**Objetivo:** soportar el archivo exportado y preservar la operación manual como fallback.

Tareas:

1. Detectar estructura, idioma y secciones sin depender únicamente del texto visible.
2. Parsear posiciones cerradas, órdenes, deals, abiertos, pendientes y resumen.
3. Conservar valores originales, fingerprint y versión del parser.
4. Emitir incidencias ante columnas, secciones o encoding desconocidos.
5. Comparar contra el prototipo HTML y el golden dataset.

**Gate:** el adaptador reproduce el caso de referencia y rechaza formatos incompatibles sin generar un resultado parcial silencioso.

## Fase 4 — Spike de API MT5

**Objetivo:** probar lectura real y documentar límites del terminal antes de integrarla al pipeline diario.

Tareas:

1. Agregar `MetaTrader5` como dependencia opcional de Windows, fijada en lockfile.
2. Conectar a un terminal de incubación autorizado mediante configuración local.
3. Capturar `account_info`, `terminal_info`, órdenes, deals, posiciones y órdenes activas.
4. Guardar respuesta cruda serializable y `last_error` seguro.
5. Verificar timestamps, `magic`, `position_id`, tickets y costes.
6. Prohibir y no exponer funciones de trading.
7. Ejecutar siempre `shutdown()` y probar fallo de terminal, login y ventana vacía.

**Gate:** una captura de solo lectura puede repetirse sin efectos y tiene IDs suficientes para reconstruir el golden dataset.

## Fase 5 — Evidencia e ingestión incremental

**Objetivo:** hacer segura la actualización diaria sin base de datos.

Tareas:

1. Crear `CollectionRun` y manifest versionado.
2. Guardar capturas inmutables en `_storage/` con SHA-256.
3. Consultar ventanas solapadas y deduplicar por IDs nativos.
4. Incorporar snapshots de cuenta, abiertos y pendientes.
5. Implementar locking y recuperación frente a una corrida interrumpida.
6. Mantener backfill explícito separado de la actualización diaria.

**Gate:** ejecutar dos veces la misma ventana produce el mismo dataset sin duplicados.

## Fase 6 — Generador Excel

**Objetivo:** producir el entregable aprobado sin acoplarlo a la captura.

Tareas:

1. Elegir librería según el contrato de plantilla.
2. Implementar vistas por estrategia y master si fue aprobado.
3. Agregar filtros, formatos, congelado de cabeceras y tipos Excel correctos.
4. Generar desde cero en un temporal y reemplazar al validar.
5. Incluir fuente, instante de actualización e incidencias visibles.
6. Probar el contenido por valores y estructura, no por bytes del ZIP.

**Gate:** el socio compara el libro automático con su proceso manual y acepta la salida.

## Fase 7 — Shadow run y reconciliación

**Objetivo:** demostrar confiabilidad antes de abandonar la actualización manual.

Tareas:

1. Ejecutar API, reporte y procedimiento manual en paralelo durante un periodo acordado.
2. Comparar trades, costes, beneficio, abiertos, pendientes y métricas.
3. Clasificar diferencias como formato, timezone, mapping o dato faltante.
4. Corregir reglas mediante nuevos fixtures de regresión.
5. Someter el cambio a revisión independiente de código y datos.

**Gate:** cero diferencias no explicadas durante el número de jornadas acordado.

## Fase 8 — Automatización diaria

**Objetivo:** operar sin intervención rutinaria y con fallos visibles.

Tareas:

1. Crear un comando `run-daily` idempotente y un `--dry-run`.
2. Configurar el scheduler de Windows con usuario de mínimo privilegio.
3. Establecer timeout, reintentos limitados y bloqueo por terminal.
4. Publicar el Excel solo después de completar captura, validación y reconciliación.
5. Conservar última salida válida si la nueva corrida falla.
6. Emitir un resumen operativo y alerta sin secretos.
7. Documentar recuperación y ejecución manual.

**Gate:** una falla de MT5 o filesystem no corrompe el último informe ni pierde la evidencia capturada.

## Fase futura — Persistencia en base de datos

No se implementa en este roadmap. Cuando exista una decisión de catálogo:

1. Implementar un adapter del puerto de persistencia existente.
2. Importar manifests y capturas históricas.
3. Ejecutar Excel desde consultas al dataset canónico.
4. Comparar salida anterior y posterior a la migración.
5. Retirar archivos intermedios únicamente después de validar backup y restauración.

## Dependencias entre entregas

```text
Contrato con socio
       |
Golden dataset
       |
Núcleo y contratos
      / \
Reporte   API spike
      \ /
Evidencia incremental
       |
Generador Excel
       |
Shadow run
       |
Automatización diaria
       |
Base de datos futura
```

## Decisiones pendientes antes de implementar

- contenido exacto del informe;
- identidad autoritativa de estrategia;
- API primaria o reporte primario durante el primer piloto;
- cuenta, terminal y zona horaria piloto;
- ubicación y retención de capturas y Excel;
- librería de escritura Excel;
- canal de alerta y ventana diaria;
- duración y tolerancias del shadow run.

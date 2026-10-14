# Roadmap — Informe automatizado de incubación MT5

**Fecha:** 2026-10-14

**Estado:** Ajustado con respuestas del socio; Fase 0 parcialmente abierta

**Documento base:** [Análisis del informe automatizado de incubación MT5](../architecture/mt5-incubator-report-analysis.md)

**Incremento activo:** [Spike de captura MT5 — contrato e inventario inicial](mt5-capture-spike.md)

## Principios de ejecución

- Entregable v1: un libro por estrategia, con nombre `encubadora_<strategy_id>_<magic_number>.xlsx` y compatible con la referencia.
- El master anterior es referencia de validación, no entregable inicial.
- Captura MT5 estrictamente de solo lectura.
- La captura conserva toda la información operativa disponible aunque el Excel inicial muestre solo una vista.
- Excel como proyección reemplazable, nunca como única fuente.
- Magic Number como ID manual estable del bot; los registros de ejecución siguen calificados por cuenta.
- Evidencia original fuera de Git; fixtures mínimos anonimizados dentro de Git.
- Idempotencia, hashes y reconciliación desde el primer incremento.
- Revisión independiente por tratar datos de trading y cálculos económicos.

## Fase 0 — Congelar el contrato con el socio

**Objetivo:** convertir el workbook objetivo en criterios de aceptación inequívocos.

Tareas:

1. Mantener `encubadora_3.95.48_11122.xlsx` como referencia principal.
2. Mantener una hoja `TRADES` con las 37 columnas observadas más `magic_number` después de `strategy_id`.
3. Mantener el autofiltro sobre las 38 columnas para filtrar por bot.
4. Crear el contrato del registro Magic Number ↔ bot ↔ ID SQX ↔ estrategia ↔ cuentas.
5. Resolver cómo agrupar una estrategia con varios Magic Numbers históricos.
6. Confirmar si la vista Excel v1 incluye abiertas y pendientes o solo cerradas.
7. Definir cómo representar revisiones sin confundirlas con operaciones nuevas.
8. Confirmar publicación acumulativa, copias fechadas, ruta y ejecución en fines de semana.
9. Registrar que la ejecución normal será a las 20:00 de `Europe/Madrid`, que la observabilidad inicial será por logs y que los reportes no se eliminan.
10. Mantener el master fuera de v1.

**Salida:** contrato versionado y workbook esperado anonimizado.

**Gate:** están resueltas las siete aclaraciones de la sección 12 del análisis y el socio aprueba el ejemplo esperado.

## Fase 1 — Golden dataset del archivo objetivo

**Objetivo:** convertir la referencia existente en una base de pruebas segura.

Tareas:

1. Construir un fixture mínimo a partir de las siete filas del workbook y su fuente MT5.
2. Anonimizar cuentas, personas e IDs sin romper relaciones.
3. Preservar casos de IDs de cierre ausentes, timezone desconocido y estados explícitos.
4. Incorporar Magic Numbers anonimizados que mantengan el mapping entre bot, estrategia y cuenta.
5. Verificar `trade_uid`, `magic_number`, beneficio neto, duración, orden de columnas y formatos.
6. Incorporar casos adicionales de duplicado, asignación no resuelta y cierre parcial.
7. Incorporar posiciones abiertas, órdenes pendientes y snapshots de dos cuentas con el mismo bot.
8. Incorporar una corrección posterior que preserve y enlace la observación anterior.
9. Usar el prototipo y el master solo como oráculos secundarios de reglas y reconciliación.

**Salida:** fixtures mínimos y tests de contrato; no reportes operativos completos.

**Gate:** los resultados anonimizados reproducen estructura, trades, costes y beneficio esperados.

Avance del incremento 0A:

- contrato de captura cruda `mt5-diagnostic-v1` implementado;
- fixture sintético con historial, posición abierta y orden pendiente;
- reconstrucción del trade y paridad económica todavía pendientes.

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

1. Definir modelos tipados para órdenes, deals, ciclos de posición y snapshots.
2. Modelar `magic_number` como ID operativo estable del bot y cada ejecución dentro del contexto de su cuenta.
3. Modelar un registro versionado de bot, ID SQX, estrategia, Magic Number, cuentas y vigencia.
4. Modelar observaciones y revisiones inmutables, separando fecha efectiva y fecha de detección.
5. Definir puertos de fuente, evidencia y reporting.
6. Implementar claves estables e idempotencia.
7. Implementar reconstrucción con entradas/salidas parciales.
8. Implementar asignación con evidencia y estados explícitos.
9. Cubrir reglas puras con tests unitarios.

**Gate:** el núcleo procesa fixtures sin importar `MetaTrader5` ni una librería Excel.

## Fase 3 — Adaptador de reporte

**Objetivo:** soportar el archivo exportado de MT5 como entrada inicial y fallback.

Tareas:

1. Detectar estructura, idioma y secciones sin depender solo del texto visible.
2. Parsear posiciones cerradas, órdenes y deals necesarios para reconstruir `TRADES`.
3. Capturar también abiertos, pendientes y snapshots, aunque su publicación en Excel se decida por separado.
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
7. Comparar capturas sucesivas para determinar qué cambios de posición se pueden reconstruir a posteriori.
8. Documentar qué requeriría capturar mediante `OnTradeTransaction` y no implementar ese colector sin demostrar su necesidad.
9. No exponer funciones de trading y ejecutar siempre `shutdown()`.

**Gate:** una captura repetible y sin efectos aporta los IDs necesarios para generar el golden dataset.

Avance del incremento 0A:

- diagnóstico de solo lectura y manifest SHA-256 implementados;
- tests con cliente MT5 controlado implementados;
- ejecución contra el terminal y los brokers reales pendiente.

## Fase 5 — Evidencia e ingesta incremental

**Objetivo:** hacer segura la actualización diaria sin base de datos.

Tareas:

1. Crear `CollectionRun` y manifest versionado.
2. Guardar capturas inmutables en `_storage/` con SHA-256.
3. Registrar mappings de deployment utilizados en cada corrida.
4. Consultar ventanas solapadas y deduplicar por IDs nativos.
5. Conservar nuevas versiones cuando una observación cambie y enlazarlas con su antecedente.
6. Implementar locking y recuperación frente a interrupciones.
7. Mantener backfill explícito separado de la actualización diaria.
8. Aplicar retención indefinida; no borrar reportes ni evidencia.

**Gate:** ejecutar dos veces la misma ventana produce el mismo dataset y los mismos trades, sin duplicados.

## Fase 6 — Generador del workbook objetivo

**Objetivo:** reproducir el archivo por estrategia sin acoplarlo a la captura.

Tareas:

1. Elegir la librería Excel según el contrato aprobado.
2. Generar un `encubadora_<strategy_id>_<magic_number>.xlsx` por estrategia.
3. Implementar una hoja `TRADES` de 38 columnas, agregando `magic_number` después de `strategy_id`.
4. Reproducir nombres, orden, tipos, filtro sobre todas las columnas, fila congelada y anchos.
5. Regenerar desde el dataset canónico, validar y reemplazar atómicamente.
6. Probar valores y estructura OOXML relevante, no bytes completos del ZIP.
7. Verificar que una estrategia o Magic Number sin mapping no se mezcle ni se publique silenciosamente.
8. Implementar la vista acordada para revisiones y para operaciones abiertas o pendientes.

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
3. Configurar el scheduler de Windows para las 20:00 de `Europe/Madrid` con usuario de mínimo privilegio.
4. Establecer timeout, reintentos limitados y bloqueo por terminal.
5. Publicar cada Excel solo tras captura, validación y reconciliación completas.
6. Conservar la última salida válida si una corrida falla.
7. Emitir logs operativos claros y sin secretos; las alertas para usuarios no técnicos quedan diferidas.
8. Documentar recuperación y ejecución manual.

**Gate:** una falla de MT5 o filesystem no corrompe el último informe ni pierde evidencia.

## Fuera de alcance de v1

- crear o mantener un nuevo `incubator_master.xlsx`;
- agregar dashboard o resumen al entregable;
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

## Aclaraciones funcionales pendientes antes de implementar

1. Ubicación, responsable y formato inicial del registro autoritativo de bots y Magic Numbers.
2. Tratamiento de una estrategia con más de un Magic Number a lo largo del tiempo.
3. Inclusión o exclusión de abiertas y pendientes en el Excel v1.
4. Representación visible de correcciones, revisiones y registros reemplazados.
5. Workbook acumulativo, copias diarias o ambos.
6. Ejecución en fines de semana y política de recuperación si MT5 no está disponible a las 20:00.
7. Rutas de publicación del Excel y de su archivo histórico.

Decisiones técnicas que se resolverán mediante el piloto, sin bloquear la conversación funcional:

- API o reporte como fuente primaria durante el primer shadow run;
- suficiencia del historial y snapshots frente a un posible colector `OnTradeTransaction`;
- librería de escritura Excel;
- duración y tolerancias del shadow run.

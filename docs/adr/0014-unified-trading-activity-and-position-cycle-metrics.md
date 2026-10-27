# ADR-0014: Actividad de trading unificada y métricas por ciclo de posición

**Estado:** accepted

**Fecha:** 2026-10-27

## Contexto

El dashboard separa actualmente `Operaciones`, que presenta el último snapshot de
posiciones abiertas y órdenes pendientes, de `Historial`, que consulta deals
durables y calcula las fórmulas provisionales observadas en el workbook del socio.
La separación es correcta para las fuentes y los ritmos de actualización, pero no
coincide con el modelo mental del analista: ambas pantallas son formas de explorar
la actividad de trading.

Además, un deal de salida no representa necesariamente una operación completa.
Puede haber entradas múltiples, fills parciales, salidas parciales, reversas o
intervenciones externas. Evaluar la autonomía de un EA exige distinguir la
evidencia MT5 de la reconstrucción de una posición y de la atribución del resultado
a un bot.

MT5 relaciona los deals y las órdenes ejecutadas con el identificador estable de
la posición. Esos identificadores pertenecen al ámbito de una cuenta. El Magic
Number identifica al EA que origina una acción, pero no forma parte de la identidad
de la posición: otro EA o una persona pueden modificar o cerrar la misma posición.
En cuentas netting, dos EAs que operan el mismo símbolo modifican necesariamente
una única posición.

## Alternativas consideradas

1. Mantener `Operaciones` e `Historial` como destinos independientes. Conserva la
   implementación actual, pero expone al usuario una división técnica y deja
   ambiguo qué significa «operación».
2. Unificar también almacenamiento y dominio en una tabla plana de operaciones.
   Simplifica superficialmente la UI, pero borra diferencias entre orden, deal y
   posición, dificulta la auditoría y fuerza columnas y reglas incompatibles.
3. Unificar la experiencia de consulta, conservar las entidades y fuentes reales,
   y reconstruir ciclos de posición explícitos solo para análisis de rendimiento.

## Decisión

Adoptar la tercera alternativa.

### Experiencia de consulta

`Operaciones` e `Historial` evolucionarán hacia una sección única de `Trading` o
`Actividad de trading`. Tendrá alcances explícitos:

- `En curso`: posiciones abiertas y órdenes pendientes del snapshot vigente;
- `Ejecuciones`: deals históricos;
- `Órdenes`: activas e históricas, incluidos estados cancelado, vencido y
  rechazado;
- `Todo`: cronología combinada para investigación, sin confundir entidades.

La vista compartirá filtros de cuenta/fuente, período, Magic Number, símbolo,
entidad, estado, dirección e identificadores relacionados. Cada fila conservará
su tipo real y podrá exponer detalles específicos. Las API, tablas y ritmos de
captura pueden continuar separados; la unificación es una capa de consulta y
presentación, no un nuevo modelo canónico ni una migración automática.

El análisis de rendimiento tendrá un espacio semántico separado. Sus gráficos y
métricas no mezclarán posiciones abiertas, órdenes o deals no elegibles aunque se
acceda a ellos desde el mismo contexto de filtros.

### Reconstrucción y atribución

La identidad mínima de un ciclo de posición es:

```text
(account_id, position_id)
```

`account_id` debe resolver de forma estable la cuenta de broker, incluido su
servidor; `source_id` no forma parte de la clave porque más de un collector puede
observar la misma cuenta. Un `position_id` igual a cero no identifica un ciclo y
es válido, por ejemplo, en una orden que nunca se ejecutó.

El Magic Number se utiliza para atribución y diagnóstico, no para fragmentar la
identidad de la posición. Cada ciclo conservará al menos el Magic propietario de
la apertura, el conjunto de Magic observados, su estado de atribución y su estado
de completitud.

Una posición podrá alimentar las métricas autónomas de un EA únicamente cuando:

1. la evidencia cubra el ciclo desde la entrada hasta el cierre total;
2. el volumen remanente sea cero y el resultado sea definitivo;
3. la atribución a un único EA sea inequívoca;
4. no exista intervención manual, de otro EA o de otro sistema externo;
5. los costes admitidos por el contrato estén disponibles.

Stop Loss y Take Profit configurados como parte de la operación del EA son salidas
legítimas, no intervenciones por sí mismos. La clasificación utilizará en conjunto
Magic Numbers, motivos, órdenes y deals relacionados; no inferirá intervención a
partir de un único campo.

Los ciclos abiertos, incompletos, intervenidos o con atribución ambigua quedan
fuera de las métricas autónomas, pero no se eliminan. Se conservan para auditoría,
diagnóstico y para mostrar el motivo de exclusión.

### Netting y colisiones

En una cuenta netting, una posición sobre la que aparecen acciones comerciales de
más de un Magic Number se marca como `colisión netting` o `Magic mixto`. Su
resultado no se reparte mediante una regla implícita entre los EAs y se excluye de
las métricas individuales de todos ellos.

La incubación deberá preferir cuentas hedging o impedir que dos EAs operen
simultáneamente el mismo símbolo dentro de una cuenta netting. Un eventual libro
virtual por estrategia requerirá otro contrato y no se deducirá como si fuera el
resultado objetivo informado por el broker.

### Versionado de métricas

`partner-workbook-v1` continúa describiendo el cálculo provisional por deals de
salida y sirve para contrastar el workbook. No se modificará silenciosamente para
que parezca calcular trades completos. El cálculo por ciclos cerrados será un
contrato nuevo, versionado y probado con entradas múltiples, cierres parciales,
reversas, intervenciones, gaps y cuentas hedging/netting.

## Consecuencias

- La navegación se organiza por tareas del analista y no por tecnología de
  almacenamiento.
- Las entidades MT5 siguen siendo auditables y no se aplastan en una fila genérica.
- El resultado por EA prioriza validez sobre cantidad: una operación dudosa se
  excluye y se explica.
- Las órdenes canceladas o vencidas siguen aportando evidencia de comportamiento,
  aunque no formen parte del rendimiento financiero.
- Será necesario exponer órdenes históricas, cobertura por entidad y relaciones
  orden/deal/posición antes de completar la experiencia unificada.
- La implementación deberá detectar ciclos incompletos y colisiones sin cargar el
  histórico creciente completo en memoria.

## Relación con decisiones anteriores

Complementa [ADR-0012](0012-durable-operation-history.md). No cambia que SQLite
sea la fuente durable ni autoriza proyecciones históricas ilimitadas en memoria;
precisa la experiencia de consulta y el criterio de elegibilidad para métricas.

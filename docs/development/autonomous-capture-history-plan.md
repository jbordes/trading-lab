# Captura autónoma, historial completo y rendimiento

Fecha: 2026-10-29. Estado: análisis y plan para revisión; implementación pendiente
del OK humano. Base: `fix/pr48-robustness-findings`, commit `d90343e`.

## Objetivo y decisiones de planificación

Conservar el historial de operaciones disponible y mantenerlo actualizado aunque
el dashboard esté detenido. Preparar la incorporación de una cuenta con años de
actividad sin exigir que primero acumulemos ese volumen en el piloto.

- Mantener SQLite en los próximos incrementos locales.
- Separar el ciclo de vida de los receptores del dashboard.
- Recuperar historia por bloques reanudables, sin frenar la captura reciente.
- Conservar órdenes, deals, ciclos y procedencia; no imponer el límite de 12 meses
  de los gráficos a la recuperación ni al almacenamiento.
- Diseñar índices a partir de las consultas conocidas y verificar su eficacia con
  datos sintéticos representativos. La medición valida el diseño; no posterga
  necesidades ya identificadas.
- Evaluar PostgreSQL al diseñar el servidor central; no migrar por anticipación.

Este plan no sustituye los ADR aceptados: [ADR-0008](../adr/0008-pilot-telemetry-retention.md)
conserva la retención sin borrados automáticos y [ADR-0009](../adr/0009-defer-external-telemetry-backup.md)
regula las copias externas. Las decisiones nuevas de automatización, retención
destructiva o despliegue requerirán sus ADR antes de activarse.

## Estado de partida y límites

El piloto documentado utiliza receptores v1 y v2, bases separadas y un dashboard
arrancados por un supervisor común. V1 aporta el estado vivo; v2 conserva actividad
y ciclos. El supervisor administra sus procesos Python, no la terminal MT5.
El collector de actividad ya dispone de ventanas, solapamiento, cursor y
confirmación: ampliar ese mecanismo antes de introducir otro recolector.

La recuperación y reconstrucción de ciclos ya se probaron en demo. Falta evaluar
su comportamiento con años de actividad y separar su operación del dashboard.
El límite de 500 ciclos de las consultas del piloto no es una política de retención.

Para capturar datos nuevos deben funcionar MT5, los collectors y el receptor.
Una tarea programada no puede recuperar capturas de equity que nunca se tomaron.
MT5/broker determinan qué historia está disponible: ausencia de filas no prueba
que la cuenta nunca tuvo actividad. Una historia parcial debe permanecer explícita.

## SQLite, PostgreSQL y ubicación de los servicios

SQLite sigue siendo apropiado para un backend local con escrituras coordinadas.
Los años de historia o varios GB no determinan por sí solos el cambio de motor.
Sus escrituras se serializan; consultas, transacciones y mantenimiento deben
evitar monopolizar el acceso. No se promete capacidad sin una prueba representativa.

| Despliegue | Evaluación |
| --- | --- |
| MT5, backend y SQLite en la VPS | Continuidad del piloto; comparten CPU, disco y memoria con los EAs |
| MT5 en la VPS; backend y SQLite juntos en otro servidor | Separación viable mediante una API; no exige cambiar de motor |
| MT5 en la VPS; backend y PostgreSQL centralizados | Candidato cuando concurran varios escritores, cuentas, workers o requisitos operativos más exigentes |

No abrir el archivo SQLite mediante una carpeta de red. Mantener el archivo junto
al proceso que lo consulta; transmitir mensajes y respuestas de API por red.
Si PostgreSQL vive separado del backend, preferir una red privada cercana para
evitar multiplicar viajes de red por consulta.

Dirección futura, todavía no implementada:

`MT5/collectors → receptor local y cola durable → API central → BDD → dashboard`

El receptor local protege frente a cortes de conectividad. Hay dos confirmaciones
distintas: aceptación durable local y aceptación durable central. Una aceptación
local no significa que el servidor central ya tenga el dato. No descartar un lote
de la cola hasta confirmar su almacenamiento central; conservar deduplicación y
orden lógico suficiente para reintentos y correcciones.

La red agrega latencia, no necesariamente un coste incompatible con segundos de
demora. Usar lotes acotados, conexiones reutilizadas, límites de tamaño, reintentos
con espera creciente y prioridad de datos recientes. La demora total incluye
captura, cola, transporte, persistencia, proyección y refresco visual.

Fuentes técnicas: [usos de SQLite](https://www.sqlite.org/whentouse.html),
[SQLite sobre red](https://www.sqlite.org/useovernet.html) y
[arquitectura PostgreSQL](https://www.postgresql.org/docs/17/tutorial-arch.html).

## Plan de implementación inmediato

Avanzar por pasos verificables; agrupar PRs por capacidad funcional. Cada paso
incluye documentación operativa y pruebas dirigidas. CI ejecuta la suite completa.

### 1. Separar receptores y dashboard

**Estado:** implementación preparada en `feature/independent-telemetry-runtime`;
pendiente de validación manual, CI y merge humano.

**Implementación:** revisar supervisor, configuración y credenciales; extraer
entradas independientes para recepción y dashboard reutilizando la lógica actual.
Usar rutas absolutas de datos independientes del checkout y configuración segura
por instancia. Mantener identidad de cuenta/fuente, puertos y credenciales de
lectura estables entre reinicios independientes. No migrar ni fusionar v1/v2.

**Detalles:** el arranque debe rechazar instancias duplicadas y puertos ocupados,
no adoptar procesos ajenos. Un cierre debe detener solo sus procesos. Evitar que
una credencial efímera generada por el supervisor sea indispensable para reiniciar
el dashboard por separado. El almacenamiento de secretos se define antes del paso 2.

**Aceptación:** con dashboard detenido entran nuevas capturas y actividad; al
reiniciarlo aparecen los datos guardados. Su reinicio no reinicia MT5 ni receptores.
Pruebas dirigidas de ciclo de vida, identidad y colisión de puertos; chequeo manual
del dashboard a cargo del usuario.

**Reversión:** detener los nuevos procesos propios y volver al arranque supervisado
previo con las mismas bases y versiones compatibles.

### 2. Operación autónoma y mantenimiento programado

**Estado:** núcleo de mantenimiento y definiciones de Task Scheduler preparados en
`feature/autonomous-telemetry-startup`; pendiente validación manual en vista previa,
actualización del ADR y activación humana en una ventana operativa.

**Implementación:** preparar primero instalación en modo de vista previa. Usar un
servicio o tarea de arranque de Windows para los receptores, con reinicio acotado
ante fallos; tareas separadas para mantenimiento periódico. La lógica continúa en
Python; Windows Task Scheduler o el gestor de servicios solo inicia el proceso.
Documentar el equivalente futuro para Linux/macOS sin implementarlo todavía.

**Detalles:** usuario de ejecución con permisos mínimos, directorio de trabajo
explícito, secretos fuera de argumentos/logs/Git, ACL adecuadas y aprovisionamiento
sin prompts interactivos. No almacenar tokens en texto plano en la definición de
la tarea. Evitar ejecuciones solapadas mediante una guarda entre procesos, registrar
último éxito/fallo y limitar logs. Reutilizar la API de backup consistente de SQLite
para automatizar la copia local existente; no copiar a ciegas el archivo activo.

MT5 puede requerir una sesión interactiva: arrancar receptores al reiniciar Windows
no garantiza que el terminal esté abierto y conectado. Documentar y comprobar esta
dependencia sin iniciar ni cerrar automáticamente terminales de trading.

**Aceptación:** receptor reiniciable tras fallo, tarea duplicada rechazada, secretos
ausentes de comandos/logs y fallos visibles. Ensayo de reinicio del sistema solo
en una ventana autorizada, porque afectaría a los EAs. Backups verificables y
trabajo de mantenimiento interrumpible, sin bucles ilimitados.

**Reversión:** deshabilitar las tareas creadas, detener sus procesos y recuperar
el arranque manual. Activación operativa y nuevo ADR antes del despliegue.

### 3. Recuperación histórica completa y reanudable

**Estado:** preparado en `feature/resumable-complete-history`: carriles reciente y
profundo independientes, avisos acotados del callback, progreso durable, pausa,
fixtures extensos y desempate estable de ventanas mínimas. Validado en compilación
MT5 y con heartbeat real del piloto; resta la comparación con un reporte amplio.

**Implementación:** extender el collector de actividad existente con progreso
durable por cuenta, fuente, rango y versión de recuperación. Mantener seguimiento
independiente de actividad reciente y recuperación antigua, con un presupuesto de
trabajo por iteración. Priorizar datos recientes sin dejar el pasado sin avanzar.
No crear productores que reutilicen sesión/secuencia o compitan por el mismo cursor.

Dividir períodos grandes en ventanas y subdividirlos cuando excedan límites. No
avanzar un cursor ante truncamiento, error o falta de confirmación durable. Si una
ventana mínima sigue saturada, informar el bloqueo y diseñar un desempate estable
por ticket; no saltar registros con el mismo timestamp. Reanudar después de un
reinicio y releer un solapamiento seguro para eventos tardíos/correcciones.

Recuperar órdenes de todos los estados disponibles y deals. Reconciliar posiciones
por cuenta y position_id, incluyendo entradas anteriores al rango solicitado.
Conservar órdenes sin ejecución y movimientos de cuenta, sin contarlos como trades
autónomos. Historia de balance derivada requiere política explícita de movimientos;
equity intratrade antiguo no se inventa desde deals.

**Detalles:** inicio y final explícitos, progreso/cobertura consultables, pausado y
reanudado, presupuesto de CPU/red y memoria. Una ventana vacía consultada con éxito
es distinta de un error, una ventana no consultada o historia no suministrada por
el broker. No utilizar el offset actual como regla histórica de DST.

**Aceptación:** fixtures de más de 12 meses, ventanas saturadas, timestamps iguales,
duplicados, reenvíos, cierre parcial y posiciones abiertas antes del rango. Reinicio
en mitad de un lote sin pérdida ni duplicación; ingesta reciente sigue avanzando.
Comparar por bloques con un reporte MT5 del mismo corte y cuenta; registrar brechas.

**Reversión:** pausar la recuperación y conservar progreso/evidencia. No limpiar
variables globales ni reiniciar cursores manualmente como procedimiento ordinario.

### 4. Consultas y métricas sobre años de historia

**Estado:** en preparación en `feature/multi-year-history-queries`: filtros de
rango/estado/Magic aplicados en SQLite antes de paginar, recorrido cronológico sin
tope funcional de 500, métricas completas con memoria acotada y series visuales
de hasta 1.200 puntos. El esquema 5 y su migración verificada agregan índices para
revisión vigente y consultas por Magic. Falta medir `EXPLAIN QUERY PLAN` y latencia
con un dataset sintético representativo antes de considerar terminado el paso.

**Implementación:** inventariar consultas reales y diseñar índices para cuenta,
posición, fecha y Magic. Aplicar filtros sobre la versión vigente de cada entidad
antes de paginar, sin resucitar observaciones anteriores cuya atribución cambió.
Usar migraciones explícitas con copia consistente y verificación para nuevos índices
o proyecciones. Evaluar plan SQL con `EXPLAIN QUERY PLAN`.

Sustituir el tope de 500 como límite funcional de métricas por procesamiento
acotado en lotes, agregados SQL o proyecciones durables según cada fórmula.
No promediar ratios ni calcular resultados definitivos con una muestra parcial.
Separar el conjunto completo usado por las métricas del muestreo visual de gráficos.
Paginación estable y consultas largas con cancelación, presupuesto y error explícito.

**Aceptación:** dataset sintético reproducible de varios años y múltiples EAs;
resultados equivalentes a una referencia determinista, consumo de memoria acotado
y captura reciente progresando durante consultas y recuperación. Acordar presupuesto
de latencia/recursos al inspeccionar el hardware; no inventar un objetivo universal.
El criterio es corrección y capacidad prevista, no esperar años de uso real.

**Reversión:** conservar esquema compatible o restaurar una copia mediante procedimiento
autorizado. Documentar compatibilidad de versiones y evitar perder escrituras nuevas
al restaurar una copia anterior.

### 5. Retención por clase de información

**Implementación ahora:** inventario de crecimiento de bases/copias, espacio libre,
tipos de evidencia y dependencias de reconstrucción, auditoría y deduplicación.
Mantener órdenes/deals/ciclos y su procedencia a largo plazo. Conservar la política
actual sin TTL mientras se define la política nueva.

**Diseño posterior:** separar capturas frecuentes de cuenta, actividad, evidencia
cruda, proyecciones, claves de deduplicación y backups. Para snapshots antiguos,
evaluar agregados que preserven mínimos/máximos y resolución declarada. Un agregado
no preserva necesariamente el orden temporal requerido por drawdown; validar cada
métrica antes de descartar originales. Evitar eliminar mensajes que respaldan
foreign keys, detalles de ciclos o replays.

**Aceptación:** conocer qué se conserva y qué podría perderse; previsualización de
cualquier limpieza, backup y restauración probada antes de borrados. Alertar falta
de espacio; nunca convertirla en limpieza silenciosa ni confirmaciones falsas.
No fijar todavía plazos arbitrarios de eliminación. Nuevo ADR y aprobación humana
antes de ejecutar una política destructiva.

## Etapa posterior: cuenta del socio y servidor central

Antes de depender de datos reales: instalación en la cuenta/terminal autorizada,
acceso de lectura, límites de carga, backup externo, restauración y objetivos de
pérdida/recuperación acordados. La excepción de datos demo descartables no se extiende
a la cuenta real. Confirmar alcance histórico disponible y modo hedging/netting.

Para servidor remoto: TLS, autenticación por productor, aislamiento por cuenta,
rotación de secretos, cuotas, cola durable local y observabilidad del retraso.
No exponer los servidores loopback actuales directamente a Internet ni cambiar
simplemente su dirección de escucha. El navegador accede al backend, nunca a la BDD.

### Análisis posterior a los cinco pasos: API central de ingesta

Una vez completados los cinco pasos de este plan, analizar la extracción del
receptor y la base fuera de la VPS de MT5. Los collectors `Telemetry` y
`TradingLabActivity` ya publican contratos HTTP y no escriben SQLite directamente;
la evolución propuesta consiste en conservar esos contratos o versionarlos para
una API central que valide y persista la información en la base elegida.

No conectar los EAs directamente a la base ni exponer los receptores loopback
actuales a Internet. El análisis debe cubrir HTTPS, credenciales distintas por
productor y fuente, autorización por cuenta/rol, idempotencia, secuencia, límites
de tamaño y frecuencia, versionado de contratos y observabilidad del atraso. Debe
comparar dos alternativas: publicación remota directa con el outbox acotado del
EA, y relay local con cola durable. La segunda es la referencia inicial porque
permite seguir aceptando lotes durante cortes entre VPS y servidor central.

El objetivo es poder trasladar API, base y dashboard sin reconfigurar la lógica
de trading ni perder trazabilidad. La selección de SQLite junto al backend o
PostgreSQL central, el despliegue y la migración quedan fuera de los cinco pasos
actuales y requerirán análisis, ADR y aprobación humana propios.

Evaluar PostgreSQL si el diseño central exige escritores concurrentes, separación
backend/BDD por red, múltiples instancias de backend o disponibilidad gestionada.
Comparar con SQLite centralizado según requisitos, coste operativo y prueba sintética.
Si se adopta: nuevo ADR, mapeo de tipos/precisión/timestamps, importación verificable,
reconciliación de conteos/importes/cobertura y plan de corte y reversión. No introducir
ahora una abstracción genérica de múltiples motores ni escritura dual permanente.

## Primer incremento a ejecutar tras aprobación

Comenzar por el paso 1: separar arranque y parada de receptores y dashboard,
resolviendo configuración y credenciales para reinicios independientes. Un PR por
esa capacidad. Luego automatización operativa y recuperación histórica, en ese
orden; revisar índices desde el inicio si las consultas conocidas lo requieren.
Este documento no instala tareas, abre puertos, migra datos ni modifica MT5.
El primer incremento agrega supervisores separados, credenciales estables
provistas en memoria y una raíz local de datos independiente del checkout.

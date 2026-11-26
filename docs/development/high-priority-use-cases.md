# Casos de uso de prioridad alta

Base revisada `8e2ea6c`. Los nombres en el pseudocódigo describen responsabilidades propuestas. [Roadmap](high-priority-roadmap.md) · [Hallazgos originales](tradinglab-static-review.md).

## 1. Crear y restaurar una copia multicuenta

**Entrada y contrato.** El operador elige el directorio de datos y la base central. Las dos entradas de línea de comandos deben aceptar las versiones centrales conocidas por el validador de esquema. La compatibilidad de copia es independiente de la capacidad de consolidar o eliminar datos. Hoy el mantenimiento pasa explícitamente la versión 8 al construir el plan. [Plan de copia](../../src/tradinglab/telemetry/backup.py) · [Comando de backup](../../scripts/backup_telemetry_db.py) · [Comando de mantenimiento](../../scripts/run_telemetry_maintenance.py) · [Esquema central](../../src/tradinglab/telemetry/central_schema.py).

1. Compartir la lista de esquemas centrales soportados con el validador. Revisar ambos comandos y conservar la posibilidad de restringir versiones en llamadas que ya especifican una política propia.
2. Validar en modo lectura la ruta, versión y estructura antes de anunciar que la copia se puede realizar. Si se pidió mantenimiento diario, validar por separado que esa operación admite el esquema antes de iniciar el trabajo.
3. Copiar con la API de backup SQLite usando las protecciones existentes. Validar el esquema y la integridad del archivo copiado antes de publicar. Usar la copia para comprobar los datos cuando pueda haber escrituras concurrentes en el origen.
4. Comprobar restauración en una ubicación nueva mediante apertura normal del producto para esa versión. Una discrepancia impide dar por válida la entrega.

~~~text
preparar(solicitud):
    abrir origen existente en modo lectura
    validar esquema central y versión admitida por el plan
    si solicita mantenimiento diario: validar compatibilidad de esa operación
    si vista previa: devolver operaciones autorizadas

ejecutar:
    adquirir bloqueo existente cuando corresponda
    comprobar de nuevo origen y esquema al iniciar copia
    copiar snapshot SQLite a staging
    validar esquema, quick_check y foreign_key_check de la copia
    generar manifiesto y digest, publicar con la protección existente
    si copia publicada y mantenimiento diario solicitado y compatible:
        ejecutar mantenimiento acotado para la cuenta indicada
~~~

**Aceptación.** Probar ambas entradas con esquemas 8, 9 y 10, versión desconocida, estructura incompatible y escritura concurrente. En una base 10 con dos cuentas verificar tras restaurar el digest, cuentas, separación de tickets, rangos y ciclos esperados. Ante solicitud diaria incompatible o fallo de copia, comprobar que los datos del origen se conservan y el resultado identifica la operación fallida.

## 2. Resolver cobertura para historial, proyección y métricas

**Entrada y contrato propuesto.** La unidad de evidencia es cuenta, entidad y ventana identificada por ambos extremos. El instante de captura y la sesión distinguen revisiones de esa ventana. Una captura vacía y completa acredita el intervalo. La cobertura temporal y la existencia de un ciclo elegible son conceptos distintos. Una operación abierta antes del corte conserva las reglas de elegibilidad actuales. [Persistencia e informe](../../src/tradinglab/telemetry/sqlite_store_v2.py) · [Proyección](../../src/tradinglab/telemetry/remote_positions.py) · [Cliente financiero](../../src/tradinglab/dashboard/telemetry_v2.py).

1. Caracterizar los extremos antes de compartir lógica. El informe filtra el límite superior con comparación estricta mientras la proyección comprueba milisegundos inclusivos. Normalizar en la frontera de cada consumidor y volver a su formato público al responder.
2. Resolver las observaciones por ventana. Conservar la precedencia de secuencias numéricas de una misma fuente y sesión. Para una misma ventana usar la revisión más reciente. Si en ese instante hay observaciones incompatibles entre sesiones, tratar la ventana como incierta. Diferentes ventanas válidas pueden completar una unión aun cuando tengan idéntico instante de captura.
3. Usar la cobertura resuelta tanto en la consulta como en la elegibilidad de la proyección. Conservar la validación de la cadena paginada antes de registrar cobertura y la exclusión de mensajes de reconciliación por posición. Mantener la resolución de conflictos de tickets independiente.
4. Para métricas, obtener cobertura de deals y órdenes bajo el mismo presupuesto de tiempo. Intersectar intervalos completos. Documentar la unidad de cualquier contador combinado y conservar la forma de respuesta. Un fallo al consultar una entidad debe reflejar evidencia no disponible.
5. Revisar las posiciones ya materializadas. Un cambio de cobertura puede retirar o añadir elegibilidad incluso con cero tickets nuevos. Identificar tanto ciclos existentes como posiciones pendientes afectadas por el intervalo. Prever reconstrucción acotada y reanudable por cuenta para instalaciones previas antes de presentar resultados como actualizados.

~~~text
resolver(cuenta, entidad, intervalo):
    leer ventanas de esa cuenta y entidad que solapan el intervalo
    para cada ventana exacta:
        tomar el instante más reciente para esa ventana
        en cada fuente y sesión conservar su secuencia numérica mayor en ese instante
        comparar evidencia equivalente entre supervivientes
        si coinciden y acreditan completitud: agregar intervalo completo recortado
        si hay evidencia parcial o conflicto: registrar incertidumbre
    ordenar y fusionar completos adyacentes o superpuestos
    devolver rangos y diagnóstico

al recalcular posición:
    usar resolver para los intervalos de deals y órdenes requeridos
    aplicar las reglas vigentes de apertura, cierre y propiedad
    persistir resultado y estado pendiente en la transacción de proyección

al calcular métricas:
    coberturas = consultar ambas entidades para cuenta y filtro temporal
    cobertura_financiera = intersección de sus rangos completos
    devolver métricas de ciclos elegibles con esa cobertura
~~~

**Aceptación.** Dos ventanas distintas con la misma captura deben conservarse. Dos sesiones en desacuerdo sobre una misma ventana deben dar el mismo diagnóstico en lector y proyección. Incluir dos cuentas con tickets iguales, fronteras adyacentes y un hueco de 1 ms, revisión parcial posterior, lote vacío completo, cadena de páginas interrumpida y reenvío duplicado. Con deals completos y órdenes parciales, la pantalla debe mostrar el hueco. Comparar una base reconstruida desde evidencia con la actualización de una base que ya tenga proyecciones.

## 3. Dar turno a los datos cuando vence el heartbeat

**Entrada y contrato.** Un tick puede encontrar un mensaje pendiente, un heartbeat vencido y trabajo de recuperación. El mensaje pendiente conserva prioridad hasta recibir confirmación o entrar en el tratamiento de error existente. Un turno de datos puede preparar una página sin emitir un lote. [Planificación, recuperación y ACK](../../apps/mt5-telemetry-collector/TradingLabActivity.mq5).

1. Mantener la resolución de cuenta y el reintento al inicio del ciclo. Separar la elección entre heartbeat y datos de la elección existente entre vía reciente e histórica.
2. Registrar si después del último heartbeat confirmado se debe conceder un turno de datos. Reiniciar ese estado al seleccionar una cuenta nueva. Mantener una sola secuencia por mensaje generado y una sola solicitud de envío por tick.
3. Hacer que un turno de datos distinga trabajo realizado, ausencia de trabajo y fallo. Una continuación de escaneo cuenta como trabajo realizado. Evitar invocar dos veces el selector de vía si modifica estado.
4. Actualizar hora del heartbeat en su confirmación. Los errores de transporte deben pasar por el reintento actual con el mismo cuerpo.

~~~text
en tick:
    verificar identidad y preparar recuperación
    si hay mensaje pendiente: intentar su envío según backoff y terminar
    si heartbeat vencido y no se debe turno de datos:
        preparar heartbeat, intentar envío y terminar
    consumir el turno de datos y ejecutar una vez el planificador de recuperación
    si hubo preparación, envío o fallo: terminar
    si heartbeat vencido y cuenta lista: preparar heartbeat e intentar envío

en ACK de heartbeat: registrar hora y marcar turno de datos debido
en ACK de datos: aplicar las reglas existentes de avance de cursor o página
~~~

**Aceptación.** Con ambos intervalos iguales y datos continuos, trazar al menos seis ticks y verificar ACK de heartbeat y avance de cursor. Repetir con ticks tardíos, escaneo multipaso, cuenta ociosa, cambio de cuenta y rechazo transitorio de un lote. Un reintento conserva secuencia y cuerpo. Un heartbeat no debe adelantar un cursor. Con intervalos predeterminados, la recuperación reciente e histórica debe mantener su política de turnos.

## 4. Generar el SetUp a partir de binarios verificables

**Entrada y contrato.** Tres programas MT5, cabeceras compartidas, fuentes Python distribuibles y recursos del dashboard. El compilador y el empaquetador necesitan acordar ubicación y procedencia por programa. Un hash del ZIP solo verifica lo que se incluyó. [Compilación](../../scripts/build_mt5_multi.ps1) · [Empaquetado](../../scripts/package_tradinglab_setup.py).

1. Alinear compilador y consumidores con la salida del paquete bajo `_storage/setup/compiled`. Compilar cada selección en un staging nuevo y preservar la selección individual y la opción All.
2. Calcular por EA una firma del fuente y cabeceras a partir de los bytes copiados al staging. Usar todas las cabeceras compartidas como criterio conservador si aún no se resuelven dependencias transitivas. Registrar versión del compilador, entradas y hash del EX5 después de verificar resultado, log y existencia del binario recién generado.
3. Publicar los artefactos de compilación bajo bloqueo compartido con el empaquetador o con generaciones inmutables. Un fallo intermedio debe dejar un conjunto anterior válido o una inconsistencia detectable.
4. Construir la lista distribuible de Python y assets a partir de las rutas Git previstas. Leer una vez los bytes a empaquetar y verificar el manifiesto por EA contra esos mismos bytes. Conservar las verificaciones del ZIP y la publicación por digest.

~~~text
compilar(selección):
    para cada EA elegido:
        copiar entradas a staging nuevo
        ejecutar MetaEditor y verificar éxito sin advertencias y EX5 recién generado
        crear manifiesto por EA con hashes de entradas y binario
        publicar generación validada

empaquetar:
    para cada EA obligatorio:
        abrir generación consistente
        comparar conjunto de nombres y hashes esperados con fuentes de distribución
        verificar hash del EX5 y agregar los bytes comprobados
        si falla una comprobación: detener e identificar el EA que requiere compilación
    agregar archivos Python y assets distribuibles, generar ZIP temporal
    releer y comprobar entradas y hashes antes de publicar
~~~

**Aceptación.** Compilación limpia de los tres programas seguida de empaquetado. Cambio de cabecera y recompilación de uno solo debe bloquear el paquete hasta actualizar el resto afectado. Cambio de un único MQ5 debe invalidar ese programa. Cubrir un EX5 sustituido, compilación interrumpida y un Python local sin seguimiento. La instalación desde un paquete válido debe encontrar los tres programas con los nombres actuales.

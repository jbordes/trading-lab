# Casos de uso para optimizar los collectors

Aplicar el [orden del roadmap](collector-optimization-roadmap.md) y completar la [comparación antes/después](collector-optimization-baseline.md). Los pasos describen cambios futuros y sus comprobaciones.

## UC1. Localizar el costo de una descarga sin interferir con los operadores

1. Preparar dos entornos demo comparables, misma versión MT5 y snapshot inicial de almacenamiento de prueba. Registrar versión del collector, parámetros efectivos, rango, CPU asignada, memoria, topología, RTT y carga coexistente. Hacer al menos tres repeticiones por variante en orden alternado y anotar si el historial del bróker ya estaba en caché.
2. Muestrear externamente el proceso MT5 identificado por la terminal demo. Tomar diferencia de tiempo CPU entre muestras, segundos transcurridos y memoria de trabajo. Identificar aparte los procesos de relay y API. Comparar la latencia de los operadores solo cuando exista un registro de evento y atención que permita medirla.
3. En una revisión que conserve el comportamiento, tomar reloj monotónico al entrar y salir de OnTimer, HistorySelect, lectura de propiedades, serialización, conversión a bytes, WebRequest y persistencia del cursor. Incluir retornos tempranos, heartbeats y reintentos. Agrupar por fase, carril, éxito y rango de duración en contadores de tamaño fijo. Emitir resúmenes espaciados. Separar tiempo de pared y consumo de CPU.
4. Correlacionar localmente sesión, secuencia y recepción central. Medir por separado trabajo reciente y profundo. Para diferencias entre hosts, registrar sincronización y desfase de los relojes. Reportar cola y frescura con percentiles, cantidad de muestras y máximos. Contrastar instrumentación encendida y apagada.
5. Aceptar la instrumentación si conserva contenido y tiempos dentro de la variación de los controles. Guardar solo resultados agregados. Esta revisión instrumentada será el control de las optimizaciones siguientes.

## UC2. Entregar una ventana densa que supera el tamaño admisible

1. En BuildPagedActivityPayload mantener el orden total existente por tiempo, tipo y ticket, la identidad del rango y su huella. Construir un prefijo de filas y medir el sobre final en UTF-8, incluida la metadata de paginación.
2. Si excede 262.144 bytes, reducir el prefijo hasta encontrar uno válido. Recalcular through con la última fila incluida, has_more con las filas restantes y el estado de ambas colecciones. Conservar en memoria el mensaje listo durante el reintento.
3. Si una fila sola excede el límite, bloquear y diagnosticar el rango afectado de forma acotada, conservar cursor y mantener el otro carril operativo. Incluir tamaño y rango en el diagnóstico. Evitar reconstruir indefinidamente esa página.
4. Avanzar through únicamente al confirmar el relay. Persistir el cursor temporal al confirmar la última página. Ante cambio de huella, reanudar con las reglas de reinicio de ventana. Tras reiniciar el proceso se admite reproducir desde el último cursor durable.
5. Probar límite exacto, exceso de un byte, Unicode, múltiples filas en el mismo milisegundo, una fila imposible, pérdida de ACK, reinicio y cobertura final. Comparar conjunto y contenido de tickets y observar progreso del otro carril.

### Cómo reproducir el bloqueo

1. Ampliar la historia simulada de `tests/mql5/activity_collector_test.mq5`. Generar, por ejemplo, 201 órdenes finalizadas dentro del mismo minuto con tickets únicos. Incluir varias con la misma marca de milisegundo y alguna ejecución con la misma marca. Configurar 200 filas por página y dejar que Activity llegue a su ventana mínima. Esto prueba que se activa la paginación por cantidad.
2. Medir el sobre completo de la primera página con los campos, comentarios y caracteres Unicode que conserva el serializador. La condición a reproducir es una página de hasta 200 filas que supere el máximo de bytes. Usar 262.144 bytes si los datos de prueba permiten alcanzar ese tamaño con los límites reales de los campos. Si quedan por debajo, inyectar en la prueba nativa un límite menor, entre el tamaño de una fila y el de la primera página. Mantener el límite de producción en 262.144 bytes.
3. Avanzar dos o más turnos con un relay simulado que acepta mensajes válidos. Con el comportamiento actual se vuelve a construir la misma página, el relay no recibe ese sobre y el cursor no avanza. Verificar también que una página apenas dentro del límite se acepte.
4. Con la corrección, registrar el tamaño de cada solicitud y los límites de las páginas. Cada solicitud debe caber y entregar el siguiente prefijo de filas ordenadas por tiempo, tipo y ticket. Simular pérdida del ACK de una página y luego aceptarla. Comprobar que se reenvían los mismos bytes, que la página siguiente no salta ni repite filas dentro de la secuencia confirmada y que el cursor temporal avanza únicamente al confirmar la última página. Comparar la cobertura y las filas admitidas con la fixture.
5. Reducir el límite por debajo del sobre con una sola fila para cubrir el caso imposible. Verificar diagnóstico, cursor conservado y progreso del carril sano. Ejecutar la prueba en el harness de MT5 con historia y transporte simulados. La carga de Juampi tuvo cero páginas y sirve para comparar UC3.

## UC3. Ajustar el tamaño del historial antiguo a su densidad

1. Inicializar el tamaño propuesto del carril profundo al valor de WindowSeconds. Conservar límites explícitos mínimo y máximo y el comportamiento vigente del carril reciente.
2. Calcular fin como el mínimo entre inicio más ventana propuesta y límite profundo actual. Ante exceso de filas o bytes dividir como hoy y recordar el tamaño reducido para el siguiente tramo. Cuando el mínimo siga saturado pasar a UC2.
3. Solo después del ACK final de una ventana completa, actualizar el cursor con el solapamiento vigente. Tras ventanas consecutivas vacías o poco densas incrementar gradualmente el tamaño hasta el máximo elegido en la prueba. Registrar divisiones, filas, bytes y ventanas vacías. Reiniciar la estimación al cambiar de cuenta.
4. Mantener alternancia entre carriles y prioridad operativa de transacciones recientes. Una ventana vacía confirmada acredita solo el intervalo leído. Un error de selección conserva cursor y cobertura.
5. Alternar tramos vacíos y densos, insertar actividad reciente durante la descarga y cortar el enlace durante una división. Comparar igualdad de filas y unión de intervalos por colección. Aceptar si baja el costo total por intervalo cubierto con frescura reciente comparable.

La primera implementación se aplica solo al carril profundo. Empieza con `WindowSeconds` y conserva el tamaño reducido cuando una ventana se subdivide. Duplica el tamaño tras dos ventanas completas consecutivas y confirmadas que usen hasta un cuarto del límite de filas de cada colección y del presupuesto de bytes del payload. El máximo es 24 horas. Las páginas y las ventanas recortadas por el final del rango no cuentan para crecer. Tras cambiar de cuenta, la estimación vuelve a su tamaño inicial. Usar `EnableAdaptiveDeepWindow=false` para el control con el mismo binario.

Con actividad continua, los dos carriles alternan cuando ambos tienen trabajo, a partir de la confirmación de un lote o página. Un lote pendiente y su reintento conservan prioridad. La preparación de una ventana puede ocupar más de un turno. Conservar la recuperación profunda habilitada para cubrir desconexiones y reinicios, incluso en cuentas cuyo historial configurado empieza el día de inicio de la operativa. La opción `EnableDeepRecovery` sigue disponible para una pausa deliberada.

## UC4. Reutilizar los bytes de un mensaje listo

1. Medir cuántas conversiones y bytes temporales genera cada tipo de mensaje. Distinguir los borradores que se descartan al dividir de los mensajes preparados para enviar.
2. Codificar el sobre definitivo una vez, comprobar longitud sin el NUL final y asociar buffer, longitud, secuencia e identidad de origen al lote pendiente o entrada de cola.
3. En cada intento pasar exactamente esos bytes a WebRequest. Liberar el buffer tras ACK, descarte explícito o cierre según el contrato de cada collector. Evitar conservar simultáneamente todas las cadenas completas y sus copias binarias.
4. Comparar antes/después con caracteres multibyte, escape de JSON, límite exacto, timeout y cambio de cuenta. Exigir mismos bytes en el reenvío, mismos límites y memoria acotada con la cola llena.

## UC5. Evitar transmitir repetidamente el historial de Telemetry

1. Inventariar lectores del campo history, compactación, consultas financieras y clientes. Registrar cómo distinguen historial vacío, truncado, error y última muestra vigente por cuenta.
2. Comparar el tiempo desde una ejecución hasta que Activity la expone. Verificar si cada consumidor tolera ese tiempo. Para los que necesitan la muestra reciente, definir referencia o actualización explícita de historial con origen, período y frescura.
3. Introducir primero lectores compatibles con mensajes actuales y nuevos. Conservar balance, equity, ancla de tiempo y posiciones/órdenes abiertas en las capturas. Tras cambio de cuenta o reinicio exigir una base propia de esa cuenta.
4. Reducir las inclusiones repetidas solo con el receptor compatible. Probar mensajes perdidos, reinicio del lector, historial sin ejecuciones, ráfaga y retorno al emisor anterior. Comparar bytes, costo en MT5, resultados financieros y antigüedad visible.

## UC6. Señalar cuándo una colección abierta es parcial

1. En BuildPositions y BuildOrders recoger total inicial, filas emitidas, límite y fallos de lectura. Considerar que la lista puede cambiar durante la enumeración.
2. Definir metadata separada para posiciones y órdenes con total observado y estado de completitud. Si hubo truncamiento o lectura fallida marcar parcial. Documentar que esta enumeración no es una instantánea atómica del bróker.
3. Adaptar validadores, almacenamiento y lectores antes de activar el nuevo emisor. En una muestra parcial conservar antigüedad y evidencia anterior de tickets omitidos. Una ausencia parcial no certifica un cierre.
4. Probar colecciones vacías, justo en el límite, límite más uno y desaparición de un ticket durante la lectura. Verificar que la vista distinga muestra incompleta y cierre confirmado sin alterar los importes de cuenta.

## UC7. Limitar trabajo perdido durante una desconexión

1. Ensayar por separado MT5 → relay y relay → API con entorno aislado. Medir trabajo de captura, espera HTTP, entradas, descartes, antigüedad y tiempo hasta recuperar.
2. Preservar la semántica de Activity: mismo lote y origen en reintento, ACK durable y cursor por cuenta. Para Telemetry cuantificar huecos en equity y posiciones cuando se llena su cola de 12 muestras o se reinicia.
3. Si el costo de construir capturas durante el corte es relevante, acordar primero con los consumidores qué muestras pueden perderse. Mantener la cadencia de captura si se necesitan extremos intradía. Evaluar muestreo reducido únicamente con política explícita y métricas de huecos.
4. Reconectar tras menos y más de 12 intervalos, cambiar de cuenta con mensajes en cola y reiniciar. Comprobar atribución original, huecos visibles, reanudación y ausencia de doble efecto en la API.

## UC8. Reducir reescaneos en ventanas densas

1. Crear fixture controlada con varias páginas, empates de tiempo y continuaciones por presupuesto. Medir HistorySelect, filas revisitadas por página y CPU de selección de claves.
2. Si domina el mantenimiento ordenado de las mejores K claves, probar una estructura acotada y ordenar solo el prefijo de salida. Si domina la relectura, evaluar una caché acotada de claves por ventana, con invalidación por cuenta, rango y cambios observables. Detener la optimización si la memoria requerida supera el presupuesto.
3. Mantener orden estable, cobertura final y reinicio seguro incluso si cambian filas mientras se escanea. La huella actual compara claves. Ensayar también una corrección de importe con igual ticket y tiempo y definir cómo se reconcilia.
4. Comparar contra control con la misma fixture, número de páginas, cursores, hashes finales, CPU y pico de memoria. La muestra de Juampi tuvo cero páginas y no permite evaluar esta mejora.

## UC9. Usar más de un turno de envío cuando haya capacidad

1. Considerar este cambio solo si UC1 y UC3 muestran espera de temporizador dominante y margen real en MT5.
2. Después del primer ACK evaluar duración total del callback, prioridad reciente, heartbeat debido, espera de reintento y costo observado de la siguiente unidad. Ceder si hay presión. Una segunda llamada HTTP síncrona puede consumir su timeout completo.
3. Limitar explícitamente lotes por turno y aplicar espera ante errores. Si el presupuesto no tolera ese timeout, programar trabajo para un turno posterior.
4. Comparar control, red lenta y ráfaga de transacciones. Aceptar solo si mejora el historial sin degradar los extremos de latencia de los operadores, la cola ni la frescura reciente.

## UC10. Evitar que un destino lento demore otras cuentas en el relay

1. Medir edad del pendiente más antiguo por flujo, demora de admisión y tiempo de forward con dos cuentas, una lenta y otra sana. Confirmar por separado el ACK durable de entrada.
2. Si un flujo afecta al otro, comparar equidad del planificador o concurrencia limitada por flujo. Garantizar un envío en vuelo por flujo cuando se necesite orden, accesos SQLite seguros, idempotencia y backoff independiente.
3. Interrumpir el destino tras commit central y antes de ACK. Reiniciar con cola pendiente y luego restablecer el destino lento. Verificar orden, aislamiento de cuentas, ausencia de dobles efectos y drenaje.
4. Aceptar solo si mejora la antigüedad del flujo sano sin trasladar presión a MT5 ni aumentar pérdida o contención. Documentar topología y resultados frente al relay vigente.

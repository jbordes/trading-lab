# Línea base de Activity y Telemetry

## Corrida observada

Demo Juampi, historial configurado desde el 1 de noviembre de 2026 hasta la puesta al día el 25 de noviembre. Activity 0.9.0 y Telemetry 0.3.4. Medición retrospectiva por hora de **recepción central UTC**, sobre la instalación existente. Una fuente y una sesión de Activity en el intervalo. Las horas del historial son las del servidor del bróker.

| Medida | Resultado antes del cambio |
| --- | --- |
| Primer y último lote UTC | 12:22:43.700602 y 12:52:13.672493 |
| Primer heartbeat con atraso histórico dentro del solapamiento de 5 s | 12:52:23.741291 UTC, 29 min 40,041 s desde el primer lote |
| Lotes, vacíos, paginados, heartbeats | 136, 49, 0, 29 |
| Máximo de bytes del mensaje Activity persistido | 67.372 |
| Última observación por tipo y ticket dentro de la corrida | 8.021 órdenes y 71 ejecuciones |
| SHA-256 de órdenes | `b38f0a65092cd8a372d5405ad9d66f9be4e96a9258ed4c1fbbfe009328bd4cc0` |
| SHA-256 de ejecuciones | `aa2049d92780f93d2968e1a8941c57385bfa0a5f47ff203bc2fc39afd6a8c7bc` |
| Telemetry durante el mismo corte de recepción | 358 capturas con historial, 31 bloques distintos, 127.806 bytes de historial extraído en 634.560 bytes de mensaje almacenado (20,1 %) |

La proporción de Telemetry depende del intervalo elegido. Los tamaños describen la representación JSON de SQLite. Los hashes incluyen los campos de la fila de negocio y permiten cambiar la agrupación por lotes. Un bróker puede corregir el histórico posteriormente. Ante una discrepancia, comparar por ticket y campo en privado antes de atribuirla al collector.

## Control con almacenamiento nuevo y los mismos collectors

Segunda corrida del 25 de noviembre de 2026 en la demo de Juampi. Se mantuvo abierta la terminal con los EAs operadores, se retiraron ambos collectors y se preservaron las bases anteriores. Con el relay drenado se activaron una central con la misma alta y fecha desde y una cola vacía. El auxiliar guardó los cursores y reinició exclusivamente el estado de Activity de esa cuenta. Activity 0.9.0 y Telemetry 0.3.4 emitieron una sesión cada uno. El estado de la caché de MT5 no se controló.

| Medida | Primera corrida | Segunda corrida de control |
| --- | ---: | ---: |
| Primer lote → cobertura completa del mismo intervalo de órdenes y ejecuciones | 29 min 19,908 s | 27 min 40,091 s |
| Primer lote → primer heartbeat saludable con atraso ≤ 5 s | 29 min 40,041 s | 28 min 30,034 s |
| Lotes / vacíos / paginados | 136 / 49 / 0 | 135 / 49 / 0 |

El control comenzó a las 19:02:54.507330 UTC y notificó la puesta al día a las 19:31:24.541824 UTC. Para reproducir el primer indicador, recorrer las ventanas completas en orden de admisión central, unir sus intervalos por colección y tomar la primera recepción en que ambas uniones cubran desde 1793491200000 hasta 1795618323000 ms del bróker inclusive. La segunda corrida siguió hasta 1795642264000 ms con cobertura continua. En el corte común coincidieron las huellas indicadas arriba para las 8.021 órdenes y 71 ejecuciones. También coincidieron los campos de ciclo y detalle de las 35 posiciones reconstruidas cuyo inicio y último evento quedaron dentro del corte, comparando la proyección disponible en cada base al leerla. Se recibieron 344 capturas de Telemetry hasta el heartbeat, incluida la anterior al primer lote. La comprobación posterior del relay registró 524 confirmados y cero pendientes o rechazados.

| Métrica del proceso completo de MT5 | Antes de volver a cargar los collectors | Durante la recuperación |
| --- | ---: | ---: |
| Muestras / segundos entre primera y última muestra | 67 / 330,57 | 342 / 1.707,67 |
| CPU media, equivalente de un núcleo lógico | 29,55 % | 29,56 % |
| CPU p95 de los intervalos de muestreo | 37,46 % | 34,95 % |
| Pico de memoria residente | 304,73 MiB | 304,88 MiB |
| Pico de memoria privada | 366,84 MiB | 376,66 MiB |

Se tomó CPU acumulada del proceso y reloj monotónico cada cinco segundos. La media es 100 × segundos de CPU / segundos transcurridos. Los segmentos son consecutivos y de distinta duración. Se desconoce qué fracción corresponde a los collectors y cómo varió la carga de los operadores. La latencia de los EAs y el costo interno por fase siguen pendientes. La diferencia de tiempos entre dos corridas de la misma versión sirve como referencia de variación.

## Reproducción de la referencia

Abrir la base central mediante URI SQLite con `mode=ro` y `PRAGMA query_only=ON`. Usar un intervalo semiabierto y una sola cuenta/sesión de Activity. Estas consultas reproducen la corrida histórica en esa instalación. En una base con múltiples cuentas, filtrar explícitamente la fuente de cada collector antes de agregar.

```sql
WITH sample AS (
  SELECT kind, received_at_utc, payload_json AS body
  FROM telemetry_v2_messages
  WHERE collector_version = 'activity-0.9.0'
    AND received_at_utc >= '2026-11-25T12:22:00'
    AND received_at_utc < '2026-11-25T12:52:24'
)
SELECT kind, count(*) AS messages, min(received_at_utc), max(received_at_utc),
       sum(json_extract(body,'$.payload.orders.total') = 0 AND
           json_extract(body,'$.payload.deals.total') = 0) AS empty_batches,
       count(json_extract(body,'$.payload.pagination')) AS pages,
       max(length(CAST(body AS BLOB))) AS max_stored_bytes,
       min(CASE WHEN CAST(json_extract(body,'$.payload.activity_progress.backlog_msc') AS INTEGER)
                     <= 5000 THEN received_at_utc END) AS first_within_overlap
FROM sample GROUP BY kind;
```

Este fragmento Python reproduce los hashes y la medida de Telemetry en la instalación original. Solo imprime agregados. Para una repetición futura, delimitar la nueva corrida por sus marcas de recepción y aplicar además idénticos límites de tiempo de evento del bróker a las filas comparadas. Obtener esos límites de la unión de ventanas originales en `activity_coverage`. Comparar independientemente continuidad, extremos y huecos de cada colección.

```python
import hashlib, json, os, sqlite3
from pathlib import Path

db = Path(os.environ["LOCALAPPDATA"]) / "TradingLab-multicuenta" / "central.sqlite3"
with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    rows = conn.execute("""
        WITH ranked AS (
          SELECT entity_type,ticket,row_json,row_number() OVER (
            PARTITION BY account_id,entity_type,ticket ORDER BY message_id DESC) AS n
          FROM activity_observations JOIN telemetry_v2_messages USING(message_id)
          WHERE telemetry_v2_messages.collector_version='activity-0.9.0'
            AND telemetry_v2_messages.received_at_utc >= '2026-11-25T12:22:00'
            AND telemetry_v2_messages.received_at_utc < '2026-11-25T12:52:24'
        ) SELECT entity_type,row_json FROM ranked WHERE n=1 ORDER BY entity_type,ticket
    """)
    digests, counts = {}, {}
    for kind, row in rows:
        counts[kind] = counts.get(kind, 0) + 1
        digest = digests.setdefault(kind, hashlib.sha256())
        digest.update(
            (
                json.dumps(
                    json.loads(row), sort_keys=True, ensure_ascii=True, separators=(",", ":")
                )
                + "\n"
            ).encode("ascii")
        )
    print({k: (counts[k], v.hexdigest()) for k, v in digests.items()})
    print(
        conn.execute("""
      SELECT count(*), count(DISTINCT json_extract(payload_json,'$.payload.history')),
             sum(length(CAST(json_extract(payload_json,'$.payload.history') AS BLOB))),
             sum(length(CAST(payload_json AS BLOB)))
      FROM telemetry_messages WHERE collector_version='0.3.4'
        AND received_at_utc >= '2026-11-25T12:22:00'
        AND received_at_utc < '2026-11-25T12:52:24'
        AND json_type(payload_json,'$.payload.history')='object'
    """).fetchone()
    )
```

## Comparación con la instrumentación activada y desactivada

Se ejecutó una corrida por variante el 25 de noviembre de 2026 en Juampi con los EX5 de `f04ceb9`, una central y una cola limpias por corrida y la misma fecha desde. Las huellas SHA-256 de los binarios instalados fueron `72ae604678fbf09243ea7e2330ae54c7408ff784918458843e46807e7b477cc9` para Activity y `7bccb5c72ca66fdf6a9cf058a852c0b5000be268a202d563711f743199a3cb58` para Telemetry.

| Medida | Desactivada | Activada |
| --- | ---: | ---: |
| Primer lote → corte común de órdenes y ejecuciones | 27 min 40,009 s | 27 min 39,961 s |
| Primer lote → heartbeat de puesta al día | 28 min 30,162 s | 28 min 20,051 s |
| Lotes de Activity / vacíos / paginados | 135 / 52 / 0 | 133 / 51 / 0 |
| CPU media de MT5, equivalente de un núcleo lógico | 28,66 % | 24,48 % |
| CPU p95 de intervalos de cinco segundos | 34,96 % | 32,46 % |
| Pico de memoria residente | 318,42 MiB | 290,54 MiB |
| Pico de memoria privada | 390,57 MiB | 364,28 MiB |

Ambas variantes tuvieron cobertura continua del corte de la referencia. Coincidieron las 8.021 órdenes, 71 ejecuciones y 35 posiciones reconstruidas, incluidas sus huellas. Todos los mensajes recibidos por el relay hasta cada heartbeat se confirmaron. Los heartbeats miden la puesta al día respecto a dos extremos distintos del historial, uno por corrida.

El muestreo externo de la variante desactivada se reanudó 238,7 s después del primer lote. Para comparar recursos se usaron 292 muestras por variante en el tramo común, aproximadamente entre el minuto 4 y el 28. Los valores describen todo MT5 y la carga de los operadores pudo variar. Esta pareja de corridas verifica el funcionamiento de la instrumentación y la reproducibilidad del tiempo hasta el mismo corte. La variación de CPU y memoria no permite estimar el costo propio de la instrumentación. Quedan por medir la latencia de los EAs y la distribución de tiempos bajo otras cargas y redes.

### Fases observadas con diagnóstico activado

Se agregaron cinco resúmenes por categoría de las sesiones confirmadas hasta el corte. Las fases están anidadas en el callback. Cada promedio usa sus propias observaciones y la última ventana parcial queda fuera.

| Collector y fase | Observaciones | Media | Máximo |
| --- | ---: | ---: | ---: |
| Activity profundo, ciclo | 102 | 17,03 ms | 37,17 ms |
| Activity profundo, envío al relay | 94 | 15,03 ms | 28,23 ms |
| Activity profundo, lectura y JSON de filas | 94 | 2,72 ms | 12,98 ms |
| Activity profundo, selección de historial | 102 | 0,122 ms | 0,215 ms |
| Activity profundo, persistencia de cursor | 94 | 0,094 ms | 0,181 ms |
| Activity profundo, codificación UTF-8 | 290 | 0,013 ms | 0,123 ms |
| Activity reciente, ciclo | 27 | 13,40 ms | 51,64 ms |
| Telemetry, ciclo | 303 | 10,44 ms | 55,30 ms |
| Telemetry, envío al relay | 303 | 10,18 ms | 21,67 ms |
| Telemetry, construcción de captura | 303 | 0,076 ms | 1,17 ms |

La espera HTTP explica alrededor del 81 % de la suma de tiempos de los ciclos profundos y el 98 % de los ciclos de Telemetry en esta muestra local. La lectura de filas y su JSON fue el costo local medido más alto en Activity profundo. El costo de codificar UTF-8 fue pequeño. Estos datos favorecen reducir consultas y envíos con ventanas adaptables. Esta carga tuvo cero páginas. El caso de falta de progreso por tamaño de mensaje requiere el escenario denso de UC2.

## Mediciones pendientes para las siguientes optimizaciones

### Control con el binario instrumentado

Usar los mismos dos EX5 en ambas variantes. Configurar `EnablePerformanceDiagnostics=false` en la primera y `true` en la segunda desde las propiedades de ambos EAs. Verificar el ajuste al volver a adjuntarlos. Registrar el SHA-256 de cada EX5 y la versión de MT5. Para cada descarga independiente, conservar el catálogo, la fecha desde y las condiciones de prueba y partir con almacenamiento y cursores de prueba limpios. Comparar al mismo corte de tiempo del bróker.

Buscar las entradas `TradingLab perf` en la pestaña **Expertos** de MT5 o en el archivo diario en `MQL5/Logs`. El collector emite un resumen por categoría de trabajo cada cinco minutos cuando hay muestras y descarga las mediciones restantes al cerrar o reiniciar la sesión de captura. Cada fase contiene cantidad de observaciones, fallos registrados, suma y máximo en microsegundos y ocho contadores de duración. Los límites superiores inclusivos son 100, 500, 1.000, 5.000, 25.000, 100.000 y 500.000 µs. El último contador reúne las duraciones mayores. Sumar los contadores antes de ubicar p50, p95 o p99 en un intervalo. La secuencia del resumen es la última asignada al emitirlo y permite relacionar la ventana de medición con la sesión en la base central. Los intentos HTTP de reenvío tienen su propia fase.

Los cronómetros miden tiempo transcurrido. El ciclo completo incluye las fases anidadas y el reporte se emite después de medirlo. La lectura de propiedades y la construcción del JSON de cada fila se miden juntas para evitar un cronómetro por fila. La captura de Telemetry incluye su lectura de historial cuando renueva la caché. Combinar estos tiempos con el muestreo externo del proceso MT5 y conservar la medición de la variante desactivada.

Para repetir UC1, usar una terminal demo y almacenamiento de prueba independiente con la misma fecha desde. Conservar la configuración de cursores de la instalación en uso. Si el extremo superior avanza con el reloj, recortar la comparación de filas y medir el instante en que ambas corridas alcanzan el mismo extremo. El heartbeat mide detección de puesta al día y depende de su propia cadencia.

| Escenario | Control | Candidata | Comparación |
| --- | --- | --- | --- |
| Historial de referencia | Valores anteriores y nuevas repeticiones pareadas | Pendiente | Cobertura, hashes, ciclos financieros, tiempo hasta el mismo extremo |
| Operación estable y ráfaga | Pendiente | Pendiente | CPU total/proceso, memoria máxima, duración de callback y frescura reciente p50/p95/p99, tamaño de muestra |
| Historial denso, ACK perdido y corte | Pendiente | Pendiente | Avance, reenvíos, duplicados, muestras descartadas y tiempo de recuperación |
| Relay remoto | Pendiente | Pendiente | RTT, tiempo hasta admisión central, profundidad y edad de cola |

La sonda existente `tests/manual/activity_load_probe.py` genera conciliaciones por posición del flujo anterior. Sirve para el transporte sintético que ejercita. La referencia de este documento proviene del flujo real posterior al PR #70.

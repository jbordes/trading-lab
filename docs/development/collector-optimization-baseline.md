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
with sqlite3.connect(db.as_uri()+"?mode=ro", uri=True) as conn:
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
        digest.update((json.dumps(json.loads(row), sort_keys=True, ensure_ascii=True,
                                  separators=(",", ":"))+"\n").encode("ascii"))
    print({k:(counts[k],v.hexdigest()) for k,v in digests.items()})
    print(conn.execute("""
      SELECT count(*), count(DISTINCT json_extract(payload_json,'$.payload.history')),
             sum(length(CAST(json_extract(payload_json,'$.payload.history') AS BLOB))),
             sum(length(CAST(payload_json AS BLOB)))
      FROM telemetry_messages WHERE collector_version='0.3.4'
        AND received_at_utc >= '2026-11-25T12:22:00'
        AND received_at_utc < '2026-11-25T12:52:24'
        AND json_type(payload_json,'$.payload.history')='object'
    """).fetchone())
```

## Mediciones pendientes para el antes y el después

Antes de optimizar, ejecutar UC1 con el control intacto y con la instrumentación sola. Usar una terminal demo aislada y almacenamiento de prueba independiente para repetir la descarga del mismo período. Conservar la configuración de cursores de la instalación en uso. Si el extremo superior avanza con el reloj, recortar la comparación de filas y medir el instante en que ambas corridas alcanzan el mismo extremo. El heartbeat mide detección de puesta al día y depende de su propia cadencia.

| Escenario | Control | Candidata | Comparación |
| --- | --- | --- | --- |
| Historial de referencia | Valores anteriores y nuevas repeticiones pareadas | Pendiente | Cobertura, hashes, ciclos financieros, tiempo hasta el mismo extremo |
| Operación estable y ráfaga | Pendiente | Pendiente | CPU total/proceso, memoria máxima, duración de callback y frescura reciente p50/p95/p99, tamaño de muestra |
| Historial denso, ACK perdido y corte | Pendiente | Pendiente | Avance, reenvíos, duplicados, muestras descartadas y tiempo de recuperación |
| Relay remoto | Pendiente | Pendiente | RTT, tiempo hasta admisión central, profundidad y edad de cola |

La sonda existente `tests/manual/activity_load_probe.py` genera conciliaciones por posición del flujo anterior. Sirve para el transporte sintético que ejercita. La referencia de este documento proviene del flujo real posterior al PR #70.

# Validación automática del piloto unificado en la VPS

Fecha: 2026-11-06. Código de referencia: `6c6f464`.
Alcance: terminal demo Juampi, collectors compilados el 2026-11-05, relay durable,
API central con esquema SQLite 7 y dashboard local. No certifica producción,
Mac/Linux, Tailscale ni cuentas reales.

El operador autorizó pruebas sin asistencia, incluidas interrupciones de los
servicios del piloto. No se reiniciaron MT5, collectors ni EAs de trading;
no se alteraron credenciales ni cursores durante estas pruebas. Las bases y la
API anteriores permanecieron fuera del ensayo. No se ejecutó `check.py full`.

## Resultado automatizado

| Comprobación | Resultado y límite |
| --- | --- |
| Tests Python dirigidos | 354 ejecutados: 353 pasan, 1 falla por preparación desactualizada del test; detalle debajo |
| Integridad SQLite | Esquema central 7, comprobaciones de integridad y relaciones válidas; outbox íntegra |
| Cobertura histórica | Deals y órdenes tienen cobertura continua del 01/10/2026 00:00 al 06/11/2026 00:00, reloj del broker; cero lotes incompletos en ese intervalo |
| API frente a SQLite | Coinciden tickets y campos de 72 deals y 6.384 órdenes en ese período cerrado; 1 y 64 páginas respectivamente, sin tickets repetidos entre páginas |
| Replay real | Reenvío de un mensaje persistido por contrato: HTTP 200 `duplicate`, una sola fila para fuente/sesión/secuencia |
| Permisos centrales | Lecturas sin autenticación o con credencial de otro permiso rechazadas; lecturas autorizadas correctas |
| Caída de API | Interrupción abrupta del proceso verificado: relay conservó 5 pendientes; al restaurar la API la cola quedó vacía y llegaron ACKs centrales |
| Caída de relay | Ambos listeners ausentes durante el corte; API siguió disponible; collectors retomaron sin intervención y la cola quedó vacía |
| HTTP 401 y 403 a los collectors | Cada rechazo se inyectó durante 75 segundos; ambos collectors fueron observados y retomaron con sus credenciales originales; logs muestran WARN y RESOLVED |
| Dashboard HTTP | Login, lectura de estado conectado, historial, ciclos, métricas, assets e iconos disponibles; sesión de prueba revocada sin cerrar sesiones humanas |
| Reporte MT5 archivado del 28/10 | Coinciden campos de sus 38 deals, 2.827 órdenes y 19 posiciones; las 18 posiciones adicionales son posteriores al último evento del reporte |

La cobertura verifica lo que el broker devolvió al collector, no la existencia
de actividad en todos los días ni una auditoría externa del histórico del broker.
El reporte archivado permite una comparación independiente parcial: no reemplaza
un reporte nuevo de MT5 hasta el cierre actual. Las observaciones repetidas de
los tickets comparados no presentan variantes contradictorias de `row_json`.

Los logs de Telemetry muestran descartes de snapshots durante los rechazos
prolongados, coherentes con su outbox volátil y su política de frescura. La
prueba no acredita conservación de cada muestra de balance/equity. Activity
conservó su recuperación; no debe confundirse un snapshot descartado con un
deal u orden perdido. No se cambió esa política durante el ensayo.

## Hallazgos pendientes, sin correcciones de producto en esta validación

### Test de error de almacenamiento desactualizado

`test_central_api.CentralApiTest.test_storage_failure_returns_no_ack_and_no_internal_details`
espera HTTP 503 y recibe HTTP 403 `source_not_allowed`. Tiene dos problemas:

- Envía el ejemplo documental `example-activity`, no registrado en su fixture.
- Inyecta el fallo en `accept`, pero la ruta actual llama a `_accept_validated`.

Con una prueba diagnóstica aislada, una fuente registrada y la inyección en el
punto realmente invocado, se obtuvo HTTP 503 `storage_unavailable` sin detalles
internos. Esto no vuelve verde al test original: hay que corregir su preparación
y verificar que siga cubriendo una falla real de persistencia sin debilitar la
autorización. No se modificó el test ni el código de producto para ocultar el fallo.

### Origen del login del dashboard

Un POST a `/login` con `Origin: https://invalid.example` y un token válido creó
una sesión. El servidor valida `Host`, pero la implementación inspeccionada no
valida `Origin` en el login. La comprobación de rechazo de origen ajeno falla.

No demuestra bypass de autenticación: requiere el token válido. Revisar el
modelo de amenazas, cookies y CSRF, y definir/reponer validación de origen para
las operaciones de sesión, con tests de login/logout y soporte explícito a
clientes no navegador según el contrato. No exponer el piloto a Internet como
consecuencia de esta prueba. No se modificaron reglas de origen ni cookies.

### Ajustes operativos ya detectados

- El default de Telemetry continúa en 8766; el piloto usa 8776. La instancia
  activa está corregida manualmente; falta corregir código, ejemplos y manual.
- El renombrado futuro de `juampi-demo-activity-v2` sigue pendiente y requiere
  coordinar identidades, outbox y cursores.
- Cambiar la fecha inicial no rebobina un cursor persistido. Evaluar una
  recuperación explícita y supervisada que no dependa de editar valores en F3.

## Evidencia local preservada

En `_storage/` del worktree `.tmp-fastapi-central-api`, fuera de Git:

- `fault-central-*.json`, `fault-relay-*.json`, `fault-401-*.json` y
  `fault-403-*.json`: estado antes/después, rechazos observados y PIDs del ensayo.
- `fault-*.stdout.log` y `fault-*.stderr.log`: arranques restaurados.
- `read-checks-*.json`: comparación API/base, cobertura y replay.
- `dashboard-http-*.json`: smoke HTTP; las ejecuciones exploratorias se conservan
  y la última distingue el hallazgo de origen de las lecturas correctas.
- `mt5-report-comparison-20261106.json`: salida original del comparador antiguo;
  devuelve 18 diferencias de presencia por posiciones posteriores al reporte.
- `mt5-report-classification-20261106.json`: clasificación contrastada con tiempos
  de evento; ninguna diferencia de campos en las entidades del reporte archivado.
- `unified-pilot-preparation.md`: preparación y recuperación supervisada anterior.

El archivo del reporte MT5 original y su comparador siguen en el `_storage/`
raíz del workspace, bajo `mt5-validation/2026-10-28/`. No se sobrescribieron.
No se guardaron valores de tokens en informes, argumentos o documentación.

## Pruebas que quedan para intervención humana

1. UI en escritorio/mobile: filtros, comparativa por EA, gráficos, detalles y
   coherencia visual. El smoke HTTP no evalúa renderizado ni usabilidad.
2. Retirar y volver a adjuntar collectors, comprobando continuidad tras reinicio
   sin editar cursores; reinicio completo de terminal solo con autorización aparte.
3. Exportar un reporte MT5 actualizado para comparar también la actividad nueva
   posterior al reporte del 28/10.

Desconexión del broker y carga nativa con historial denso permanecen diferidas
por decisión previa; no se ejecutaron. Las cuatro pruebas nativas ya habían
pasado con supervisión humana; las pruebas Python no las sustituyen.

Comprobación final: API `ready`, dashboard `connected`, outbox con cero activos,
sin errores ni rechazos. Se observó nuevamente captura fresca tras resolver los
rechazos. API, relay y dashboard quedaron funcionando. No se hace commit, push
ni PR como parte de esta ejecución de pruebas.

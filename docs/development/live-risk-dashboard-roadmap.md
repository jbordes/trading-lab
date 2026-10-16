# Roadmap — Dashboard local de riesgo

**Fecha:** 2026-10-14

**Estado:** incremento 0C en implementación

**Arquitectura:** [Dashboard local de riesgo](../architecture/live-risk-dashboard.md)

## Principios

- Solo lectura desde la credencial hasta la interfaz.
- Cuenta demo antes de conectar cuentas reales.
- Pocos segundos de demora; no prometer tiempo real estricto.
- Sin métricas cuya fórmula no haya aprobado el socio.
- Sin base ni modelo amplio antes de comprobar su necesidad.
- Historial, errores y frescura visibles; nunca ocultar datos obsoletos.

## Incremento 0B — Vista MT5 local

Alcance:

1. Adaptador mínimo para `account_info`, `positions_get` y `orders_get`.
2. Snapshot tipado con cuenta enmascarada y valores finitos.
3. Polling configurable, cinco segundos por defecto y mínimo de dos.
4. Historial acotado en memoria.
5. Servidor enlazado únicamente a `127.0.0.1`.
6. Pantalla responsive con estado, valores y curva balance/equity.
7. Modo demo determinista.
8. Tests de la fuente, degradación, historial y HTTP read-only.

Gate:

- validación completa del harness;
- vista demo comprobada en localhost;
- ejecución real habilitada con terminal y cuenta demo autorizados.

## Incremento 0C — Validación MT5 real

Implementado:

1. Captura conectada al terminal MT5 demo autorizado.
2. Posiciones abiertas y órdenes pendientes individuales, con filtro por Magic
   Number.
3. Ventana móvil de 24 horas de deals y órdenes históricas, con lectura
   incremental solapada, reconciliación completa periódica, deduplicación y
   límite en memoria.
4. Estado de captura con duración, intentos, éxitos, fallos y último éxito.

Pendiente para cerrar el incremento:

1. Comparar precios, volumen, SL/TP, resultado y timestamps con el terminal
   durante una sesión controlada.
2. Ejecutar una prueba prolongada y decidir con evidencia si conviene mantener la
   sesión IPC abierta.
3. Incorporar una instancia separada con contraseña de inversor antes de usar
   cuentas reales.
4. Evaluar agrupación por bot después de validar el muestreo operativo, sin
   reemplazar el detalle por operación.

## Spike complementario — Telemetría push MT5

Implementado en la rama del [spike](mt5-telemetry-collector-spike.md): guardas de
demo/loopback, cola acotada, validación estricta y recuperación de deals mediante
relectura de una ventana reciente. La reconciliación reemplaza la vista, conserva
Magic Number y costes y señala errores/truncamiento. No cambia la UI ni calcula
métricas; pruebas sintéticas y compilación no equivalen a validación en terminal.

El receptor incorpora límites de conexiones, plazo de red y contenido retenido,
con eliminación de índices de sesiones al desalojar sus mensajes. Los seis
puntos de revisión están implementados para el piloto; no implican cierre de
la comparación real ni autorización de despliegue o merge.

Pendiente: ejecutar las pruebas nativas en un terminal aislado y comparar contra
Python una apertura/cierre entre muestras, costes, reinicio y caída del receptor.
Medir latencia, ventana necesaria y saturación antes de agregar paginación o
persistencia. Validar la zona horaria del servidor; no asumir tiempos UTC.

## Incremento 1 — Contrato de control operativo

Guía para la conversación: [Métricas de riesgo para acordar con el socio](guia-metricas-para-el-socio.md).

Resolver con el socio:

1. definición exacta del método DDD/WSF;
2. timezone y comienzo del día;
3. referencia de balance/equity y tratamiento del flotante;
4. límites fijos o trailing;
5. depósitos, retiros y resets;
6. scope por cuenta, bot o portfolio.

Luego implementar DDD y Max DD como cálculos versionados con fixtures y casos límite.

## Incremento 2 — Persistencia mínima

Solo cuando el contrato de métricas históricas lo requiera:

1. definir frecuencia y retención necesarias;
2. evaluar SQLite append-only frente a segmentos inmutables en `_storage/`;
3. implementar idempotencia y recuperación tras reinicio;
4. conservar procedencia y payload crudo necesario;
5. agregar compactación o downsampling únicamente si el volumen medido lo exige.

## Incremento 3 — Riesgo histórico y visualizaciones

Las decisiones y ejemplos pendientes se recopilan en la
[guía de métricas](guia-metricas-para-el-socio.md).

1. Aprobar VaR, volatilidad, covarianza, riesgo de portfolio, MDD histórico y Sharpe.
2. Definir retornos, ventanas, pesos, horizonte, confianza y tasa de referencia.
3. Incorporar Apache ECharts como dependencia local fijada.
4. Agregar distribuciones, heatmap de covarianza y gráficos comparativos.
5. Validar resultados contra ejemplos suministrados por el socio.

## Incremento 4 — StocksTrader

1. Obtener token de una cuenta demo.
2. Confirmar permisos o scopes read-only con el proveedor.
3. Implementar cliente GET con hosts y rutas permitidos explícitamente.
4. Mapear el contrato mínimo sin forzar semántica MT5.
5. Resolver identidad de bot o estrategia en StocksTrader.
6. Comparar frescura y consistencia con su plataforma web.

## Fuera del piloto

- exposición pública o dentro de la LAN;
- ejecución o modificación de operaciones;
- PostgreSQL, TimescaleDB, colas o microservicios;
- autenticación multiusuario;
- fórmulas inferidas de ejemplos de Gemini;
- Excel como salida principal.

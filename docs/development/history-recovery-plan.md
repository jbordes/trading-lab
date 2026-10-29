# Recuperación histórica — primer paso

Fecha: 2026-10-25. Estado: backend, collector y consulta durable implementados;
recuperación reciente prioritaria preparada, piloto pendiente.

## Evidencia del piloto

La comparación local de los reportes MT5 con
`piloto-metrics-ui-test.sqlite3` encontró 26 deals en el reporte y 13 en la
base; los 13 coincidentes coinciden en los campos operativos comparados.
El reporte contiene 13 cierres con neto USD 59,43; la base contiene 7 de esos
cierres con neto USD -224,67. Los dos XLSX contienen los mismos miembros ZIP,
aunque sus hashes de archivo difieren. Se conservaron copias en
`_storage/mt5-validation/2026-10-25/`, fuera de Git.

Esto prueba cobertura incompleta en la base inspeccionada, no corrupción de
los registros coincidentes ni validación general de todas las fórmulas.
Hay interrupciones de recepción superiores a la ventana de una hora del
collector v1. Son compatibles con la falta de recuperación histórica; no
permiten atribuir individualmente cada ausencia sin contrastar ventanas en
tiempo del servidor. No interpretar `complete` de una ventana como historial
completo de la cuenta. Los costes de apertura requieren otro caso de prueba:
en estos reportes son cero.

## Paso 1 — Frontera entre estado vivo y actividad

Aplicar el [contrato v2](../architecture/telemetry-v2-contract.md) y la
[separación de collectors](../architecture/collector-responsibilities.md).
Reutilizar admisión y persistencia existentes; no crear otro protocolo histórico.

| Flujo | Información | Tratamiento al recuperar conexión |
| --- | --- | --- |
| Estado vivo | Cuenta, equity, balance, posiciones y órdenes pendientes actuales | Priorizar la captura reciente; no reconstruir equity pasada desde el saldo actual |
| Actividad | Deals y órdenes históricas, cualquiera sea su estado disponible en MT5 | Recuperar intervalos pendientes con confirmación durable, solapamiento y deduplicación |

Ambos flujos se asocian a una cuenta provisionada y mantienen fuente, rol,
secuencia, salud y credencial propios. El token humano del dashboard sigue
independiente. La separación no requiere otra terminal ni otro servidor.
La misma cuenta/rol tiene un productor primario explícito durante la transición.

Un lote de actividad nunca sustituye los valores actuales de cuenta ni actualiza
su frescura. Un fallo del historial no impide servir el último estado vivo
válido. El trabajo histórico debe tener límites de tamaño, tiempo y reintentos;
separar EAs no elimina la competencia por recursos de la terminal.

## Órdenes como evidencia de comportamiento

Conservar las órdenes históricas disponibles, incluidas canceladas, expiradas,
rechazadas y ejecutadas, aunque no generen deals. No todos los rechazos de una
solicitud necesariamente aparecen como órdenes históricas en MT5.
Identificar cada entidad por cuenta, tipo y ticket; conservar Magic Number,
relación orden/deal/posición, tiempos, estado y campos admitidos por el contrato.
Una orden cancelada sin ejecución no cuenta como trade ni como pérdida.

El estado final de una orden no equivale a un historial de modificaciones ni
explica siempre la decisión interna del EA. Los logs o una instrumentación
adicional se evaluarán después. Las pantallas y métricas de comportamiento
quedan fuera del primer corte; la captura debe preservar la evidencia disponible.

## Pasos siguientes y cierre verificable

1. **Este paso:** fijar responsabilidades, alcance de órdenes y criterios de
   integración. No implica que existan ya productores v2 operativos.
2. **Provisión implementada:** `provision_telemetry_v2_db.py` crea, solo con
   `--apply`, una base nueva y aislada con cuenta enmascarada y fuentes `live` y
   `activity` diferentes. La vista previa es el comportamiento predeterminado;
   no recibe tokens, no reemplaza archivos y verifica el registro antes de terminar.
   **Receptor implementado:** el servicio opt-in abre exclusivamente esa base,
   escucha en loopback y autentica `live` y `activity` con credenciales distintas
   mantenidas en memoria. Autoriza rol, fuente e identidad antes de validar el
   mensaje, confirma después del commit y diferencia aceptación, duplicado,
   secuencia antigua, conflicto y fallo de almacenamiento. La actividad ya se
   proyecta y consulta localmente con paginación, filtros y cobertura, sin exponer
   todavía una API para el dashboard. Resolver la continuidad del historial v1
   con una transición explícita; cualquier migración de datos existentes requiere
   aprobación antes de ejecutarla.
3. **Implementado en código:** collector de actividad con inicio histórico
   explícito, cursor durable local por fuente/identidad, confirmación después del
   commit, reenvío del mismo lote, solapamiento y subdivisión de rangos saturados.
   Conserva deals y órdenes finalizadas. Un rango mínimo saturado usa páginas
   compuestas y solo avanza después de confirmar su cadena durable. La versión
   anterior compiló sin errores; `activity-0.5.0` todavía requiere compilación e
   instalación manual en la terminal de prueba.
4. **Consulta durable implementada:** deals y órdenes se proyectan por separado en
   la misma transacción de ingesta. Se consultan por cuenta, período y Magic Number
   con cursor estable; la cobertura completa y los lotes incompletos se informan
   sin reconstruir la cuenta en memoria. La API loopback usa una credencial de
   lectura propia y el dashboard puede consumirla de forma opt-in para historial y
   métricas, sin exponerla al navegador. Falta integrar el collector de estado vivo
   v2 y representar visualmente la cobertura.
5. Validar reinicio, desorden, duplicados, error, truncamiento y caída prolongada.
   Probar que un lote antiguo no cambia balance/equity actuales y que una orden
   cancelada sin deal se conserva sin incrementar trades. Contrastar con MT5.

## Evolución 0.3: actividad reciente independiente del backfill

`TradingLabActivity` conserva un solo productor, una secuencia y como máximo un
lote sin confirmar, pero separa dos cursores durables. El carril reciente comienza
con una relectura acotada de la última hora y se atiende al iniciar, ante actividad
de trading o al vencer su cadencia. El carril profundo continúa desde
`HistoryStartServerTime` únicamente cuando el reciente está al día. Ambos conservan
solapamiento, confirmación posterior al commit y deduplicación del receptor.

Una ventana mínima saturada se pagina mediante una clave estable compuesta por
timestamp, tipo de entidad y ticket. El cursor principal del carril no avanza
hasta confirmar la cadena completa; una página parcial no declara cobertura. Si
el conjunto histórico cambia durante el proceso, se reinicia la ventana y las
observaciones repetidas se resuelven de forma idempotente. Los parámetros nuevos son
`RecentLookbackSeconds` y `RecentCadenceSeconds`; sus valores iniciales son una hora
y un minuto. El cursor histórico anterior se reutiliza y el cursor reciente nuevo
se inicializa sin borrar variables globales.

El callback `OnTradeTransaction` conserva además hasta 128 avisos mínimos en una
cola circular preasignada. Solo copia tipo, tickets, posición, símbolo y reloj
monotónico de recepción; no consulta historia ni realiza red, archivos o SQLite.
El timer drena esos avisos para priorizar la relectura reciente. Si la cola se
completa, incrementa un contador de descartes y la recuperación autoritativa por
historial continúa siendo la protección contra huecos. Los avisos aceleran y
diagnostican; no se convierten en una segunda fuente de verdad.

La versión `activity-0.5.0` emite además un heartbeat operativo cada minuto. El
mensaje informa por separado los cursores reciente y profundo, atraso pendiente,
bloqueos, avisos en cola o descartados y los últimos tickets observados. Un heartbeat
confirmado no mueve cursores, no confirma cobertura y no desencadena reconciliación
de posiciones. Su esquema es opcional dentro del contrato de heartbeat para que
los productores existentes sigan siendo compatibles. Un bloqueo o un descarte
de avisos degrada explícitamente su estado.

El progreso se consulta mediante `GET /v2/activity-progress`, leyendo el último
heartbeat durable sin crear una proyección creciente en memoria. Continúan pendientes
dentro del punto 3: pausa operativa, prueba reproducible con más de 12 meses y
compilación/validación manual de `activity-0.5.0` en la terminal de prueba.

La instalación en Juampi se realiza después de validar código y con intervención
humana. No modificar la terminal del socio. La captura sigue siendo solo lectura
de MT5. No importar el Excel como si fuera telemetría nativa ni rellenar huecos
con valores inventados. La recuperación depende del historial que entregue MT5.

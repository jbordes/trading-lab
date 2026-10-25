# Recuperación histórica — primer paso

Fecha: 2026-10-25. Estado: backend, collector y consulta durable implementados; piloto pendiente.

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
   Conserva deals y órdenes finalizadas. Un rango mínimo saturado queda
   `truncated`, persiste un bloqueo y no entra en un ciclo de reenvíos. Compila
   con 0 errores y 0 warnings; falta instalarlo y validarlo contra MT5 real.
4. **Consulta durable implementada:** deals y órdenes se proyectan por separado en
   la misma transacción de ingesta. Se consultan por cuenta, período y Magic Number
   con cursor estable; la cobertura completa y los lotes incompletos se informan
   sin reconstruir la cuenta en memoria. Falta integrar el collector de estado vivo
   y adaptar la API autenticada del dashboard.
5. Validar reinicio, desorden, duplicados, error, truncamiento y caída prolongada.
   Probar que un lote antiguo no cambia balance/equity actuales y que una orden
   cancelada sin deal se conserva sin incrementar trades. Contrastar con MT5.

La instalación en Juampi se realiza después de validar código y con intervención
humana. No modificar la terminal del socio. La captura sigue siendo solo lectura
de MT5. No importar el Excel como si fuera telemetría nativa ni rellenar huecos
con valores inventados. La recuperación depende del historial que entregue MT5.

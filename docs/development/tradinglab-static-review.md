# Revisión estática de TradingLab multicuenta

Base revisada: `feature/collector-optimization` en `8e2ea6c8e11c65d1aed4af936a28daba3b1c58f3`.

La revisión abarca la captura en MT5, el relay, la API, SQLite, el dashboard, el SetUp, el empaquetado y las verificaciones existentes. Los hallazgos se obtuvieron por lectura del código. El impacto operativo y los tiempos de ejecución quedan pendientes de medición. Las referencias de línea corresponden al commit revisado.

La revisión identifica cuatro áreas de trabajo para ramas separadas. La primera reúne los hallazgos de prioridad alta. La optimización de collectors sigue en pausa. El roadmap y los casos de uso con pseudocódigo quedan pendientes de confirmación.

## Hallazgos de prioridad alta

### 1. Criterios distintos de cobertura del historial

La proyección de posiciones une los intervalos completos. El informe de cobertura elige primero una observación por instante de captura y sesión, y después resuelve discrepancias entre sesiones. Esa agrupación no incluye la ventana histórica, así que puede descartar una de dos ventanas legítimas capturadas en el mismo instante. Performance financiera consulta la cobertura de deals, aunque la proyección de una posición también puede depender de órdenes. La pantalla y la proyección pueden informar estados distintos para un mismo período. La causa de avisos de «datos parciales» observados en una instalación concreta requeriría evidencia de esa instalación.

Conviene definir el significado de «completo» para deals, órdenes y métricas financieras y compartir la resolución de evidencia. Deben contemplarse ventanas distintas con la misma marca temporal, dos terminales sobre una cuenta y correcciones del broker. [informe de cobertura, línea 714](../../src/tradinglab/telemetry/sqlite_store_v2.py), [proyección de posiciones, línea 42](../../src/tradinglab/telemetry/remote_positions.py), [métricas financieras, línea 1188](../../src/tradinglab/dashboard/telemetry_v2.py).

### 2. El heartbeat de Activity puede impedir el envío de datos

La configuración acepta `HeartbeatSeconds == IntervalSeconds`. Activity atiende primero un heartbeat vencido y sale del ciclo al enviarlo. Si el temporizador se ejecuta al intervalo configurado o más tarde, esto puede repetirse indefinidamente incluso con confirmaciones correctas. El collector sigue emitiendo señales de vida mientras el cursor se queda quieto.

El criterio de aceptación es que ambas tareas progresen cuando coinciden, manteniendo el temporizador actual y un único lote pendiente. [Activity, líneas 177, 241 y 469](../../apps/mt5-telemetry-collector/TradingLabActivity.mq5).

### 3. El backup operativo rechaza la base multicuenta actual

El SetUp crea una base de esquema 10. El plan usado por los comandos de backup y mantenimiento admite por defecto únicamente el esquema 8. La ruta puede pasar la preparación y la copia fallar al validar la versión.

La compatibilidad debe comprobarse también al restaurar una copia y abrirla conservando cuentas, cobertura y posiciones. Las operaciones de mantenimiento que modifican datos requieren una evaluación propia. [creación de la base, línea 74](../../src/tradinglab/multi_host.py), [versión por defecto, línea 24](../../src/tradinglab/telemetry/central_schema.py), [validación del backup, línea 83](../../src/tradinglab/telemetry/backup.py), [entrada de mantenimiento, línea 40](../../scripts/run_telemetry_maintenance.py).

### 4. Compilación y empaquetado reproducible del SetUp

La compilación deposita los binarios en `_storage/multicuenta/compiled` y el empaquetador los busca en `_storage/setup/compiled`. Al compilar un solo EA se copian todas las cabeceras compartidas. El empaquetador comprueba que el texto de las cabeceras coincide y que los binarios existen, sin demostrar qué cabeceras se usaron para producir cada binario. Un ZIP íntegro puede contener un EX5 anterior. Además, el paquete incluye todos los Python presentes bajo `src/tradinglab`, incluso archivos locales ajenos a Git.

Conviene unificar la salida y asociar cada EX5 a sus fuentes y cabeceras. El caso que debe detectarse es un cambio de cabecera seguido de una compilación parcial. Para Python conviene seleccionar los archivos distribuibles de forma explícita. [compilación, línea 4](../../scripts/build_mt5_multi.ps1), [empaquetado, línea 32](../../scripts/package_tradinglab_setup.py).

## Rendimiento de extremo a extremo

- **Ingestión y proyección.** Un lote identifica posiciones afectadas y reconstruye su proyección dentro de la transacción central. Se eliminan resultados previos, se vuelven a ordenar observaciones y se interpreta JSON. Con ventanas solapadas pueden repetirse reconstrucciones aunque los tickets observados conserven su contenido. La comparación futura debe registrar posiciones reconstruidas, posiciones que cambiaron y duración de la transacción. Una reasignación de ticket debe recomputar las posiciones anterior y nueva. Una ventana vacía puede aportar la cobertura faltante. [Selección y reconstrucción, líneas 13 y 61](../../src/tradinglab/telemetry/remote_positions.py).
- **Performance financiera.** El dashboard pide cobertura y recorre ciclos en páginas HTTP de 100. Cada página vuelve a combinar y ordenar evidencia en SQLite. El trabajo puede crecer con el historial total aunque se consulte una ventana corta. Entre páginas también pueden entrar correcciones. La comparación debe abarcar una página inicial y sucesivas en una cuenta grande. La selección de la versión vigente debe preceder a los filtros por fecha o magic cuando dichos campos puedan cambiar. [Paginación, línea 1172](../../src/tradinglab/dashboard/telemetry_v2.py), [consulta, línea 888](../../src/tradinglab/telemetry/sqlite_store_v2.py).
- **Cola durable del relay.** La última secuencia se busca con `ORDER BY length(sequence), sequence` dentro de la admisión y el índice actual no cubre todo ese orden. Consultar estado agrega filas de una tabla que conserva metadatos confirmados. Conviene comparar los planes con muchas filas confirmadas y pocas pendientes. Un índice o una última secuencia persistida deben preservar el reconocimiento de reenvíos antiguos tras reiniciar. [Admisión y estado, líneas 171 y 279](../../src/tradinglab/telemetry/relay_queue.py).
- **Transporte del relay.** Los flujos se atienden secuencialmente y cada envío abre una conexión y configura un vencimiento. Una API lenta puede retrasar el turno de otras cuentas. Al recibir se lee el JSON para resolver `source_id` y se interpreta otra vez para validarlo. Medir espera, conexión y confirmación por separado. La reutilización de trabajo tiene prioridad sobre introducir concurrencia, que tendría que conservar el orden por flujo y los límites de tiempo. [Relay, línea 99](../../src/tradinglab/multi_relay.py), [transporte HTTP, línea 60](../../src/tradinglab/telemetry/relay_delivery.py).
- **Dashboard multicuenta.** El primer acceso arranca un servicio bajo un bloqueo compartido. El arranque hace una consulta síncrona y puede retrasar el primer acceso a otra cuenta. Las instancias abiertas siguen consultando hasta cerrar el proceso. Con el volumen previsto conviene eliminar primero la espera cruzada, preservando una instancia por cuenta incluso con dos aperturas simultáneas. [Gestión de cuentas, línea 30](../../src/tradinglab/multi_dashboard.py), [arranque, línea 188](../../src/tradinglab/dashboard/service.py).
- **Paginación densa en MT5.** Cada continuación llama a `HistorySelect` y al avanzar de página se recorre nuevamente la ventana. `CycleBudgetMs` acota el escaneo y deja fuera la selección y la serialización final. Antes de retomar la optimización conviene medir esas etapas y el ciclo completo, con filas examinadas por fila enviada, manteniendo el temporizador y un único envío pendiente. [Paginación, líneas 709, 762 y 813](../../apps/mt5-telemetry-collector/TradingLabActivity.mq5).
- **Recuperación de Activity.** Tras una desconexión larga, el cursor reciente restaurado puede quedar lejos del presente y demorar la aparición de operaciones nuevas. Una página válida por cantidad de filas también puede exceder el límite de bytes. La rama descarta el cuerpo sin reducir la página ni avanzar, con lo cual puede repetir el trabajo. Ambos casos requieren preservar el rango pendiente hasta confirmación. [Cursor y control de tamaño, líneas 1168 y 301](../../apps/mt5-telemetry-collector/TradingLabActivity.mq5).

## Seguridad y operación

- **Instalación de uv.** Si falta uv, el SetUp descarga por HTTPS un script sin versión fijada ni verificación de huella y lo ejecuta. `uv sync --locked` protege una etapa posterior. Fijar y verificar el artefacto de arranque mejora la reproducibilidad. [Bootstrap, línea 19](../../scripts/tradinglab_setup_windows.ps1).
- **Permisos de una instalación reutilizada.** Al crear la carpeta se aplica protección. Una carpeta restaurada o copiada puede superar la comprobación del marcador y tener permisos más amplios. Se deben verificar los permisos efectivos antes de reutilizar archivos privados. [Preparación, línea 45](../../src/tradinglab/multi_host.py).
- **Límites de entrada de la API.** Las rutas `POST /catalog` y `POST /resolve` interpretan el cuerpo antes de autenticar dentro del manejador. El servicio exterior no aplica un límite equivalente al interno. La protección en un despliegue remoto puede depender del proxy. Conviene limitar el cuerpo antes de interpretarlo y conservar la validación de campos. [API, línea 149](../../src/tradinglab/multi_catalog.py).
- **Estado y diagnóstico de servicios.** SetUp consulta el puerto de Telemetry para el relay y Activity escucha en otro puerto. El estado de la API responde `ready` de forma constante. Reutilizar el relay con la misma URL puede omitir la comprobación de existencia de su cola. Conviene detectar y explicar qué componente está afectado, preservando la cola existente. [Estado, línea 83](../../src/tradinglab/multi_operations.py), [health, línea 177](../../src/tradinglab/multi_catalog.py), [reutilización, línea 90](../../src/tradinglab/multi_host.py).

## Acoplamiento, duplicación y verificaciones

- **Esquema y proyecciones.** Las variantes de esquema se construyen con reemplazos de texto y varias operaciones dependen del orden de columnas. Nombrar las columnas en operaciones críticas reduce el riesgo al evolucionar las tablas. La misma evidencia debe producir el mismo ciclo financiero. [Esquema](../../src/tradinglab/telemetry/central_schema.py), [persistencia de ciclos, línea 159](../../src/tradinglab/telemetry/remote_positions.py).
- **Validación de esquema.** Se ejecuta DDL en una base transitoria para construir los objetos de referencia. Se puede reutilizar esa referencia por versión y seguir comparando los objetos efectivos de cada base. [Construcción de referencia, línea 95](../../src/tradinglab/telemetry/central_schema.py).
- **Alta y montaje de cuentas.** El manejador asíncrono ejecuta escritura SQLite síncrona. Una espera por el bloqueo puede ocupar el hilo que atiende otras peticiones. Además, para montar una cuenta se relee el catálogo completo. Priorizar la espera compartida con el volumen previsto. [Registro, montaje y manejador, líneas 49, 125 y 191](../../src/tradinglab/multi_catalog.py).
- **Verificaciones del collector.** Algunas pruebas buscan fragmentos en el fuente. Pueden confirmar la presencia de una guarda aunque el flujo de ejecución impida alcanzarla. Las futuras comprobaciones de comportamiento deben enfocarse en el avance de cursor, la conservación del lote, la cobertura reportada y el contenido del paquete. [Pruebas de Activity, línea 20](../../tests/unit/test_mt5_activity_collector.py), [flujo de calidad](../../.github/workflows/quality.yml).

### Precisión sobre los totales de Telemetry

El snapshot ya incluye los totales de posiciones y órdenes. El dashboard compara ambos totales con el detalle para marcarlo parcial, por lo que esos campos cubren el aviso de truncamiento por cantidad. Si la composición cambia durante la lectura y el total se mantiene, la comparación no certifica una captura de un solo instante. [Captura, línea 332](../../apps/mt5-telemetry-collector/TradingLabTelemetry.mq5), [detección de detalle parcial, línea 755](../../src/tradinglab/dashboard/telemetry.py).

## Orden propuesto

Primero, confiabilidad del dato y capacidad de recuperación con los cuatro hallazgos de prioridad alta. Después, diagnóstico y seguridad del SetUp. Para el rendimiento, medir primero la proyección central, las consultas financieras y el relay. La consulta financiera y la materialización de ciclos son los primeros candidatos para observar el coste de filtrar los últimos siete días sin trasladar trabajo a MT5.

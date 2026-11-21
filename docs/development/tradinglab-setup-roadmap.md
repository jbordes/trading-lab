# TradingLab SetUp y captura multicuenta

Propuesta de trabajo al 20 de noviembre de 2026. La referencia técnica es la rama de instalación remota en `bc27ae3`. La instalación estable de Windows sirve como referencia de experiencia de usuario. Los binarios de producción serán los collectors del contrato remoto. La compatibilidad con collectors estables y el despliegue automatizado entre servidores quedan fuera del alcance actual.

## Estado de la implementación multicuenta

La rama `feature/tradinglab-setup-multicuenta` parte de `bc27ae3`. La referencia de experiencia del instalador estable es `a86cf1f`. La entrada de Windows es `TradingLab SetUp.cmd`. La [guía de operación y aceptación](tradinglab-setup-multicuenta.md) describe la preparación en un equipo y la disposición con API central detrás de un proxy HTTPS.

Se compilaron Activity, Telemetry y el asistente de gráficos con MetaEditor de Roboforex. En la revisión manual local se creó una base nueva, se dieron de alta dos cuentas de muestra con el mismo login en servidores distintos y se consultó la salud de API, relay y dashboard. Al detener la API, el relay y el dashboard siguieron respondiendo. Los tres servicios de esa revisión se detuvieron al terminar.

En Windows se preparó la terminal demo con SetUp. Tras corregir el alta de la cuenta, Activity y Telemetry enviaron datos al relay. Activity 0.8.4 retomó el historial pendiente tras recargarse con el reloj del bróker detenido. En dos lecturas consecutivas los cierres conciliados pasaron de 8 a 11. En la segunda lectura las 11 posiciones con salida tenían un cierre apto para las métricas y el relay había confirmado todos los envíos. El historial completo seguía en recuperación. Durante la interrupción anterior del relay, Telemetry informó descartes de muestras de estado al llenarse su cola local.

Quedan por verificar en la demo la cobertura final desde la fecha configurada, el recorrido entre dos cuentas registradas y una desconocida, la entrega de un lote de A después de rotar a B y el cambio de cuenta en el dashboard con datos de ambas. La aceptación en equipos separados requiere disponer de esos equipos y del acceso HTTPS previsto.

## Punto de partida

- El piloto estable registra una instalación demo con recepción de estado y actividad. El 4014 observado al instalar motivó revisar los orígenes WebRequest autorizados y mostrar las direcciones efectivas al terminar. La causa en esa instalación quedó pendiente de verificación.
- La rama remota incluye relay con cola durable, API, SQLite central, dashboard y diagnóstico de collectors. Su instalador aprovisiona una cuenta y puede construir el recorrido completo en un equipo. La presencia del código y las pruebas de componentes no acreditan el nuevo recorrido multicuenta.
- La [guarda actual](../../apps/mt5-telemetry-collector/TradingLabAccountGuard.mqh) compara conexión, login, servidor y modo. El [aprovisionamiento](../../src/tradinglab/installation_backend.py) conecta fuentes específicas a los procesos. El [modelo central](central-sqlite.md) vincula cada fuente a una cuenta y un rol. El [ADR existente](../adr/0024-dual-installation-account-guard.md) documenta la decisión anterior. Si cambia su política, registrar un ADR posterior.

## Decisiones del producto

1. Un SetUp permite preparar componentes en el equipo actual, registrar terminales y cuentas, e iniciar uno o varios servicios. Cada proceso tiene consola y ciclo de vida propios. La API abre SQLite central y el relay abre su cola SQLite. El estado de proceso y la disponibilidad de sus dependencias se muestran por separado.
2. Una instalación central sirve a todas las cuentas. Un relay por equipo de captura puede atender varias terminales. Los collectors se preparan una vez por terminal. Cualquier terminal preparada puede reportar una cuenta dada de alta. La API atribuye cada lote a la cuenta observada durante la captura.
3. Tras iniciar sesión con contraseña, el dashboard ofrece un desplegable con las cuentas dadas de alta, incluidas las que están sin conexión. Cambiar la selección conserva la sesión. Estado, actividad, historial, métricas y fecha de última observación corresponden a la cuenta seleccionada. El selector del dashboard es independiente del login de MT5.
4. Un único formulario muestra URLs completas, editables y con valores iniciales. La selección de componentes determina qué arranca en este equipo. Los destinos determinan dónde se conectan sus clientes. El usuario puede editar esquema, host, puerto y ruta dentro de las combinaciones soportadas.

| Campo propuesto en el JSON | Valor inicial propuesto | Uso |
| --- | --- | --- |
| `dashboard_url` | `http://127.0.0.1:8775/dashboard` | Acceso del operador |
| `api_base_url` | `http://127.0.0.1:8782` | Origen para relay y cliente del dashboard. Ejemplo remoto: `https://api.tradinglab.com` |
| `snapshot_ingest_url` | `http://127.0.0.1:8776/account-state` | Collector Telemetry al relay local |
| `activity_ingest_url` | `http://127.0.0.1:8777/trading-events` | Collector Activity al relay local |

HTTP local funciona con los collectors actuales. El relay admite HTTPS hacia la API. Validar el esquema según el servicio, la ruta del contrato y las colisiones de escucha en cada equipo. Mostrar los dos orígenes exactos para WebRequest en MT5. Una URL pública puede terminar TLS en un proxy con un puerto de escucha interno distinto. Conservar ese ajuste local cuando proceda, sin pedir al usuario que duplique host y puerto en la configuración ordinaria.

## Alta manual e identidad observada

El collector obtiene servidor, login y modo directamente de la sesión MT5. Comprueba la identidad antes y después de leer cada lote. Si falta el servidor o el login, o si cambia la cuenta durante la lectura, descarta esa lectura, conserva el cursor y reintenta cuando MT5 entregue una identidad válida. Al completar una lectura válida, guarda juntos los datos y su identidad de cuenta. El relay conserva esa identidad durante todos los reintentos. Cursores y deduplicación quedan vinculados a la cuenta.

El operador usa TradingLab SetUp → Cuentas → Agregar cuenta. SetUp solicita el alta a la API central, que guarda el registro en la tabla `accounts` de `central.sqlite3`, en el directorio privado del equipo que aloja la API. El registro contiene el alias y permite resolver de forma única la pareja (servidor MT5, login completo) a un `account_id` estable. El modo se coteja como atributo. El esquema actual contempla un login enmascarado. El hito 4 debe definir cómo guardar y comparar la pareja exacta en la base nueva y asegurar su unicidad. Las altas repetidas deben ser idempotentes. El desplegable consulta este catálogo. El alta de una cuenta no modifica presets, tokens de captura ni binarios de los collectors.

Al conectar o cambiar de sesión, el collector consulta mediante el relay si la identidad está registrada. La API autentica el origen de captura y resuelve la identidad contra el catálogo. También valida la atribución al ingresar los lotes. Para una cuenta desconocida, el relay comunica ese resultado al collector, que emite un WARN por episodio y suspende la telemetría hasta un alta manual o cambio de cuenta. Revalidar con espera permite reconocer un alta sin recargar el EA. Si la API está inaccesible, el resultado es indeterminado: se reintenta, sin clasificar la cuenta como desconocida. La entrega de lotes ya admitidos por el relay conserva la identidad de origen.

REAL y DEMO describen el modo reportado por el servidor MT5. Ambos permiten observación de solo lectura. La etapa comercial de fondeo (evaluación o fondeada) es independiente del modo técnico.

## Hitos y criterios de salida

| Hito pendiente | Entrega | Verificación |
| --- | --- | --- |
| 1. Fijar referencia | Identificar el ZIP estable probado y sus funciones, recoger los cambios de instalación terminados y preparar rama de integración sobre el runtime remoto | Inventario contrastado: asistente, abrir/guardar JSON, continuar, presets, fecha del broker, selección de carpeta MT5, adjuntar collectors y paquete verificable |
| 2. Configuración | JSON versionado de instalación con componentes locales, URLs, terminales y referencias a credenciales privadas. El catálogo de altas pertenece a la API. Reemplazar los campos de puertos que duplican URLs | Abrir, editar, guardar y volver a abrir conserva los valores. Para importar un JSON de puertos anterior, mostrar conversión y confirmar antes de guardar. Continuar conserva identidades y datos existentes |
| 3. Ejecución independiente | Iniciar, detener y consultar servicios individualmente o en grupo desde SetUp | Cerrar SetUp deja los procesos activos. Detener el dashboard permite seguir capturando. Detener la API acumula envíos y reiniciarla vacía la cola sin duplicados |
| 4. Registro y captura | Alta central manual, identidad leída de MT5 y autenticación del productor por terminal y rol | Registrar A y B con los mismos collectors y presets. Rotar A → desconocida → B con A pendiente de entrega. Verificar WARN en el collector, ausencia de datos de la desconocida y reanudación en B. Volver a A y comprobar su cursor. Probar logins iguales de servidores distintos y API desconectada |
| 5. Dashboard y paquete | Selector de cuenta, estado de frescura, ZIP Windows con collectors remotos, hashes, configuración y arranque | Instalar desde el ZIP en un solo servidor. Verificar una cuenta por vista, persistencia tras reinicio y recepción de ambos collectors. Registrar tiempos de consultas comparables antes de atribuir mejoras de rendimiento |
| 6. Equipos separados | Validar los mismos componentes con URLs remotas cuando haya servidores disponibles | Probar DNS, TLS, autorización, desconexión y recuperación extremo a extremo. El despliegue remoto automatizado corresponde a una fase posterior |

## Reemplazo de la instalación estable

La versión multicuenta comienza con una base nueva, sin migración de los datos de prueba. Sustituirá a la estable cuando se valide el piloto. El operador podrá elegir la fecha desde la cual Activity debe leer el historial disponible en el broker para cada cuenta. Los saldos y valores de equity observados periódicamente por Telemetry comienzan con la captura nueva. Esta decisión no requiere borrar la instalación anterior.

## Contrato técnico por concretar en el hito 4

- Al preparar MT5, SetUp asigna una identidad persistente a la instalación. La propuesta es emitir credenciales por terminal y rol (Telemetry o Activity), conservar sus referencias al volver a ejecutar SetUp y mantener los secretos fuera del JSON exportable. El diseño debe especificar cómo autentica el relay al collector y cómo transmite ese origen a la API usando su propia conexión autenticada.
- Dar de alta la cuenta por servidor y login. La credencial autentica el origen del envío. Probar que dos terminales preparadas pueden enviar la misma operación de una cuenta registrada y que el historial la muestra una sola vez. Simular también una identidad incompleta y un cambio de cuenta durante la lectura y comprobar que el cursor sigue en la última lectura confirmada.
- En cada lote, fijar la identidad observada al capturarlo. Definir los campos de la cola y de la petición a la API, la clave de deduplicación y cuándo avanzar el cursor. El relay confirma la recepción después de guardar el lote de forma durable. La API confirma su procesamiento después de persistirlo o reconocer una repetición ya procesada.
- Aplicar «fecha desde» al historial de cada cuenta y mantener su cursor independiente. Verificar la recuperación del historial disponible tras alternar cuentas y la ausencia de puntos de equity inventados durante la desconexión.

Actualizar los hitos con evidencia al completarlos. La validación en equipos físicamente separados corresponde al hito 6.

El [roadmap de captura ligera y reconstrucción central](remote-activity-roadmap.md) continúa la implementación multicuenta con un relay remoto opcional.

# TradingLab SetUp multicuenta para Windows

Extraiga el ZIP completo en una carpeta local y abra **TradingLab SetUp.cmd**. El iniciador prepara Python 3.14 y las dependencias de `uv.lock` mediante uv. La primera preparación de un equipo necesita acceso a esas descargas.

## Equipo único

1. En **Equipo** seleccione API, relay y dashboard. Elija una carpeta privada nueva y conserve las entradas del relay `http://127.0.0.1:8776/account-state` y `http://127.0.0.1:8777/trading-events` si esos puertos están disponibles. El relay envía ambos flujos a la API central configurada en **API URL** (por defecto `http://127.0.0.1:8782`). La API guarda las cuentas e historial en `central.sqlite3`. El relay guarda los envíos pendientes en `relay.sqlite3`.
2. Pulse **Preparar equipo**. La primera instalación genera automáticamente la clave de administración de la API y, si deja su campo vacío, la contraseña del dashboard. Para iniciar sesión consulte el campo `password` de `dashboard.private.json` en la carpeta privada del dashboard. Al volver a preparar el equipo se conservan las credenciales existentes. Para continuar otro día, use **Abrir JSON** y elija el `setup.json` de esa carpeta. **Guardar JSON** exporta un perfil de componentes, rutas y URLs. Las credenciales quedan en la carpeta privada del equipo.
3. En **Servicios** seleccione uno o varios y pulse **Iniciar selección**. Cada servicio abre una consola independiente. **Consultar estado** permite ver si responden el proceso local y la API configurada. Puede cerrar el SetUp. Para detener servicios use **Detener selección** o Ctrl+C en la consola correspondiente.
4. En **Cuentas** dé de alta cada cuenta con alias, login completo, servidor exacto, divisa, modo que reporta MT5, fecha desde y offset del broker en minutos. La fecha se expresa como `YYYY.MM.DD HH:MM:SS` en el reloj del broker. Repetir un alta idéntica conserva el registro. Una discrepancia con un registro existente genera un error.
5. En MT5 use **Archivo → Abrir carpeta de datos**. En la pestaña **Terminal MT5** seleccione esa carpeta y pulse **Preparar collectors**. Se instalan los tres EX5 del paquete. Si el destino ya contiene otros binarios con los mismos nombres, SetUp informa el conflicto antes de reemplazarlos.
6. En MT5 autorice los dos orígenes de WebRequest que indica SetUp. Actualice el Navegador y ejecute **Scripts → TradingLab → TradingLabAttachCollectors** en un gráfico. El script abre gráficos para Activity y Telemetry. Repita la preparación una vez por terminal.
7. Abra el dashboard, inicie sesión y seleccione una cuenta. Cada pestaña del navegador recuerda su selección y permite cambiarla dentro de la sesión. Tras dar de alta más cuentas, recargue la página para actualizar la lista.

## Rotación e historial

Los collectors leen el servidor, el login y el modo de la sesión MT5. Consultan el catálogo por medio del relay y vinculan la fuente devuelta a los lotes capturados para esa cuenta. Ante una cuenta desconocida registran una advertencia y vuelven a consultar. Un fallo de red se informa por separado. Activity conserva su avance por cuenta en las variables globales de esa terminal. El historial recupera operaciones disponibles desde la fecha configurada. Las observaciones de equity comienzan con la captura.

## Aviso al reconocer una cuenta

En el log del collector, `source_id` identifica la terminal configurada. Al recibir un rechazo del catálogo, Telemetry 0.3.3 y Activity 0.8.2 registran el servidor observado, el login enmascarado, el modo MT5 y el estado HTTP. Con la API y el relay del mismo paquete, el detalle distingue un catálogo vacío, una pareja servidor/login sin alta y una pareja registrada con otro modo. Una ruta de resolución inexistente genera `account_lookup_failed`. Al corregir el alta o la conexión, el collector vuelve a consultar cada diez segundos mientras espera.

Para actualizar una instalación, extraiga el ZIP en una carpeta de código nueva, detenga los servicios de TradingLab y abra el SetUp nuevo con el `setup.json` privado existente. Retire Activity y Telemetry de sus gráficos dedicados, prepare los collectors e inicie los servicios. Ejecute el asistente de gráficos para cargar los binarios nuevos. Las cuentas y su historial siguen en la carpeta privada original.

## Componentes en otros equipos

Ejecute el mismo SetUp en cada equipo y seleccione los componentes locales. Prepare primero la API y el acceso HTTPS al equipo central. Los procesos escuchan en loopback. Un proxy TLS gestionado por el operador puede publicar la API y el dashboard. Configure la URL pública completa en **Equipo**. Con HTTPS, la API escucha por defecto en el puerto local 8782 y el dashboard en el 8775. Puede ajustar el puerto local para el proxy si hace falta. Si usa un prefijo en la URL de la API, el proxy debe retirarlo antes de reenviar al proceso local. Para el dashboard publique el origen con la ruta `/dashboard` y reenvíe las rutas de sesión, datos y recursos del mismo origen.

El relay corre en el equipo de MT5 y puede atender varias terminales. Los collectors usan HTTP en loopback. Al preparar un relay o un dashboard en otro equipo, ingrese la URL de la API y su clave de administración (campo `admin` de `api.private.json` en la carpeta privada de la API) para autorizar la vinculación. También se usa al dar de alta una cuenta desde otro equipo. Después, cada servicio utiliza sus propias credenciales para las operaciones habituales. Las URLs y carpetas pueden diferir por host. El traslado de datos de una instalación estable y el despliegue automático de proxies quedan fuera de este paquete.

## Comprobación manual de aceptación

- En un directorio nuevo, prepare los tres servicios, abra y guarde un perfil y reabra SetUp. Compruebe que la API y el relay continúan cuando cierra la consola del dashboard.
- Registre A y B. Compruebe ambos collectors en A, luego abra una cuenta desconocida y revise el aviso en el log del collector. Cambie a B y compruebe la fecha de última captura en el selector. Reabra A y revise el cursor de Activity y sus operaciones.
- Con A reconocida, detenga la API y deje capturar al relay. Observe los pendientes, cambie de cuenta y vuelva a iniciar la API. Compruebe la entrega a A y la captura de B. Repita la recepción de una operación desde una segunda terminal y compruebe que el historial de la cuenta muestra una sola operación por ticket.
- Pruebe dos cuentas con el mismo número en servidores distintos. Compruebe la separación del estado, las operaciones, la evolución y las métricas al cambiar de cuenta en la misma sesión.
- En equipos separados compruebe las URLs externas, el certificado TLS y la recuperación de captura después de una interrupción de red.

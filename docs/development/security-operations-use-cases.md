# Casos de uso de seguridad y operación

Complemento del [roadmap](security-operations-roadmap.md). Cada caso identifica el punto donde debe aplicarse la guarda y qué observar durante la validación conjunta.

## 1. Preparar uv en Windows

Mantener la búsqueda local de `Find-Uv`. Para la descarga inicial usar un binario de una release oficial versionada. Registrar en el repositorio la huella de cada arquitectura soportada, verificada antes de incorporar el cambio. Usar una versión compatible con el proyecto y contrastarla con la de CI. La huella cubre el archivo que contiene el ejecutable final.

```text
buscar uv instalado en rutas admitidas
si existe y cumple la política de compatibilidad: usar su ruta absoluta
si falta o es incompatible:
    seleccionar versión, URL y SHA-256 por arquitectura del sistema
    si falta una entrada: explicar la plataforma y detener
    crear temporal privado para esta ejecución
    intentar:
        descargar el artefacto y comparar su SHA-256 con la referencia empaquetada
        ante error de red o diferencia de huella: detener antes de extraer o ejecutar
        extraer solo el ejecutable esperado en el directorio privado
        publicar por reemplazo atómico en una ubicación de usuario versionada
        seleccionar esa ruta absoluta
    finalmente: retirar solo el temporal propio
ejecutar uv sync --locked --no-dev y propagar el resultado a la interfaz
```

Validar arranque offline con uv compatible, instalación limpia, plataforma desconocida, descarga interrumpida, huella incorrecta y dos preparaciones simultáneas. Un fallo debe conservar cualquier instalación utilizable anterior.

## 2. Abrir una instalación existente o restaurada

`installation.private_directory` crea la carpeta con permisos privados. `prepare` admite los marcadores `setup.version` y `multicuenta.version`. Un marcador válido identifica el formato. La comprobación de acceso debe preceder también a los caminos que leen directamente archivos privados, como alta, vinculación y arranque de servicios.

```text
examinar la ruta y cada componente relevante antes de seguir enlaces
si es una instalación nueva: crear el directorio privado y verificarlo antes de escribir el marcador
si se reutiliza: verificar primero el directorio y luego el marcador regular de versión 2
en Windows:
    leer propietario y DACL por SID, incluidas reglas heredadas y explícitas
    comprobar que solo usuario autorizado y SYSTEM pueden leer secretos o alterar archivos
    rechazar propietario no confiable, DACL nula o derechos efectivos ambiguos
en POSIX: comprobar propietario, bits de acceso privados y permisos efectivos aplicables
para cada archivo sensible que se abrirá:
    verificar destino regular, propietario y permisos propios, incluso si el padre es privado
si falla una comprobación: mostrar ruta y motivo saneados y salir antes de consumir el archivo
adquirir el bloqueo aplicable y operar sobre las rutas verificadas
```

Incluir en la política los archivos de configuración que determinan destinos, las claves y los archivos de datos. Considerar sustitución de rutas entre inspección y apertura mediante un directorio padre confiable y apertura segura donde corresponda. Validar herencia correcta, archivo con permisos explícitos amplios, marcador antiguo, junction, enlace y error al consultar permisos. La reparación de permisos de una copia restaurada debe ser una acción explícita.

## 3. Admitir peticiones del catálogo exterior

Los modelos `Registration` y `Observed` hoy se procesan antes de que entre el manejador. Aplicar la política en la frontera ASGI antes de FastAPI. Reutilizar la semántica del límite central de 256 KiB y conservar `TrustedHostMiddleware` y la autenticación de las aplicaciones montadas.

```text
para POST /catalog: exigir el bearer de administración
para POST /resolve/{role}: validar el bearer de productor para ese rol
    resolver trading-events-raw con la credencial trading-events
para POST de pairing: conservar autenticación administrativa y acotar también el cuerpo
si falla la autorización: devolver 401 antes de consumir el cuerpo
si Content-Length es inválido o ambiguo: rechazar la petición
si la longitud declarada supera el límite: devolver 413
leer los fragmentos entrantes contando bytes antes de agregarlos al búfer acotado
si se supera el límite real: devolver 413 sin invocar el manejador
entregar el cuerpo una sola vez a FastAPI y mantener sus validaciones de campos
preservar no-store también en las respuestas tempranas
```

Probar en conjunto cuerpo en el límite y un byte por encima, ausencia de longitud, transferencia fragmentada, cliente desconectado, JSON inválido y rol incorrecto. Con credencial válida deben conservarse el alta, el 404 con motivo para cuentas desconocidas y el 503 de proyección para raw en esquema antiguo. Los POST de ingesta montados mantienen su validación y sustitución interna del bearer.

## 4. Reutilizar el relay con la misma API

El retorno temprano de `prepare` cuando coincide la URL debe ocurrir después de verificar el almacenamiento del relay. Distinguir una instalación limpia de la pérdida de una cola que ya estaba vinculada.

```text
bajo prepare.lock y tras validar permisos:
    leer la configuración previa del rol
    si existen credenciales previas del relay:
        exigir una cola existente y regular antes de abrir SQLite
        verificar en modo de lectura versión soportada y objetos requeridos de esa versión
        si falta, está dañada o es incompatible: informar y detener la preparación
        si la API coincide: reutilizar claves y cola
        si cambió: aplicar la guarda existente de credenciales y bindings antes de guardar
    si no existen claves ni cola: seguir el flujo de primera preparación
    si existe una cola huérfana: informar estado incompleto y conservarla para recuperación
    confirmar la configuración solo tras completar las comprobaciones
```

Evitar que una apertura SQLite normal cree un archivo ausente. La verificación de estado debe ser de lectura, incluso para una cola v1 cuyo constructor operativo puede migrar a v2. Un bloqueo temporal se reporta como ocupado. Validar cola vacía, cola con pendientes, destino central distinto y reintento tras interrupción.

## 5. Mostrar qué servicio está disponible

Separar el bloqueo de proceso local de la respuesta HTTP. Telemetry y Activity pueden escuchar en puertos distintos o compartir uno. El endpoint configurado de la API puede estar en otro equipo.

```text
GET /health de la API:
    abrir la base existente en lectura con tiempo de espera acotado
    verificar versión compatible y ejecutar una consulta mínima sobre la tabla de catálogo
    aceptar un catálogo vacío válido
    si la comprobación pasa: devolver 200 y status ready
    ante fallo: devolver 503 con código estable sin detalles privados
estado de SetUp:
    para cada rol local seleccionado: consultar su bloqueo y último error saneado si está detenido
    si relay activo: agrupar Telemetry y Activity por puerto local y consultar /health una vez por puerto
    validar respuesta y atributos de cola, indicando qué listener falló
    mostrar pendientes una sola vez por cola compartida
    para API y dashboard activos: interpretar el contrato propio de /health
    consultar además api_base_url/health con timeout y la configuración remota seleccionada
    distinguir timeout, respuesta inválida y servicio que responde degradado
```

Mantener cada consulta acotada y continuar con las demás tras un fallo. Validar puertos iguales, solo Activity inaccesible, proceso detenido, API local disponible con URL configurada inaccesible, y base ausente o ilegible. Consultar estado nunca crea la base, migra la cola ni inicia procesos.

# Roadmap de seguridad y operación

Rama `fix/tradinglab-review-security-operations`, basada en el commit de rendimiento `3f1dc76`. El alcance corresponde a [Seguridad y operación](tradinglab-static-review.md#seguridad-y-operación). Los [casos de uso](security-operations-use-cases.md) describen los caminos normales y de fallo.

| Orden | Trabajo y punto de entrada | Criterio de cierre |
| --- | --- | --- |
| 1 | Bootstrap de Windows en `scripts/tradinglab_setup_windows.ps1`. Incluir en el paquete la referencia de versión, plataforma y SHA-256 del artefacto de uv. | La instalación limpia usa exclusivamente bytes verificados. Una instalación existente compatible sigue funcionando sin descarga. |
| 2 | Compartir la política de directorio privado entre `installation.py`, `multi_host.py` y los accesos directos de `multi_operations.py`. | Una instalación nueva o restaurada comprueba propietario, permisos y destino antes de leer claves o escribir. Se aceptan ambos marcadores históricos. |
| 3 | Proteger el catálogo exterior de `multi_catalog.py` antes de la deserialización de FastAPI. | Alta y resolución mantienen autorización por rol, límites efectivos y errores de negocio con o sin proxy. |
| 4 | Comprobar la cola antes de reutilizar la vinculación en `multi_host.prepare`. | Repetir la preparación conserva identidad, claves, mensajes y bindings. La ausencia de una cola previamente configurada se hace visible. |
| 5 | Completar la disponibilidad de la API y el diagnóstico de los listeners en `multi_catalog.py` y `multi_operations.status`. | SetUp distingue proceso, endpoint y dependencia afectada en instalaciones locales y distribuidas. |

## Secuencia de integración

El bootstrap fija uv 0.13.0 para Windows y reutiliza una instalación local de esa versión o posterior. Las huellas del paquete corresponden a los wheels de Windows x64, ARM64 y x86 publicados en [PyPI](https://pypi.org/project/uv/0.13.0/#files).

En Windows se admiten como propietarios el usuario actual, SYSTEM y el grupo local Administradores. Las reglas de acceso permitido se restringen al usuario actual y SYSTEM, de acuerdo con los permisos que aplica SetUp al crear la carpeta. Ante una copia restaurada con permisos incompatibles, el operador debe revisar el propietario y las reglas antes de reintentar.

Una preparación repetida comprueba en lectura el esquema, la integridad y los contadores de la cola. Esta comprobación puede recorrer el historial retenido durante la preparación. La consulta de estado de los listeners usa los contadores operativos de la cola.

Preparar cambios pequeños por fila. Aplicar la comprobación de permisos antes de la de integridad de la cola. Definir el contrato de salud de la API antes de cambiar su consumidor en SetUp. Mantener las regresiones junto al código de cada cambio y ejecutar las pruebas juntas al finalizar todos los bloques de fixes.

En la ronda conjunta, usar carpetas y bases de prueba, una instalación nueva y otra restaurada, los esquemas centrales admitidos y colas con mensajes pendientes. Incluir Windows para el bootstrap y las ACL reales. Comprobar la distribución empaquetada además del checkout. Registrar versión, escenario y resultado sin credenciales.

# Revisión del sistema: errores, performance y seguridad

Fecha: 2026-10-21 (Europe/Madrid).
Base de performance y seguridad: `cd80098`, main después del PR #23.
Estado: análisis terminado para el alcance indicado; remediación de seguridad registrada debajo.

## Alcance y evidencia

Se revisaron collector MQL5, receptor HTTP, contrato, persistencia SQLite,
inspector, backups, cliente del receptor, servidor del dashboard, frontend,
arranque y configuración de CI. Las pruebas adicionales usaron bases temporales,
datos sintéticos y servidores efímeros en loopback. No se alteraron terminales,
captura activa, base operativa, credenciales ni configuraciones del broker.

Las cifras de performance son medianas locales de ensayos pequeños con Python
3.14 en esta máquina; no son SLA ni resultados de carga sostenida. La evaluación
de seguridad es revisión de código y reproducciones acotadas, no una certificación.
No se probaron explotación desde un navegador externo, permisos efectivos del
sistema operativo, configuración de firewall, binarios instalados, historial Git
completo, vulnerabilidades publicadas de dependencias ni tiempos reales de MT5.

## Errores: cierre del primer bloque

Los cinco hallazgos originales fueron abordados mediante merge humano:

| Hallazgo | Integración |
| --- | --- |
| Captura futura bloquea recuperación de la vista | [PR #21](https://github.com/jbordes/trading-lab/pull/21) |
| Mismo deal contado en varias fuentes de una cuenta | [PR #22](https://github.com/jbordes/trading-lab/pull/22) |
| Resumen inconsistente ante escrituras concurrentes | [PR #23](https://github.com/jbordes/trading-lab/pull/23) |
| Detalle de operaciones truncado sin advertencia | PR #23 |
| Cursor incremental compara fechas como texto | PR #23 |

La validación local final de ese bloque pasó 25 pruebas del harness y 159 de
producto, formato, lint y sintaxis JavaScript. Este registro no sustituye una
prueba visual ni asegura ausencia de otros errores.

## Performance

### P1. Inspección histórica e interferencia con la captura — alta

`inspection.py` recorre los mensajes y descompone JSON para los conteos históricos.
El resumen consistente mantiene una transacción de lectura. La base creada por
el código actual usa `journal_mode=delete`: el lector puede retrasar el commit
de un escritor. La consistencia introducida por PR #23 debe conservarse.

Ensayo: mensajes de una fuente y sesión, diez deals repetidos por muestra,
órdenes sintéticas, esquema real y carga inicial por lotes. Tres inspecciones
por tamaño; se informa mediana, sin `--verify`.

| Muestras | Base SQLite | Inspección |
| ---: | ---: | ---: |
| 1.000 | 4,05 MiB | 104 ms |
| 10.000 | 40,20 MiB | 982 ms |
| 30.000 | 120,55 MiB | 3.086 ms |

30.000 muestras a cinco segundos representan unas 42 horas. En otra base temporal,
una lectura abierta impidió el commit de una segunda conexión: con timeout de
100 ms el escritor recibió `database is locked` a los 108 ms; al cerrar la
lectura, pudo confirmar. Esto demuestra contención, no pérdida de datos.

El collector espera por defecto 500 ms. Si una inspección se solapa con una
entrega, puede provocar timeout y reenvío aun cuando el receptor termine
confirmando. Los reintentos idempotentes siguen siendo necesarios.

Propuesta: medir WAL con lecturas/escrituras concurrentes, comprobar checkpoints,
backups y recuperación; optimizar consultas del inspector o separar proyecciones
para consultas frecuentes. No cambiar el modo de la base activa automáticamente.
Aceptación: resumen consistente y latencia de recepción dentro del presupuesto
del collector durante una inspección representativa.

### P2. Consulta de secuencia creciente por sesión — media

`sqlite_store.py` busca la última secuencia usando `ORDER BY length(sequence),
sequence`. `EXPLAIN QUERY PLAN` muestra el índice de identidad para encontrar la
sesión, seguido de `USE TEMP B-TREE FOR ORDER BY`.

Medianas de siete consultas: 0,146 ms con 1.000 mensajes, 1,151 ms con 10.000,
5,769 ms con 30.000. El costo se paga por mensaje nuevo de esa sesión.

Propuesta: comparar un índice compatible con ese orden frente a mantener el
último número confirmado transaccionalmente. Preservar enteros grandes,
idempotencia, rechazo de secuencias antiguas y separación por fuente/sesión.
Aceptación: mejora medida a varios tamaños y estrategia explícita de migración
si cambia el esquema; no introducir un índice incompatible con su validación actual.

### P3. Repetición de historial y crecimiento — media

El collector relee una hora de historia y envía hasta 200 deals por snapshot;
el journal conserva el mensaje completo. Estimaciones con una orden sintética:

| Deals por muestra | Bytes de JSON por muestra | JSON por día a cinco segundos |
| ---: | ---: | ---: |
| 0 | 824 | 13,6 MiB |
| 10 | 2.994 | 49,3 MiB |
| 200 | 44.225 | 728,8 MiB |

Son escenarios de carga constante, no el volumen observado de la cuenta real.
Excluyen índices, sobrecosto SQLite y copias. Las copias completas conservadas
cada día acumulan también las repeticiones de todos los días anteriores.

Abrir el registro de 120,55 MiB, incluidas verificaciones de integridad, tardó
452 ms de mediana. El último snapshot se obtuvo en 0,559 ms. No retirar controles
de integridad para ganar tiempo sin una política alternativa comprobada.

Propuesta: medir tamaños operativos, consultar entidades/proyecciones deduplicadas
y evaluar captura incremental con reconciliación. La retención y evidencia cruda
requieren decisión explícita; este análisis no autoriza borrados ni compactación.

### P4. Validaciones y copias repetidas — posterior

El recorrido persistente vuelve a validar el sobre en la vista, al guardarlo y
al restaurarlo. El perfil de un reenvío de 200 deals confirmó tres llamadas a
`parse_envelope` dentro del backend, además de la validación HTTP externa.

En bases pequeñas, quince aceptaciones nuevas por tamaño dieron medianas de
4,568 / 5,909 / 23,428 ms para 0 / 10 / 200 deals. Excluyen red y captura MT5.
Con 30.000 mensajes previos, guardar un mensaje pequeño dio 11,938 ms.

Propuesta: reutilizar sobres internos ya validados y su representación canónica,
sin omitir validación externa ni integridad de lecturas persistidas. Prioridad
inferior a contención y crecimiento.

### Dashboard y límites de la medición

Preparar estado con 720 puntos costó aproximadamente 0,3 ms; filtrar el historial
incremental, 0,9 ms. El frontend pausa polling oculto, evita requests superpuestos,
conserva historial acotado y reutiliza filas. No hay evidencia para cambiar
framework o gráficos por performance en este momento. Faltan mediciones de
renderizado móvil, `HistorySelect` real, varias fuentes y carga sostenida.

## Seguridad

Modelo de confianza actual: cuenta demo aprobada, servicios en `127.0.0.1`,
operador local y token de telemetría. Loopback restringe acceso de red, pero no
autentica procesos ni usuarios locales. No existe todavía un acceso remoto aprobado.

### Estado de remediación

| Hallazgo | Estado |
| --- | --- |
| S1: autenticación y validación de Host | Integrado mediante PR #25 |
| S2: redirecciones y proxies implícitos | Implementado en `fix/dashboard-http-hardening`; pendiente de merge humano |
| S3: conexiones y plazo del servidor | Implementado en `fix/dashboard-http-hardening`; pendiente de merge humano |

La remediación de S2 fija el destino en loopback, desactiva proxies implícitos y
convierte cualquier respuesta 30x de snapshot o `health` en un error controlado.
La regresión comprueba que el destino de la redirección no recibe una solicitud.
La de S3 reutiliza el servidor HTTP acotado: admite como máximo 16 conexiones y
aplica un plazo total de cinco segundos por conexión de forma predeterminada. Las
pruebas cubren clientes lentos, rechazo por exceso y liberación durante el cierre.

### S1. Dashboard sin autenticación y sin validación de Host — alta antes de acceso remoto

`dashboard/web.py` publica `/dashboard` y `/api/state` sin sesión ni credencial.
Una solicitud sintética a loopback con `Host: untrusted.example` y un `Origin`
ajeno recibió HTTP 200 y datos demo de cuenta. No se comprueba ninguno de esos
encabezados. No hay `Access-Control-Allow-Origin` permisivo.

Impacto demostrado: cualquier cliente local capaz de alcanzar el puerto puede
leer los datos; el servidor acepta nombres de host arbitrarios. La ausencia de
restricción de Host deja pendiente protección contra DNS rebinding. No se
demostró explotación desde navegador: sus restricciones de origen y acceso a red
local pueden intervenir; un Origin ajeno por sí solo no prueba lectura cross-site.

Propuesta: aceptar autoridades locales explícitas y rechazar hosts inesperados;
diseñar autenticación para la interfaz y API antes de acceso compartido/remoto.
El token del collector no debe convertirse en credencial del navegador. Si se
habilita acceso remoto, requerirá transporte cifrado y una decisión de despliegue.
Aceptación: Host ajeno rechazado y pruebas de autorización acordes al modo publicado.

### S2. Cliente local sigue redirecciones con Authorization — media, confirmado

`LoopbackTelemetryClient.latest()` construye una URL local, pero usa `urlopen`
con el manejador de redirecciones predeterminado. Dos servidores efímeros de
prueba demostraron que un 302 a otro puerto reenvía `Authorization`; se usó
exclusivamente un token sintético y se imprimió solo presencia/ausencia.

La implementación de `urllib` instalada copia ese encabezado al nuevo request.
La validación del cuerpo final ocurre después del envío de la credencial.
La prueba se limitó a dos puertos de loopback; no se envió nada a un host externo.

Precondición: el destino consultado debe devolver una redirección, por sustitución,
compromiso o configuración inesperada. No se demostró que un tercero remoto pueda
controlar el receptor actual. Quien controla el destino inicial ya puede observar
el token; el problema adicional es salir del destino autorizado automáticamente.

Propuesta: rechazar redirecciones, desactivar proxies implícitos para este cliente
y fijar la conexión al endpoint local. Aplicar la política también a health.
Aceptación: un 30x produce error controlado y el segundo servidor no recibe request.

### S3. Servidor del dashboard sin límites de conexiones ni plazo — media

El receptor usa `BoundedTelemetryServer`, pero el dashboard utiliza
`ThreadingHTTPServer` directamente. Tres requests sintéticos con encabezados
incompletos crearon tres workers y sus sockets tenían timeout `None`. Se cerraron
todos al terminar. No se ejecutó una prueba de agotamiento de recursos.

Un cliente local puede mantener conexiones y consumir hilos/recursos. Si se
publicara mediante proxy, habría que considerar también esa frontera.

Propuesta: límite de admisión y plazo total por conexión, aprovechando el patrón
testeado del receptor cuando sea compatible con el dashboard. Aceptación: clientes
lentos vencen, exceso de conexiones se limita y shutdown libera recursos.

### Límites de confianza que deben quedar explícitos

- El mismo token permite leer snapshots y enviar telemetría. Antes de separar
  componentes entre máquinas/usuarios, evaluar credenciales y permisos separados,
  rotación y revocación. Hoy no existe una capacidad de trading remota en el receptor.
- El token autentica al emisor que lo posee, no demuestra que sea MT5. En SQLite
  se restringe una fuente y se contrastan servidor/moneda; la cuenta enmascarada
  no es una prueba criptográfica de identidad. La guarda de cuenta vive en el EA.
- Archivos SQLite y backups conservan información sensible de trading. Gitignore
  evita versionarlos por defecto, pero no restringe lectura local ni cifra archivos.
  Permisos efectivos, cifrado del disco y exportación segura quedan por verificar
  antes de compartir la VPS o usar cuentas productivas.
- SHA-256 detecta inconsistencias al comparar contenido, pero no protege contra
  un actor que pueda reescribir simultáneamente datos y hashes. No es firma de origen.
- El JSON tiene tamaño acotado y la concurrencia del receptor está limitada; el
  almacenamiento durable no tiene cuota automática. Un emisor autorizado defectuoso
  puede llenar disco. Relacionar monitoreo/retención con P3; no borrar automáticamente.
- CI tiene dependencias fijadas por lock y acciones fijadas por commit, pero este
  análisis no consultó una base de avisos de vulnerabilidades. No se afirma que las
  versiones estén libres de CVEs. Falta establecer esa comprobación periódica.

### Controles existentes observados

- Ambos servidores enlazan `127.0.0.1`; collector valida URL loopback exacta.
- Ingesta y snapshot del receptor exigen Bearer, comparación constante y un solo
  encabezado Authorization. El modo persistente restringe fuente autorizada.
- Límite de 256 KiB, JSON con claves únicas, campos y tipos estrictos, profundidad
  y colecciones limitadas, números finitos y validación de identificadores.
- Receptor limita conexiones/plazos y rechaza framing ambiguo y métodos de escritura
  no admitidos. SQL usa parámetros para entradas de datos.
- Frontend usa `textContent` para datos; servidor sirve un mapa fijo de assets y
  envía CSP, `nosniff`, política de referrer y `no-store` para estado.
- Token no forma parte de argumentos del proceso ni del estado entregado al
  navegador. Arranque soporta entrada oculta y no lee presets ni `.env` reales.
- Collector revisado contiene guardas de cuenta demo y lecturas; no comandos de
  trading ni ejecución de comandos recibidos. No se verificó el binario instalado.
- CI usa permisos de lectura y el harness busca secretos/artefactos prohibidos.
  Esto es una defensa parcial, no un escaneo exhaustivo del historial Git.

## Orden propuesto para retomar

1. Integrar mediante revisión humana la remediación ya implementada de S2 y S3.
2. P1: resolver contención conservando consistencia y durabilidad.
3. P2: optimizar consulta de secuencias con mediciones comparables.
4. P3: acordar crecimiento, proyecciones y captura incremental sin perder evidencia.
5. P4: simplificar validaciones internas si el perfil sigue justificándolo.

Cada implementación requiere rama/PR y merge humano. Este documento no autoriza
cambios operativos. El bloque de errores y S1 están integrados; S2 y S3 esperan
merge humano y las propuestas de performance continúan pendientes.

## Cadencia de revisión acordada

Repetir el ciclo cada seis PRs efectivamente mergeados en main, contando merges y
no saltos entre números de PR. Baseline del ciclo cerrado: PR #23 (`cd80098`).
El PR que publique este informe cuenta dentro del siguiente grupo de seis.
Separar de nuevo errores, seguridad y performance para cerrar cada análisis con
evidencias. La cadencia queda registrada; no existe todavía contador ni bloqueo CI
automático. Al retomar, consultar merges posteriores al baseline.

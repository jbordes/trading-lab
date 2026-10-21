# Operación supervisada del collector MT5

**Estado:** procedimiento manual propuesto para validar

**Alcance:** terminales demo locales; no habilita cuentas reales ni instalación remota

## Objetivo

Instalar, configurar, comprobar, actualizar y retirar una instancia de
`TradingLabTelemetry` sin descubrir terminales automáticamente, mezclar cuentas ni
exponer credenciales. Cada collector se ejecuta dentro de la terminal que observa;
el receptor y el dashboard seleccionan sus datos mediante un `source_id` explícito.

Este procedimiento debe ejecutarse manualmente y registrar sus excepciones antes
de crear scripts de instalación o una skill. El collector es de solo lectura, pero
copiar archivos, adjuntar EAs y cambiar la lista de WebRequest siguen siendo
acciones del operador sobre MT5.

## Modelo multterminal

- Una identidad MT5 aprobada tiene exactamente un `source_id` estable y un solo
  collector adjunto. Al cambiar de cuenta, se asigna otro identificador.
- Varias terminales del mismo equipo pueden enviar al mismo receptor loopback y
  puerto. El receptor conserva la última muestra por `source_id`.
- `source_id` selecciona datos; no autoriza. El Bearer token protege el receptor
  completo y actualmente es compartido por todos los collectors que lo usan.
- La carpeta de datos y el MetaEditor deben pertenecer a la terminal objetivo. No
  se eligen por el orden en que Windows o MT5 los descubran.
- No se ejecutan dos collectors con el mismo `source_id`, aunque estén en cuentas
  o terminales diferentes.

## Datos necesarios

Registrar antes de comenzar, sin guardar secretos en Git:

| Dato | Regla |
| --- | --- |
| Commit del repositorio | Debe contener la fuente revisada que se compilará. |
| Terminal objetivo | Identificada por su ejecutable y carpeta de datos exactos. |
| Cuenta y servidor | Comparados localmente con MT5; el registro compartido los enmascara. |
| `source_id` | Identificador no sensible, único para esa identidad. |
| Puerto loopback | `8766` por defecto; debe coincidir en receptor, EA y WebRequest. |
| Token | ASCII imprimible de al menos 24 caracteres, generado y conservado fuera de Git. |
| Parámetros | Intervalo, timeout, límites y ventana de historial revisados por el operador. |

No copiar ni registrar el token, una contraseña, un archivo `.env`, el login
completo o un preset que contenga secretos. Un `.set` es texto plano y debe
tratarse como secreto cuando incluya el token.

## Precondiciones

1. Usar únicamente una cuenta demo aprobada. Las cuentas reales permanecen fuera
   de alcance hasta superar el gate de promoción.
2. Confirmar dentro de la terminal objetivo su servidor, tipo de cuenta y carpeta
   mediante **Archivo > Abrir carpeta de datos**. No deducirla desde otra instancia.
3. Mantener trading algorítmico deshabilitado durante esta validación. El collector
   no necesita llamadas de trading.
4. Preparar el repositorio con `uv sync --locked` y ejecutar
   `uv run python scripts/check.py full` en el commit que se instalará.
5. Verificar que no haya otro collector adjunto para el mismo `source_id`.

## Instalación y configuración

### 1. Preparar el receptor

Definir el token solamente en el entorno del proceso e iniciar el receptor:

```text
TRADINGLAB_TELEMETRY_TOKEN=<token local>
uv run python scripts/telemetry_receiver.py --port 8766
```

En PowerShell, Bash o el supervisor futuro se usa la sintaxis propia del sistema;
el valor nunca se incorpora al comando documentado, al repositorio ni a una
captura. Comprobar que `http://127.0.0.1:8766/health` responde localmente.

### 2. Compilar para la terminal correcta

1. Copiar la fuente revisada
   `apps/mt5-telemetry-collector/TradingLabTelemetry.mq5` dentro de una carpeta
   identificable bajo `<data-folder>/MQL5/Experts/` de la terminal objetivo.
2. Abrir el MetaEditor desde esa misma terminal y compilar esa copia.
3. Exigir **0 errores y 0 warnings**. Comprobar que el `.ex5` resultante está en
   la misma carpeta de datos y no en la de otra instalación.
4. Registrar commit, hash SHA-256 de la fuente copiada y builds de MetaEditor/MT5,
   sin versionar el `.ex5`, el log completo ni la carpeta de datos.

Si no puede demostrarse a qué carpeta pertenece el compilado, detener el proceso.

### 3. Autorizar el destino local

En **Herramientas > Opciones > Asesores Expertos**, autorizar únicamente la base
loopback correspondiente, por ejemplo `http://127.0.0.1:8766`. No autorizar
dominios externos, `localhost`, comodines ni un puerto distinto al configurado.

La autorización WebRequest es configuración de esa instalación. Confirmarla en
la terminal objetivo incluso si otra terminal del equipo ya funciona.

### 4. Adjuntar y configurar el EA

Adjuntar el collector a un solo gráfico dedicado y completar localmente:

- `IngestUrl`: `http://127.0.0.1:<puerto>/v1/telemetry`;
- `Token`: el mismo secreto del receptor;
- `SourceId`: el identificador aprobado para esa cuenta;
- `ExpectedDemoLogin` y `ExpectedDemoServer`: identidad exacta que el EA debe
  verificar, sin incorporarla a Git;
- intervalo, timeout, límites y ventana histórica dentro de los rangos validados.

No reutilizar un preset con identidad o token de otra terminal. Conservar el
trading algorítmico deshabilitado y comprobar en el log **read-only spike started**.
Un error de identidad, URL o parámetros es un rechazo correcto y no debe sortearse.

### 5. Conectar el dashboard

Con el token de telemetría disponible fuera de Git, iniciar el dashboard. El
comando pedirá de forma oculta un segundo token para el acceso humano:

```text
uv run python scripts/live_dashboard.py --telemetry --telemetry-source <source_id>
```

Abrir `http://127.0.0.1:8765/dashboard` e ingresar el segundo token en `/login`.
No ingresar allí el token del EA. No seleccionar una fuente modificando el collector
ni abriendo terminales en otro orden.

## Verificación de aceptación

La instalación se acepta solamente si se cumplen todos estos puntos:

1. El log de MT5 identifica el arranque sin imprimir token ni login completo.
2. `/health` avanza en mensajes aceptados y no muestra fallos continuos.
3. El dashboard pasa de sin datos a conectado para el `source_id` esperado.
4. Cuenta enmascarada, balance, equity, flotante, posiciones, órdenes y Magic
   Numbers coinciden con la terminal objetivo o una captura diagnóstica aislada.
5. Solicitar otro `source_id` produce sus propios datos o 404; nunca los de esta
   terminal.
6. Una interrupción controlada del receptor degrada el dashboard; al restaurarlo,
   la cola drena y vuelve a avanzar sin intervención sobre las operaciones.
7. Reiniciar o volver a adjuntar el EA crea una sesión nueva y mantiene la misma
   identidad aprobada.
8. No se habilitó trading, no se enviaron órdenes y no se modificó otra terminal.

Registrar resultado, hora, latencia observada y contadores generales. No guardar
payloads, históricos ni identificadores completos en Git.

## Fallo seguro

Detener y no reintentar a ciegas cuando ocurra cualquiera de estos casos:

- carpeta, cuenta, servidor o tipo de cuenta no coinciden;
- compilación con errores o warnings;
- `source_id` repetido o ambiguo;
- el dashboard muestra una identidad o valores de otra terminal;
- WebRequest apunta fuera de loopback o el receptor redirige;
- el collector queda detenido por `pilot_guard`;
- aparecen rechazos sostenidos, truncamiento inesperado o crecimiento anormal del
  payload.

Conservar solo evidencia no sensible, retirar el EA si corresponde y diagnosticar
antes de volver a adjuntarlo.

## Actualización y rollback

1. Validar primero receptor y contrato compatibles con la nueva versión.
2. Detener o retirar el collector de su gráfico antes de reemplazar el binario.
3. Compilar desde el nuevo commit en la carpeta de la terminal objetivo.
4. Revisar nuevamente todos los inputs; nunca heredar el token o la identidad de
   otra instalación.
5. Adjuntar una sola instancia y repetir la verificación de aceptación.

Ante un fallo, retirar la versión nueva. El rollback consiste en recompilar la
fuente revisada del commit anterior y repetir el procedimiento; no se conserva un
`.ex5` sin procedencia ni se sobrescribe una instancia activa. Un cambio de cuenta
exige otro `source_id`, no un rollback silencioso.

## Retiro

El retiro requiere aprobación del operador de la terminal:

1. Identificar por gráfico, `source_id` y log la instancia exacta.
2. Retirar el EA del gráfico y confirmar el mensaje de detención.
3. Verificar que el dashboard de ese `source_id` termina degradado por antigüedad.
   `/health` es global y puede seguir avanzando por otros collectors, por lo que
   no demuestra por sí solo el retiro de una fuente concreta.
4. Eliminar la copia `.mq5`, `.ex5` y presets locales solo después de resolver sus
   rutas dentro de la carpeta de datos correcta y confirmar que no los usa otra
   instancia.
5. Quitar la autorización WebRequest solo si ningún otro collector de esa terminal
   la necesita.
6. Rotar el token si pudo quedar expuesto. Como hoy es compartido por receptor,
   coordinar la actualización de todos sus collectors antes de revocarlo.

El receptor puede conservar temporalmente la última muestra en memoria hasta su
desalojo o reinicio; eso no significa que el collector siga ejecutándose.

## Evidencia mínima

- fecha, operador y resultado;
- commit y SHA-256 de la fuente;
- builds de MT5 y MetaEditor;
- ruta de datos identificada de forma local, redactada si se comparte;
- `source_id`, puerto y parámetros no secretos;
- identidad enmascarada y tipo demo;
- 0 errores/0 warnings y checklist de aceptación;
- motivo y resultado de actualización, rollback o retiro.

La primera ejecución en una segunda terminal debe tratarse como validación de este
runbook. Sus diferencias y excepciones decidirán qué pasos merece la pena
automatizar; hasta entonces no se crea un instalador ni una skill.

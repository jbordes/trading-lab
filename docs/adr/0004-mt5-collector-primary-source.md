# ADR-0004: Collector MQL5 como fuente operativa primaria

**Estado:** accepted

**Fecha:** 2026-10-17

## Contexto

TradingLab debe observar varias terminales MT5 ejecutándose simultáneamente en
una misma VPS. La integración oficial de Python permite indicar la ruta del
ejecutable en `initialize()`, pero sin ella selecciona una instalación de forma
automática. No documenta aislamiento concurrente de varias terminales dentro de
un mismo proceso.

Una prueba local con las dos instalaciones autorizadas mostró:

- 20 inicializaciones sin ruta eligieron la terminal del socio, aunque la de
  pruebas también estaba abierta;
- dos procesos independientes, cada uno con ruta explícita, completaron 50 ciclos
  concurrentes por terminal sin cruces ni fallos;
- dos conexiones forzadas dentro del mismo proceso compartieron el estado del
  módulo: la lectura destinada a una terminal terminó vinculada a la otra en los
  30 ciclos.

Por tanto, usar Python en producción exigiría un worker supervisado por terminal,
configuración e identidad explícitas, comunicación entre procesos y recuperación
independiente. El collector propio ya se ejecuta dentro de la terminal, valida la
cuenta y el servidor esperados y publica un `source_id` estable. Su piloto demo
integrado también comprobó degradación y recuperación del dashboard.

Referencias oficiales: [`initialize()`](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py)
y [`terminal_info()`](https://www.mql5.com/en/docs/python_metatrader5/mt5terminalinfo_py).

## Alternativas consideradas

1. Mantener una única conexión Python automática: mínima configuración, pero no
   identifica la terminal deseada y queda descartada para varias instancias.
2. Crear un proceso Python por terminal: técnicamente viable con ruta y guardas
   explícitas, a costa de supervisar una topología paralela al collector.
3. Adoptar un collector MQL5 por terminal como fuente operativa y reservar Python
   para diagnósticos o reconciliaciones aisladas.

## Decisión

Se adopta la tercera alternativa.

Cada terminal MT5 observada tendrá un único collector aprobado y un `source_id`
no sensible asociado a una sola identidad de cuenta. El dashboard consumirá la
telemetría validada por el receptor; no descubrirá terminales mediante la API
Python ni compartirá una conexión Python entre fuentes.

La API Python se conserva como herramienta auxiliar de solo lectura. Toda
ejecución deberá seleccionar una ruta explícita, operar sobre una sola terminal
por proceso y comprobar ruta del ejecutable, carpeta de datos, cuenta y servidor
antes de aceptar evidencia. No se construirá un supervisor multterminal Python
mientras el collector cubra el flujo operativo.

La comparación amplia de rendimiento entre ambas vías deja de ser un gate de
arquitectura. Sigue siendo obligatoria una validación acotada con operaciones
reales para verificar campos, costes, Magic Number, timestamps, completitud y
frescura del contrato del collector. Python puede actuar como oráculo puntual en
una terminal aislada, pero esa prueba no reabre la decisión de topología.

## Consecuencias

- El aislamiento operativo coincide con el límite natural de cada terminal MT5.
- Se evita desarrollar y operar un worker Python por cada instancia.
- El collector, su contrato MQL5/Python y su instalación pasan a ser componentes
  mantenidos, no un spike descartable.
- Adjuntar, configurar, compilar y actualizar el EA requiere un procedimiento
  controlado por terminal y aprobación humana.
- La telemetría remota, persistencia durable y agregación multicuenta continúan
  fuera de esta decisión y necesitarán diseño propio.
- El adaptador Python actual no debe considerarse seguro para uso multterminal
  hasta que su entrada exija identidad explícita; se mantiene solo como soporte
  transitorio y diagnóstico.

## Reemplaza

Reemplaza la elección de la API Python como fuente MT5 operativa inicial de
ADR-0002 y el gate de ADR-0003 que subordinaba la topología a una comparación
amplia. Mantiene la frontera de solo lectura de ADR-0002 y convierte el resultado
positivo del spike de ADR-0003 en la dirección vigente.

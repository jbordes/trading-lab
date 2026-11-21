# Construcción de la plataforma de datos remota

## Próximos pasos acordados al 2026-11-09

El piloto local ya fue migrado de forma supervisada al esquema 8 y recibe
Telemetry 0.3.1 con hora del broker. El instalador independiente de mantenimiento
está desarrollado y documentado; no se instaló ninguna tarea. Estos avances
actualizan el estado histórico de los apartados siguientes, sin afirmar merge
ni despliegue remoto.

1. Cerrar la entrega actual mediante revisión del diff, PR a la rama de integración,
   CI y merge humano; no repetir por rutina todos los tests localmente.
2. Preparar el host de prueba elegido (Mac o Linux; Windows también soportado)
   con bootstrap y base nueva de esquema 8. La transferencia de los datos de
   prueba anteriores no es requisito para iniciar con una base vacía.
3. Conectar VPS → API privada con Tailscale, mantener SQLite local al host de
   datos y verificar el circuito collectors → relay → API → base → dashboard.
4. **Pendiente importante dentro de esa instalación:** instalar y ensayar el
   mantenimiento en el host de la base, siguiendo el
   [checklist operativo](automatic-maintenance.md). Verificar un disparo real,
   copia previa, primer cierre diario y reinicio/reposo/permisos. No activar
   ahora tareas en la VPS ni exigir ensayos en los tres sistemas a la vez.
5. Validar interrupciones y recuperación del circuito remoto y contrastar
   datos; completar la revisión de cierre antes del PR final hacia `main`.

Las pruebas nativas nuevas del reloj de Telemetry, la desconexión del broker,
el traslado verificable si se decide preservar datos y las garantías pendientes
de producción conservan su estado; no se consideran resueltas por el instalador.

Actualización en `feature/account-progression-history`, 2026-11-06: el código
incorpora esquema central 8 para el histórico diario observado y una migración
explícita 7 → 8, todavía sin aplicar al piloto. Ver
[almacenamiento diario](daily-account-history-storage.md). Las referencias a
esquema 7 y versiones anteriores más abajo describen hitos previos, no la
versión creada por el bootstrap de esta rama.

**Estado vigente al 2026-11-05:** piloto local operativo; contrato descriptivo y
esquema central 7 en rama actual pendiente de integración; traslado remoto pendiente

**Rama estable temporal:** `feature/remote-data-platform`

**Base inicial:** `origin/main` en `ff3b864`

El piloto local ya ejecuta los collectors Telemetry `0.2.1` y Activity
`activity-0.7.1`, una outbox durable con listeners `8776/8777`, FastAPI `8781`,
el dashboard `8775` y el modelo previo de dos archivos SQLite. La rama nueva
prepara el contrato descriptivo y una sola `central.sqlite3`/esquema 7; requiere
integración revisada y corte supervisado antes de reemplazar el modelo local.
La rama retira las CLIs, receptores y SQL aislados, y limita el producto central
a esquema 7. Pasaron 289 pruebas afectadas y el check `fast`; las pruebas nuevas
de esta feature siguen en curso. No se afirma una ejecución nueva de scripts
nativos ni activación de jobs.

Esta evidencia local no equivale a merge ni a CI verde. El estado de PRs no se
deduce aquí: requiere revisión humana y los checks correspondientes. No está
desplegado en la Mac, no existe aún el piloto remoto con enlace privado y no se
habilitan cuentas reales.

Pendiente: importador verificado para datos anteriores y cutover coordinado;
gestión centralizada de credenciales y permisos; preparar Mac/Tailscale;
prueba operativa de desconexión del broker; comparación amplia de
reportes/cuentas; backup y restauración para producción; revisión de fórmulas
financieras existentes y definición de métricas de riesgo y ejecución con el socio. La
retención de datos históricos conserva la política sin TTL; la retención de
14 días corresponde solo a los logs locales de diagnóstico.

## Objetivo

El objetivo sigue siendo separar progresivamente la persistencia y la API de la
VPS que ejecuta MT5, sin arriesgar la captura ni desestabilizar `main`. La
robustez de los collectors y la integración local de
[dashboard con FastAPI](central-api-dashboard.md) ya están implementadas y
probadas en el piloto local; la instalación vigente se describe en
[el manual operativo](mt5-collector-operations.md). La gestión de
[credenciales y permisos](credential-management-plan.md) sigue pendiente.

El piloto remoto alojará API, backend y
SQLite central/esquema 7 en una Mac conectada privadamente con la VPS. La base permanecerá en
disco local junto al backend; nunca se abrirá SQLite mediante una carpeta de red.

La implementación conservará receptores locales en la VPS y añadirá transporte
durable hacia la API central. Los EAs no recibirán acceso directo a la base ni
permisos genéricos de modificación o borrado.

## Modelo temporal de ramas

`feature/remote-data-platform` funciona como una rama de integración estable,
paralela a `main`, únicamente durante este programa:

```text
main (estable, sin cambios del programa)
  └─ feature/remote-data-platform (integración estable)
       ├─ docs/*
       ├─ feature/*
       ├─ fix/*
       └─ chore/*
```

Cada incremento:

1. nace de la cabeza actual de `feature/remote-data-platform`;
2. resuelve una capacidad o corrección coherente;
3. ejecuta validación local proporcional al riesgo;
4. abre un pull request cuyo destino es `feature/remote-data-platform`;
5. espera el gate completo de GitHub y merge humano;
6. actualiza la base de las entregas dependientes antes de publicarlas.

No se hacen merges directos, force-pushes ni cambios funcionales directos en la
rama de integración. El commit inicial que crea y documenta este proceso es una
excepción de arranque aprobada expresamente por el propietario.

## Bitácora durante el programa

La jornada sigue siendo una unidad por fecha en `Europe/Madrid` y no se acopla a
ninguna feature. Durante este programa:

- la entrada diaria canónica vive en `feature/remote-data-platform`;
- las ramas cortas no modifican `docs/sessions/`;
- únicamente la entrada de hoy puede crearse o actualizarse directamente en la
  rama de integración;
- el commit de bitácora no mezcla ninguna otra ruta;
- las entradas de días anteriores siguen siendo inmutables;
- `main` no recibe bitácoras hasta la integración final del programa.

La rama estable se declara en `tool.tradinglab.workflow.stable-branch` dentro de
`pyproject.toml`. El guard, el cálculo local del diff y el resumen de cambios usan
esa misma fuente. GitHub continúa tomando la base real de cada pull request. Al
cerrar el programa se elimina la configuración temporal y el valor vuelve a
`main` por defecto.

## Secuencia inicial y estado de entregas

Esta secuencia conserva el plan inicial. Los estados indican implementación y
validación local conocidas; no afirman merge o CI de una rama o PR.

**Paso 1 implementado localmente:** [contrato central](../architecture/central-ingestion-api-contract.md),
ingesta, lecturas y documentación OpenAPI. API central probada localmente.

**Paso 2 implementado localmente:** bootstrap de la [base central SQLite esquema 7](central-sqlite.md)
con vista previa, aplicación explícita y destino local fuera del checkout,
documentado en [preparación del host remoto](remote-host-setup.md). No implica
creación o traslado de una base operativa remota.

**Paso 3 implementado y activado en el piloto local:** [relay y outbox durable](durable-telemetry-relay.md),
integrados con los dos EAs y FastAPI. El traslado de API y SQLite a la Mac sigue
pendiente; el relay permanecerá junto a MT5 en la VPS.

FastAPI/OpenAPI se desarrolló dentro del programa y se integró al flujo local.
La guía de [operación central](central-api-operation.md) describe el estado
conocido; el despliegue remoto no se da por hecho.

1. **Contrato central y seguridad — implementado localmente.** Delimitar ingesta v1/v2, ACK durable,
   autenticación por productor, límites y lecturas del dashboard. No exponer
   operaciones genéricas de baja o modificación a los collectors.
2. **Creación limpia de la base central SQLite esquema 7 — implementado localmente.**
   El bootstrap portable crea una base nueva, registra cuenta y fuentes, y no
   sobrescribe un destino existente. Ver [SQLite central](central-sqlite.md) y
   [preparación del host](remote-host-setup.md).
3. **Relay y outbox durable — implementado en el piloto local.** Mantener los EAs en loopback y reenviar desde la VPS
   con idempotencia, reintentos, backoff y confirmación central.
4. **Servicio piloto en la Mac — pendiente.** Ejecutar API y SQLite juntas, usar conectividad
   privada y evitar suspensión o exposición pública accidental.
   La [preparación portable del host](remote-host-setup.md) y el
   [ADR-0019](../adr/0019-private-remote-host-bootstrap.md) y
   [ADR-0020](../adr/0020-single-central-sqlite-database.md) agregan bootstrap para
   Mac/Linux/Windows, una base central nueva y el procedimiento Tailscale VPS → API.
   No equivalen a instalación nativa ni enlace remoto ya validados.
5. **Validación extremo a extremo — parcial.** Probar cortes, reinicios, ACK perdido,
   duplicados, recuperación, atraso y reconciliación de conteos.
6. **Traslado verificable — pendiente.** Separar migración de esquema de exportación/importación
   entre hosts mediante snapshot consistente, manifest, hash e integridad.
7. **Cierre del programa — pendiente.** Revisar seguridad y robustez, retirar la excepción de
   ramas, actualizar documentación vigente y abrir el PR final hacia `main`.

Para el primer piloto remoto se prefiere una base central esquema 7 vacía porque
los datos actuales son de prueba. Antes de conectar una base con datos que deban
preservarse se requiere un traslado verificable y planificado; no se asume que el
bootstrap migre datos ni reconcilie cursores.

## Gates

- Ningún secreto, token, base o reporte pesado entra en Git.
- Ningún EA ni proceso remoto abre el archivo SQLite directamente.
- La indisponibilidad de la Mac no detiene MT5 ni descarta datos ya aceptados por
  el relay local.
- Un ACK local no se confunde con persistencia central confirmada.
- Toda escritura remota es idempotente y queda asociada a cuenta, fuente y versión
  de contrato.
- Despliegues, migraciones y activación de conectividad requieren aprobación
  humana y un camino de reversión.

## Pendientes preservados fuera del alcance inmediato

- [revisión completa de diseño y buenas prácticas Python](python-design-review-plan.md)
  en todo el proyecto (SOLID, DRY, YAGNI, encapsulamiento y patrones); no se limita
  a la revisión parcial de API y relay;

- activación definitiva y observación de los jobs automáticos en la VPS;
- comparación amplia de la base y la API contra reportes MT5;
- política definitiva de retención, backup externo y restauración;
- fórmulas financieras todavía sujetas a revisión del socio;
- definición de métricas de performance ejecutiva;
- pendientes visuales y operativos no relacionados con la extracción de la base.

Estos puntos no se consideran cancelados. Se retomarán cuando no interfieran con
el camino crítico de la plataforma remota o cuando el piloto aporte evidencia.

## Cierre y retorno a `main`

El PR final solo se abre cuando los incrementos estén integrados, CI esté verde,
el piloto funcione con interrupciones controladas y exista una revisión explícita
de seguridad y recuperación. Antes de ese PR se eliminan las reglas temporales de
`AGENTS.md` y de la bitácora, se conserva este documento como registro histórico y
se restaura `main` como única rama estable y único destino canónico de sesiones.

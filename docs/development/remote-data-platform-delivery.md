# Construcción de la plataforma de datos remota

**Estado:** programa aprobado; preparación de la rama de integración

**Rama estable temporal:** `feature/remote-data-platform`

**Base inicial:** `origin/main` en `ff3b864`

## Objetivo

Separar progresivamente la persistencia y la API de la VPS que ejecuta MT5 sin
arriesgar la captura ni desestabilizar `main`. El piloto alojará API, backend y
SQLite v5 en una Mac conectada privadamente con la VPS. La base permanecerá en
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

## Entregas previstas

Paso 1 preparado: [contrato central](../architecture/central-ingestion-api-contract.md)
y rutas `/docs` y `/docs.json` en ambos receptores. Pendiente revisión y merge.
El despliegue remoto permanece en los pasos siguientes.

1. **Contrato central y seguridad.** Delimitar ingesta v1/v2, ACK durable,
   autenticación por productor, límites y lecturas del dashboard. No exponer
   operaciones genéricas de baja o modificación a los collectors.
2. **Creación limpia de SQLite v5.** Proveer un comando portable que cree una base
   nueva, registre cuenta y fuentes, y nunca sobrescriba un destino existente.
3. **Relay y outbox durable.** Mantener los EAs en loopback y reenviar desde la VPS
   con idempotencia, reintentos, backoff y confirmación central.
4. **Servicio piloto en la Mac.** Ejecutar API y SQLite juntas, usar conectividad
   privada y evitar suspensión o exposición pública accidental.
5. **Validación extremo a extremo.** Probar cortes, reinicios, ACK perdido,
   duplicados, recuperación, atraso y reconciliación de conteos.
6. **Traslado verificable.** Separar migración de esquema de exportación/importación
   entre hosts mediante snapshot consistente, manifest, hash e integridad.
7. **Cierre del programa.** Revisar seguridad y robustez, retirar la excepción de
   ramas, actualizar documentación vigente y abrir el PR final hacia `main`.

Para el primer piloto se prefiere una base v5 vacía porque los datos actuales son
de prueba. La herramienta de traslado se implementará antes de conectar una base
que deba conservarse.

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

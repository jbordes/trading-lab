# Estándares de desarrollo de código

**Versión:** 0.1

**Estado:** Vigente desde Harness 0.1

## Objetivo

Estas reglas definen cómo construir scripts y aplicaciones mantenibles para TradingLab. Se aplican con proporcionalidad: una utilidad pequeña no necesita capas ceremoniales, pero ningún acceso a SQX, MT5, Google Drive, catálogo o filesystem debe quedar mezclado con la lógica de negocio.

## Estructura progresiva

Las rutas se crean cuando exista el primer componente real que las necesite:

```text
src/tradinglab/       lógica reutilizable del producto
scripts/              entradas operativas delgadas
tests/unit/           lógica aislada y determinista
tests/integration/    filesystem, procesos y adaptadores
tests/fixtures/       muestras mínimas, anonimizadas y versionables
```

Un archivo de `scripts/` interpreta argumentos, construye dependencias, llama un caso de uso y traduce el resultado a salida y código de retorno. La lógica reutilizable vive en `src/tradinglab/`; no se copia entre scripts.

## Arquitectura pragmática

La dirección conceptual es:

```text
CLI o automatización -> caso de uso -> lógica de dominio -> puertos
                                                     ^
                                                     |
                                  adaptadores de SQX, MT5, Drive,
                                  catálogo, procesos y filesystem
```

- La lógica de dominio no importa adaptadores concretos ni depende del directorio actual, red, reloj global o variables de entorno.
- Las dependencias externas se reciben mediante parámetros, funciones, protocolos o constructores. No se incorpora un contenedor de inyección hasta que exista una necesidad demostrada.
- Se crea una interfaz cuando separa una frontera externa, habilita una prueba relevante o existen implementaciones alternativas; no por cada clase.
- Se priorizan KISS y cohesión. DRY no justifica una abstracción prematura y SOLID no exige multiplicar capas o patrones.

## Legibilidad y tipos

- Usar nombres descriptivos, funciones enfocadas y retornos explícitos.
- Preferir `pathlib.Path`, tipos concretos y fechas con zona horaria.
- El código nuevo lleva anotaciones de tipos en sus interfaces públicas y lógica no trivial.
- Los comentarios explican motivos, invariantes o riesgos; no repiten el código.
- Ruff define el formato y las reglas estáticas comunes. No se deshabilita una regla sin una justificación localizada.

## Entradas, salidas y errores

- Tratar como no confiable todo archivo o mensaje procedente de SQX, MT5, Drive, usuarios o servicios externos.
- Validar formato, tamaño, identificadores, rutas y valores antes de operar.
- No aceptar recorridos que escapen de la raíz autorizada ni seguir destinos implícitos.
- Usar excepciones específicas dentro de la aplicación y convertirlas en mensajes y códigos de salida estables en la frontera.
- No ocultar errores con `except Exception` salvo en una frontera que registre el contexto seguro y preserve la causa.
- Los procesos externos tienen timeout, comprueban su código de salida y no construyen comandos de shell concatenando entradas.

## Operaciones con efectos

- Una operación repetida debe ser idempotente o detectar explícitamente el estado previo.
- No sobrescribir ni borrar silenciosamente. Las acciones sensibles ofrecen `--dry-run`, confirmación humana o una protección equivalente.
- Para archivos relevantes, escribir en un temporal dentro del mismo destino, validar y reemplazar de manera atómica cuando el sistema lo permita.
- Calcular y conservar SHA-256 en fronteras de ingestión y para artefactos que deban ser reproducibles.
- No mezclar una transformación pura con copia, publicación, despliegue o comunicación externa.

## Configuración y observabilidad

- Leer y validar configuración en un único punto de entrada; no dispersar accesos a variables de entorno.
- Separar configuración pública, rutas locales y secretos. Los secretos nunca aparecen en Git, errores, logs o fixtures.
- Los procesos relevantes propagan identificadores disponibles como `run_id`, `strategy_id`, `experiment_id` y hash del artefacto.
- Registrar inicio, resultado, duración y error útil sin volcar contenidos sensibles o archivos completos.
- Usar UTC para instantes internos y `Europe/Madrid` para la jornada y presentación humana cuando corresponda.

## Estrategia de pruebas

- Todo cambio de comportamiento incluye una prueba o explica en el PR por qué no es automatizable.
- Las pruebas unitarias cubren transformaciones, decisiones y errores sin red ni herramientas externas.
- Las pruebas de integración usan directorios temporales y dobles controlados para fronteras locales.
- Los fixtures son mínimos, anonimizados, con licencia compatible y sin credenciales ni resultados operativos masivos.
- Las pruebas E2E se reservan para flujos críticos ejecutables y se mantienen separadas de los checks rápidos.
- Las pruebas son deterministas: reloj, aleatoriedad, red y procesos externos se controlan explícitamente.

## Criterio de revisión

Antes del PR se comprueba que el cambio:

- mantiene la lógica fuera de entradas operativas;
- valida casos límite y entradas no confiables;
- contempla fallos parciales y repetición segura;
- incluye pruebas proporcionales al riesgo;
- no agrega abstracciones, dependencias o infraestructura sin una necesidad concreta;
- pasa `uv run python scripts/check.py full`.

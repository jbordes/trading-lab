# Bitácora de sesión — Revisión de arquitectura inicial

**Fecha:** 7 de octubre de 2026  
**Tema:** Análisis y revisión de arquitectura de TradingLab 2.0  
**Estado:** En curso; arquitectura 2.2, pipeline y MT5 Runner documentados, pendientes de validación

## Objetivo

Analizar el documento `Trading_Lab_2_0_Arquitectura_Inicial.pdf`, identificar fortalezas y riesgos, y preparar una segunda propuesta comparable antes de inicializar el repositorio Git.

## Material revisado

- `Trading_Lab_2_0_Arquitectura_Inicial.pdf` — 15 páginas.
- Estado del workspace: solo estaba presente el documento inicial; no existían todavía código, README, estructura de proyecto ni repositorio Git inicializado.

## Conclusiones del análisis

### Decisiones consideradas correctas

- Un único repositorio Git para todo TradingLab.
- Una base lógica central con separación mediante `project_id`.
- Distinción entre historial Git, experimentos en base de datos y contexto humano en reportes de sesión.
- Separación entre archivos reales y metadatos estructurados.
- Vinculación de resultados con commit, versión de datos, configuración y versión de motor.
- Codex como cliente del laboratorio y no como dependencia arquitectónica central.

### Riesgos detectados

- Ausencia de una capa explícita para datasets y artefactos pesados.
- Uso de rutas locales como referencia durable de artefactos.
- `git_commit` insuficiente para reproducir por sí solo una ejecución.
- Modelo genérico de métricas sin unidades, tipos, scopes ni versión de fórmula.
- Riesgo de convertir `Programming/` en un directorio sin fronteras claras.
- Posible duplicación entre documentación global, documentación de proyecto y reportes de sesión.
- Versionado amplio de PDFs/binarios poco adecuado para revisiones Git.
- MCP planteado antes de consolidar una API de dominio.
- Falta de procedimientos de seguridad, respaldo, restauración, pruebas e invalidación de resultados.

## Decisiones propuestas en la arquitectura v2

- Mantener monorepo y catálogo central.
- Usar rutas operativas en minúsculas y `kebab-case`.
- Organizar software por unidades: `apps/`, `packages/`, `db/`, `infra/` y `tools/`.
- Definir una matriz de fuentes de verdad.
- Introducir datasets versionados y storage separado de Git.
- Registrar artefactos por URI, SHA-256, tamaño, tipo y backend.
- Crear un manifiesto inmutable por run.
- Separar formalmente experimento y ejecución.
- Normalizar métricas con tipo, unidad, scope y versión de cálculo.
- Implementar primero un flujo vertical real MT5/SQX.
- Usar ADR para decisiones y bitácoras para historia de trabajo.
- Mantener MCP como adaptador sobre API/servicios tipados.

## Artefactos creados

- `docs/architecture/tradinglab-architecture-v2.md`
- `docs/architecture/tradinglab-architecture-v2.pdf`
- `docs/sessions/2026-10-07-architecture-review.md`

## Acciones no realizadas deliberadamente

- No se ejecutó `git init`.
- No se creó repositorio remoto.
- No se movió ni modificó el PDF original.
- No se eligió stack tecnológico para API o base de datos.

Estas acciones requieren primero validar la propuesta y, para GitHub, confirmar cuenta u organización, nombre, visibilidad y URL del remoto.

## Preguntas abiertas

1. ¿Cuál será la cuenta u organización propietaria en GitHub?
2. ¿El repositorio será privado o público?
3. ¿Se usará PostgreSQL desde el piloto?
4. ¿Dónde residirá y cómo se respaldará el storage inicial?
5. ¿Qué proyecto y reporte se utilizarán como primer flujo real?
6. ¿Qué política de ramas y revisiones se adoptará?
7. ¿Qué runtime se utilizará para API, CLI e importadores?

## Próximo paso acordado

Revisar el PDF de arquitectura v2 con los socios, registrar ajustes y, una vez aprobado, inicializar Git y configurar el repositorio remoto de GitHub.

## Continuación — Documentación explicativa

Antes de iniciar Git se solicitó ampliar la documentación para facilitar la revisión con los socios. Se acordó separar las explicaciones en dos documentos, evitando sobrecargar la arquitectura principal.

### Trabajo realizado

- Se documentó el propósito, contenido permitido, exclusiones y criterio de uso de cada directorio y archivo raíz.
- Se añadió una guía para decidir dónde ubicar nuevos elementos.
- Se distinguió la estructura mínima del piloto de la estructura futura.
- Se explicaron las decisiones no relacionadas directamente con carpetas: monorepo, catálogo, fuentes de verdad, modelo de dominio, datasets, manifiestos, métricas, artefactos, estados, API/MCP, seguridad, backups, observabilidad y pruebas.
- Se documentaron alternativas, consecuencias y condiciones de revisión de las decisiones principales.
- Se preparó un glosario para conversaciones con personas no involucradas en el diseño inicial.

### Nuevos artefactos

- `docs/architecture/repository-structure-guide.md`
- `docs/architecture/repository-structure-guide.pdf`
- `docs/architecture/architecture-decisions-guide.md`
- `docs/architecture/architecture-decisions-guide.pdf`

### Estado de Git

Git continúa sin inicializar. No se creó ni configuró ningún remoto.

### Próximo paso actualizado

Revisar conjuntamente la arquitectura v2 y sus dos documentos de apoyo. Incorporar correcciones, registrar la decisión de aprobación y solo después inicializar Git/GitHub.

## Continuación — Pipeline SQX → MT5 → Incubación

Se identificó que la arquitectura 2.0 no representaba de manera suficiente el proceso real mediante el cual una estrategia candidata de SQX se prepara, compila, valida, despliega e incuba en MT5. Tratar directamente una `StrategyVersion` como ejecutable habría dejado sin trazabilidad modificaciones de código, dependencias, versión de MetaEditor, preset y binario `.ex5`.

### Análisis realizado

- Se separó la identidad de la estrategia de la identidad del bot compilado.
- Se determinó que la exportación original de SQX debe conservarse sin modificaciones.
- Se definió que toda preparación debe provenir de una receta versionada o de cambios manuales revisables en Git.
- Se estableció que compilar correctamente no es suficiente: el bot debe superar gates técnicos y de equivalencia SQX/MT5.
- Se resolvió modelar la incubación como un experimento cuyos runs están vinculados a un deployment concreto.
- Se estableció que cambiar `.ex5` o preset durante una incubación requiere otro build, deployment o run.
- Se mantuvo la regla de no almacenar credenciales de MT5 ni ejecutables generados en Git.

### Decisiones incorporadas

- Nueva entidad `BotBuild` para identificar entradas, preparación, compilador, outputs, hashes y aprobación.
- Nueva entidad `Environment` para describir el contexto MT5 sin incluir secretos.
- Nueva entidad `Deployment` para vincular un build aprobado con entorno y configuración efectiva.
- Estados y gates explícitos para build, deployment e incubación.
- `packages/bot-pipeline/` como futura capacidad reutilizable.
- Subdirectorios de proyecto para configuraciones de estrategia, build e incubación, y para componentes SQX/MT5.
- Build manifest separado del run manifest.
- Política recomendada inicial de cero errores y cero warnings de compilación, pendiente de aprobación de socios.

### Documentos modificados

- `docs/architecture/tradinglab-architecture-v2.md` — actualizado de 2.0 a 2.1.
- `docs/architecture/repository-structure-guide.md` — actualizado de 1.0 a 1.1.
- `docs/architecture/architecture-decisions-guide.md` — actualizado de 1.0 a 1.1.

### Nuevo documento

- `docs/architecture/sqx-mt5-incubation-pipeline.md`
- `docs/architecture/sqx-mt5-incubation-pipeline.pdf`

El documento define etapas desde selección hasta cierre de incubación, gates G0–G6, manifests, estados, fuentes de verdad, catálogo, seguridad, rollback, roles, observabilidad y criterios de aceptación.

### Preguntas nuevas para socios

1. ¿Qué builds de SQX, MetaEditor y MT5 se admitirán inicialmente?
2. ¿Se aprobará una política estricta de cero warnings?
3. ¿Qué tolerancias definirán equivalencia aceptable entre SQX y MT5?
4. ¿Cuáles serán los límites de riesgo obligatorios antes de incubar?
5. ¿Cuál será el primer entorno MT5 de incubación?
6. ¿Qué gates requieren aprobación humana y quién puede desplegar?
7. ¿Qué duración y criterios determinarán el resultado de una incubación?

### Estado de Git

Git continúa sin inicializar. La validación documental sigue siendo el paso anterior a configurar el repositorio.

## Continuación — VPS MT5 aislada y TradingLab MT5 Runner

Se aclaró que TradingLab trabaja en una VPS con SQX y datos, mientras MT5 se ejecuta en otra VPS administrada por el socio. Por decisión de seguridad, TradingLab no tendrá acceso remoto a esa segunda VPS. Sí se permitirá ejecutar allí scripts creados por TradingLab para facilitar compilación, backtesting e incubación.

### Análisis realizado

- Se confirmó que el aislamiento es compatible con la arquitectura.
- Se descartó una rama Git permanente dedicada al servidor MT5 porque no constituye una frontera de seguridad, puede divergir y no representa una versión instalada.
- Se propuso `TradingLab MT5 Runner` como aplicación local, versionada y reversible.
- Se separaron cuatro artefactos: `RunnerRelease`, `JobPackage`, `Acknowledgement` y `EvidenceBundle`.
- Se decidió que Google Drive será el canal inicial de transporte, no la fuente de verdad ni autorización automática.
- Se estableció que los jobs serán declarativos y no permitirán shell o PowerShell arbitrario.
- Se mantuvo aprobación humana local para acciones sensibles durante las primeras etapas.
- Se definió una evolución desde operación manual hasta polling y automatización limitada por políticas.
- Se documentó como mejora futura el uso de releases inmutables y attestations de GitHub.

### Decisiones de arquitectura

- La VPS TradingLab no inicia conexiones administrativas hacia la VPS MT5.
- La VPS MT5 no tendrá inicialmente credenciales del monorepo principal.
- El runner se desarrolla en `main`, bajo `apps/mt5-runner/`.
- Los contratos compartidos viven en `packages/exchange-contracts/`.
- Los releases se comparten inicialmente mediante Google Drive y se verifican antes de instalar.
- Un archivo aparecido en Drive no se ejecuta automáticamente.
- El runner se ejecutará con privilegio mínimo y allowlist de acciones y rutas.
- TradingLab reconcilia cada evidencia con el job y asigna nivel de verificación.

### Documentos modificados

- `docs/architecture/tradinglab-architecture-v2.md` — actualizado de 2.1 a 2.2.
- `docs/architecture/sqx-mt5-incubation-pipeline.md` — actualizado de 1.0 a 1.1.
- `docs/architecture/repository-structure-guide.md` — actualizado de 1.1 a 1.2.
- `docs/architecture/architecture-decisions-guide.md` — actualizado de 1.1 a 1.2.

### Nuevo documento

- `docs/architecture/tradinglab-mt5-runner-workflow.md`
- `docs/architecture/tradinglab-mt5-runner-workflow.pdf`

El documento detalla construcción, revisión, publicación, instalación, rollback, creación y aprobación de jobs, ejecución, evidencia, reconciliación, seguridad, auditoría, fallos y evolución hacia GitHub.

### Decisiones pendientes

1. Runtime y lenguaje del runner.
2. Usuario Windows y permisos exactos.
3. Propietario y permisos de las carpetas de Google Drive.
4. Método local para almacenar credenciales de Drive.
5. Política de firma de scripts y paquetes.
6. Acciones que requerirán aprobación humana.
7. Frecuencia de polling cuando se automatice.
8. Retención de workspaces y evidencias en la VPS MT5.
9. Condiciones para adoptar releases inmutables de GitHub.

### Estado de Git

Git continúa sin inicializar. Los documentos dejan preparada la estrategia de distribución, pero no crean ramas, releases, credenciales ni repositorios remotos.

## Continuación — Inicialización de Git

Después de completar la documentación se autorizó inicializar el repositorio local y conectarlo con `https://github.com/jbordes/trading-lab.git`.

### Preparación realizada

- Se creó `README.md` como entrada al proyecto y mapa de la documentación vigente.
- Se creó `.gitignore` para excluir secretos, storage local, binarios MT4/MT5, logs, bases locales, cachés y archivos temporales.
- Se creó `.gitattributes` para normalizar finales de línea y marcar PDFs/binarios correctamente.
- Se ejecutó `git init -b main` y se creó el repositorio local con rama principal `main`.

### Bloqueos detectados

- La identidad Git global de la VPS pertenece a otra persona: `Nehuen Capuzzi <Nehuen.Capuzzi1999@gmail.com>`. No se utilizó para crear commits ni se modificó globalmente.
- El proceso aislado de Codex se ejecuta con un usuario diferente del propietario de la carpeta. Git exige declarar el directorio como seguro para ese usuario.
- Después de la inicialización, el sandbox permite leer `.git` pero no modificar su configuración. Por ese motivo no se pudo añadir `origin`, preparar el índice ni crear el primer commit desde esta sesión.
- La conexión HTTPS a GitHub no pudo autenticarse mediante el contexto Windows del sandbox. No se solicitaron ni almacenaron credenciales.

### Estado alcanzado

- Repositorio local creado.
- Rama `main` definida.
- Working tree todavía sin commit.
- Remoto `origin` todavía no configurado.
- Ningún dato enviado a GitHub.

### Próximo paso

Ejecutar desde el perfil Windows propietario una secuencia controlada para configurar identidad local, añadir `origin`, revisar archivos, crear el commit inicial y autenticar el primer push mediante Git Credential Manager o navegador.

## Cierre — Configuración y primer push de Git

Los pasos pendientes se ejecutaron desde el perfil Windows propietario de la VPS y la inicialización del repositorio quedó completada.

### Resultado verificado

- Identidad local del repositorio: `Juan Pablo Bordes <juanpablo.bordes@gmail.com>`.
- Remoto `origin`: `https://github.com/jbordes/trading-lab.git`.
- Rama principal: `main`.
- Commit inicial: `ddaf250` (`chore: initialize TradingLab 2.0`).
- La referencia local `origin/main` apunta al mismo commit que `main`.
- El commit contiene el documento original, la arquitectura 2.2, las guías de apoyo, el pipeline SQX–MT5, el workflow de TradingLab MT5 Runner y esta bitácora.
- El árbol de trabajo quedó limpio después del primer push.

### Consideraciones operativas

- Se mantiene HTTPS con el administrador de credenciales del perfil Windows; no es necesario migrar a SSH mientras este mecanismo resulte adecuado.
- Las credenciales no se almacenan en el repositorio ni se comparten con TradingLab o Codex.
- Fuera de esta VPS, el propietario trabaja habitualmente desde macOS/Unix. Cada equipo utilizará sus propias credenciales y nunca se copiarán claves privadas entre máquinas.
- La actualización de esta sección queda pendiente de un segundo commit para conservar en la bitácora el cierre de la inicialización.

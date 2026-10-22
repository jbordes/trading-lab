# Separación de responsabilidades de los collectors MT5

Fecha: 2026-10-22. Estado: propuesta para revisión, sin implementación ni cambios
en terminales. Base inspeccionada: `cf24fa4` (PR #26).

## Objetivo y despliegue

Separar la captura rápida de estado de la recuperación de actividad histórica,
para reducir trabajo repetido y permitir frecuencias distintas. Se puede pilotar
en la terminal demo actual: cada collector ocuparía su propio gráfico, junto a
los EAs de trading existentes. Una terminal observadora adicional, conectada a
la misma cuenta con acceso de inversor, es una opción futura de despliegue y no
un prerrequisito. No se modifica la terminal del socio.

La terminal observadora recibiría información de cuenta, no los logs, inputs ni
estado interno de EAs ejecutados en otra terminal. Múltiples terminales de trading
comparten cuenta, margen y operaciones; separar procesos no separa riesgo.
Magic Number identifica la estrategia dentro del alcance de cuenta, no concede
exclusividad de acceso a sus órdenes.

## Evidencia en el código actual

- `TradingLabTelemetry.mq5`: `BuildSnapshot` reúne cuenta, posiciones, órdenes
  pendientes e historial de deals en cada captura. `HistorySelect` relee una
  ventana acotada, hasta 200 deals. No captura historial de órdenes canceladas.
- `OnTradeTransaction` marca actividad; captura y envío ocurren en `OnTimer`.
  El intervalo permitido es 2..60 segundos, por defecto cinco.
- La guarda exige timeout HTTP de al menos 500 ms y como máximo un cuarto del
  intervalo. Admitir un segundo requiere revisar ambas restricciones, no solo
  reducir el mínimo del intervalo.
- El contrato v1 admite `account_snapshot` y `heartbeat`; no admite un mensaje
  autónomo de historial. El historial es opcional dentro del snapshot.
- SQLite registra fuentes asociadas a cuentas, pero `PersistentTelemetryReceiver`
  autoriza una única fuente por instancia y la vista actual selecciona snapshots
  de una fuente. Registrar dos fuentes no compone automáticamente sus datos.
- El backend del dashboard consulta por defecto cada cinco segundos, mínimo dos.
  La latencia total incluye captura, entrega, proyección y actualización del navegador.

## Separación propuesta

| Collector | Responsabilidad exclusiva | Frecuencia candidata |
| --- | --- | --- |
| Estado vivo | Balance, equity, flotante, margen, posiciones y órdenes pendientes actuales | Inicialmente 2 segundos; evaluar 1 segundo con mediciones |
| Actividad | Deals y órdenes históricas, incluidos estados cancelado/expirado; recuperar y reconciliar historial | Eventos agrupados y consulta periódica de respaldo; barridos más amplios menos frecuentes |

El diagnóstico permanece integrado en cada collector: versión, última captura,
entrega, errores, descartes y retraso. No hace falta un tercer EA para informar
su propia salud. Un observador externo sería otro caso de uso.

La responsabilidad se divide por semántica, coste y recuperación, no por símbolo
o Magic Number: ambos collectors cubren la cuenta; el dashboard filtra por bot.
Compartir transporte, guardas y serialización mediante módulos MQL5 comunes y
entradas pequeñas evita mantener dos copias divergentes del collector completo.
Las colas y el estado de ejecución pertenecen a cada instancia.

## Contratos e identidad antes de implementar

La definición inicial queda en el [contrato v2 propuesto](telemetry-v2-contract.md)
y [ADR-0011](../adr/0011-separate-telemetry-streams.md), con ejemplos sintéticos y
escenarios de aceptación. El próximo paso ejecutable es validar esos mensajes
en un módulo aislado antes de conectarlos al receptor.

Proponer una versión de contrato que distinga estado vivo de lotes de actividad.
Conservar v1 durante la transición. Definir esquema y compatibilidad mediante ADR
antes de desarrollar; este análisis no fija todavía nombres de campos públicos.

- Cuenta: identidad interna provisionada, no deducida del login enmascarado.
- Fuente: instancia productora con identidad propia y rol autorizado. Dos
  collectors no reutilizan `source_id`, sesión ni secuencia.
- Mensaje: deduplicación por fuente/sesión/secuencia y control de contenido.
- Registro histórico: identidad por cuenta, tipo de entidad y ticket. Una orden
  y un deal no comparten identidad aunque coincidan sus números. Reenvíos y
  correcciones deben conservar trazabilidad sin duplicar métricas.
- Cada lote declara rango, completitud, truncamiento, errores y tiempos de
  captura/recepción. Tiempo del broker conserva su semántica hasta validarlo.

Evolucionar el receptor local hacia una lista explícita de fuentes y roles
autorizados por cuenta; no aceptar cualquier fuente declarada por el emisor.
Evaluar credencial por productor y comprobar su rol antes de ingerir. Mantener
un servicio y un escritor SQLite controlado, sin introducir varios receptores
competidores ni nuevos microservicios para el piloto.

## Composición y recuperación

El backend compone la vista de cuenta a partir del último estado vivo válido y
de la actividad reconciliada. Un lote histórico nunca reemplaza equity o balance.
Cada flujo conserva frescura, cobertura y errores propios; no presentar la
composición como una observación atómica tomada en un único instante.

Durante una interrupción, estado vivo prioriza recuperar la muestra reciente.
Actividad prioriza reconstruir el rango faltante con solapamiento y deduplicación.
Los callbacks de transacciones marcan trabajo pendiente; no realizan HTTP ni un
barrido completo. La reconciliación sigue siendo necesaria aunque haya eventos.
No avanzar cobertura confirmada por un lote fallido o truncado. Si se llena la
ventana, dividir la recuperación en lotes acotados antes de declarar completitud.
La garantía depende también de cuánto historial conserve y entregue el broker.

No se promete conservar cada muestra de equity: reemplazar muestras pendientes
afecta la evidencia de extremos intrasegundo. Definir con el socio precisión de
drawdown y retención antes de usar esa serie para métricas de riesgo.

## Rendimiento y límites

Separar EAs aísla sus manejadores, pero comparten terminal, CPU, conexión al broker
y backend. Un historial pesado todavía puede competir por recursos. Medir carga,
bytes por mensaje, crecimiento de SQLite, demora de captura a recepción y demora
hasta visualización (mediana y percentiles altos), además de cobertura recuperada.

Una frecuencia de un segundo es un objetivo de actualización, no una garantía de
tiempo real ni de detección de todos los extremos. No persistir una copia de todo
el historial cada segundo. SSE puede reducir el retraso servidor-navegador, pero
no acelera una captura vieja: decidirlo después de medir el flujo completo.

## Pasos pequeños y criterios de aceptación

1. Aprobar contrato e identidades en un ADR propuesto; fixtures para ambos flujos,
   incluido un caso de orden cancelada sin deal. Acordar objetivo de frescura y
   precisión de métricas por separado.
2. Implementar admisión y composición en backend con fixtures: desorden de llegada,
   duplicados, correcciones, reinicio, fuente/rol incorrectos y flujo ausente.
   El estado vivo debe continuar actualizándose si actividad falla.
3. Extraer módulos comunes y crear los dos collectors. Validar guardas demo,
   límites, recuperación y compatibilidad antes de instalarlos.
4. Prueba supervisada en la terminal actual, con instalación autorizada y rollback
   al collector único. Usar fuentes piloto explícitas; no mezclar productores
   viejos/nuevos en una misma identidad. Contrastar con MT5 operaciones reales.
5. Ajustar captura y dashboard hacia un segundo si las mediciones lo justifican.
   Evaluar SSE y persistencia de muestras según resultados, sin prometer latencia
   de extremo a extremo antes de medirla.

No requiere una terminal extra, una base nueva ni cambiar definiciones de métricas.
Las modificaciones de esquema o migraciones se diseñarán y aprobarán por separado.

## Referencias

- [Arquitectura vigente](tradinglab-architecture-v2.md).
- [Roadmap del dashboard](../development/live-risk-dashboard-roadmap.md).
- [Acceso de inversor en MT5](https://www.metatrader5.com/en/terminal/help/startworking/authorization).
- [Eventos de transacciones](https://www.mql5.com/en/docs/event_handlers/ontradetransaction).
- [Temporizadores y descarte de eventos superpuestos](https://www.mql5.com/en/docs/event_handlers/ontimer).

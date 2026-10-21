# ADR-0010: Separar la autenticación humana de la telemetría

**Estado:** accepted

**Fecha:** 2026-10-21

## Contexto

El collector MT5 y el receptor usan un token para autenticar la entrega de
telemetría. El dashboard consultaba ese receptor en el servidor, sin entregar el
token al navegador, pero su interfaz y `/api/state` no exigían autenticación al
usuario. Reutilizar el secreto del EA en el navegador mezclaría identidades,
ampliaría su exposición y obligaría a rotar la captura para revocar un acceso
humano.

El piloto continúa enlazado exclusivamente a `127.0.0.1`. La autenticación local
no autoriza por sí sola una exposición en LAN o Internet, donde también se
requieren TLS y una decisión explícita de despliegue.

## Alternativas consideradas

1. Reutilizar el token de telemetría para acceder al dashboard.
2. Proteger la interfaz con HTTP Basic usando una credencial separada.
3. Usar un token humano separado para crear una sesión opaca, temporal y
   revocable en memoria.
4. Incorporar ahora usuarios persistentes, contraseñas y un proveedor de identidad.

## Decisión

Se adopta la tercera alternativa. `TRADINGLAB_TELEMETRY_TOKEN` conserva
exclusivamente el flujo EA-receptor-dashboard del lado servidor.
`TRADINGLAB_DASHBOARD_TOKEN`, necesariamente distinto, autentica al operador en
`/login`. El token se envía en el cuerpo de un formulario local y se intercambia
por una cookie de sesión aleatoria, `HttpOnly`, `SameSite=Strict`, con duración
máxima de doce horas. Las sesiones viven únicamente en memoria, tienen cantidad
acotada, expiran y pueden revocarse mediante logout o reinicio.

La portada y los assets de presentación permanecen públicos. `/dashboard` y
`/api/state` requieren sesión. `/health` publica únicamente el estado mínimo para
operación local. El servidor acepta solo autoridades `localhost` y `127.0.0.1`
acordes a su puerto para reducir el riesgo de DNS rebinding.

## Consecuencias

Arrancar el conjunto requiere dos secretos diferentes. Rotar o revocar el acceso
al dashboard no obliga a reconfigurar el EA. Reiniciar el servidor cierra todas
las sesiones, y ninguna credencial ni sesión se persiste en Git o SQLite.

La cookie no lleva `Secure` porque el piloto usa HTTP sobre loopback. Antes de
publicar por red se deberá terminar TLS en una frontera aprobada, habilitar
cookies seguras, definir rate limiting y decidir si el login local se conserva o
se reemplaza por identidad multiusuario. Este ADR no autoriza acceso remoto.

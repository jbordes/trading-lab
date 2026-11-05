# ADR-0019: Preparación portable y acceso privado al host de datos

**Estado:** accepted

**Fecha:** 2026-11-05

## Contexto

El piloto API/SQLite funciona en la VPS; se prepara una Mac como primer host
remoto, manteniendo MT5 y el relay locales. Se requiere el mismo procedimiento
para macOS, Linux y Windows y que la Mac no inicie conexiones hacia la VPS.

## Alternativas consideradas

1. Publicar Uvicorn directamente: amplía exposición y obliga a gestionar TLS.
2. Túneles SSH: viables, pero añaden servicio, claves y supervisión de túneles.
3. API loopback con Tailscale Serve HTTPS privado y política direccional mínima.

## Decisión

Preparar directorios nuevos fuera de Git mediante un núcleo Python y wrappers
de bootstrap por sistema. Instalar dependencias locked con uv/Python 3.14;
crear SQLite v1 y v2/esquema 5, registrar identidades y generar credenciales
separadas sin imprimirlas. Proteger el directorio y publicar `host.json` al
final. No sobrescribir, migrar, borrar ni iniciar servicios automáticamente.

Mantener Uvicorn en `127.0.0.1`; admitir opcionalmente un Host DNS Tailscale
exacto para el proxy, sin comodines ni cambio de bind. Configurar Tailscale,
HTTPS y permisos manualmente, con revisión humana: solo `tag:tl-vps` puede
iniciar TCP/443 hacia `tag:tl-api`. Las respuestas pertenecen a esa conexión;
no se autoriza una conexión nueva inversa. No habilitar Funnel, rutas de
subred, exit nodes ni SSH como parte de este piloto.

## Consecuencias

- La política requiere eliminar permisos amplios preexistentes; las reglas
  permisivas se suman, no se anulan con otra regla más específica. No aplicar
  esta política a una tailnet usada para administración sin revisarla primero.
- No es un diodo ni una garantía de aislamiento total: no cubre conexiones
  por la IP pública/LAN y un destino remoto malicioso sigue respondiendo a la
  VPS. Los controles locales y del proveedor deben mantenerse.
- Tailscale Serve termina TLS y no reemplaza los tokens y permisos de la API.
  No se confía en cabeceras de proxy de forma implícita.
- La instalación nativa y el enlace remoto requieren validación supervisada.
  Los scripts y tests locales no demuestran un despliegue real en la Mac.
- La base nueva no reinicia cursores de MT5. El cambio de target del relay,
  las colas vinculadas al destino y el backfill requieren un corte planificado.
- No sustituye el módulo futuro de administración de credenciales, los jobs
  permanentes ni una exportación/importación consistente de datos.

## Referencias

- [Manual de preparación](../development/remote-host-setup.md).
- [Grants de Tailscale](https://tailscale.com/docs/reference/syntax/grants).
- [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve).

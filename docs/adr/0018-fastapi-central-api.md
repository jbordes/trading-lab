# ADR-0018: FastAPI y OpenAPI para la API central

**Estado:** accepted

**Fecha:** 2026-11-04

## Contexto

La API central del programa remoto requiere un contrato navegable y verificable,
modelos explícitos, credenciales separadas y evolución de endpoints. Los primeros
receptores usan handlers manuales y un catálogo propio que no es OpenAPI.

## Alternativas consideradas

1. Ampliar los handlers y mantener OpenAPI manualmente: menos dependencias, más
   lógica HTTP y riesgo de divergencia entre documentación y servidor.
2. Usar FastAPI como adaptador, con OpenAPI y modelos Pydantic explícitos, sobre
   admisión, persistencia y cálculos existentes.

## Decisión

Adoptar FastAPI/Uvicorn para una API central optativa. Publicar `/openapi.json`,
Swagger UI `/docs` y ReDoc `/redoc`. Reutilizar los validadores de dominio para
JSON estricto, correlaciones entre campos, tiempos, roles e idempotencia. Los
modelos estructurales de OpenAPI se validan también durante la ingesta; el cuerpo
se lee con límites antes de procesarlo. No introducir un ORM ni alterar fórmulas.

Conservar inicialmente rutas v1/v2 y confirmaciones 200/202 por compatibilidad
con los EAs y el relay. Los contratos pueden evolucionar explícitamente; esos
códigos no son una restricción impuesta por MT5. La nueva API convierte fallos de
validación a 400 sin reflejar cuerpos sensibles en errores.

Separar transporte y validación del ACK del coordinador del relay mediante un
protocolo inyectable. Extraer esquema y migraciones SQLite del registro operativo
y compartir consultas/presentación v2 entre adaptadores HTTP.

## Consecuencias

- Nuevas dependencias fijadas por `uv.lock`, con pruebas de contrato y portabilidad.
- Un proceso de API, SQLite local a ese backend y operaciones síncronas fuera del
  event loop durante las solicitudes. No duplicar workers del relay en la API.
- Los receptores anteriores continúan disponibles; la sustitución operativa
  requiere un piloto y configuración explícita.
- La UI de documentación predeterminada usa assets CDN del framework; su acceso
  requiere Internet. No persiste autorización entre recargas ni envía el contrato
  a un validador externo. Autohospedar esos assets y restringir documentación en
  despliegues posteriores son decisiones operativas pendientes, no capacidades
  offline que ya existan.
- La auditoría completa de diseño Python permanece pendiente y separada de esta entrega.

## Reemplaza

No reemplaza la decisión de relay del ADR-0017. Amplía su implementación central
y distingue la documentación OpenAPI de los catálogos locales anteriores.

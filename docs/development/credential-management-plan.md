# Próximo paso: gestión centralizada de credenciales y permisos

Estado: pendiente; acordado el 2026-11-04. No implementado en esta entrega.

Centralizar reglas y administración en un módulo Python independiente de FastAPI.
No crear un servicio separado ni usar una credencial global.

## Primera entrega propuesta

- Identificar cliente, cuenta, fuente y permisos: ingesta live, activity o lectura.
- Generar tokens opacos con `secrets.token_urlsafe(32)`; verificar sus huellas
  SHA-256 mediante comparación de tiempo constante. SHA-256 se aplica a tokens
  aleatorios de alta entropía, nunca a contraseñas humanas.
- Registrar identificador, hash, propietario, permisos, creación, vencimiento
  opcional y revocación; no guardar tokens recibidos en texto claro ni en logs.
- CLI local para emitir, listar metadatos, revocar y rotar. Entrega del valor
  original explícita y controlada, no salida rutinaria ni argumento de proceso.
- Transición desde credenciales actuales sin perder pendientes. Probar permisos,
  expiración, revocación y rotación. Mantener separados EA, relay y sesión humana.

El cliente necesita conservar el token original que presenta. El hashing del
receptor no sustituye archivos privados, protección del equipo ni TLS/transporte
privado remoto. Ignorar un archivo en Git no lo cifra.

## Fuera del primer alcance

- Contraseñas humanas: evaluar Argon2id con `argon2-cffi` al incorporar usuarios.
- JWT/PyJWT: no introducir tokens autocontenidos sin necesidad demostrada.
- `cryptography`: solo para una necesidad concreta de cifrado o firma.
- No mezclar accesos con el esquema histórico SQLite v5 sin definir antes su
  persistencia y ciclo de vida.

Esta tarea sigue a la conexión local dashboard/API. No sustituye las pruebas del
relay ni la preparación del transporte a la Mac.

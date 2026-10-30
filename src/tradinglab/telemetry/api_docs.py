"""Static developer reference served without touching telemetry or credentials."""

from __future__ import annotations

import json
from html import escape
from http.server import BaseHTTPRequestHandler


def api_catalog(version: str) -> dict[str, object]:
    """Describe implemented receiver routes, separate from the planned remote transport."""
    if version not in {"v1", "v2"}:
        raise ValueError("Unsupported receiver version")
    common = [
        ("GET", "/health", "Sin token", "Salud del receptor; no demuestra cobertura completa."),
        ("GET", "/docs", "Sin token", "Referencia navegable, sin datos de cuenta."),
        ("GET", "/docs.json", "Sin token", "Este catálogo JSON; no es OpenAPI."),
        (
            "POST",
            f"/{version}/telemetry",
            "Bearer del productor",
            "JSON UTF-8, Content-Length único, máximo 256 KiB (o límite configurado menor). "
            "202: aceptado; 200: duplicado idéntico. No cambiar identidad al reintentar.",
        ),
    ]
    routes = (
        [
            ("GET", "/v1/snapshot", "Bearer v1", "source_id obligatorio. Última muestra viva."),
            (
                "GET",
                "/v1/deals",
                "Bearer v1",
                "source_id, from_msc, to_msc obligatorios; "
                "magic_number, limit (1..100), cursor opcionales. Requiere persistencia.",
            ),
            (
                "GET",
                "/v1/account-history",
                "Bearer v1",
                "source_id, from_msc, to_msc "
                "obligatorios. Hasta 366 días y 480 puntos; requiere persistencia.",
            ),
        ]
        if version == "v1"
        else [
            (
                "GET",
                "/v2/activity",
                "Bearer de lectura",
                "entity=deal|order, from_msc, "
                "to_msc obligatorios; magic_number, limit (1..100), cursor opcionales. "
                "Respuesta: items, next_cursor, coverage.",
            ),
            (
                "GET",
                "/v2/activity-progress",
                "Bearer de lectura",
                "Sin parámetros. "
                "activity_progress puede ser null; progreso no equivale a cobertura.",
            ),
            (
                "GET",
                "/v2/position-cycles",
                "Bearer de lectura",
                "Opcionales: owner_magic "
                "o owner_magics (CSV hasta 12), from_msc y to_msc juntos, closed_only=true|false, "
                "order=asc|desc, include_details=true|false, limit (1..100), cursor. "
                "Respuesta: items y next_cursor. Un ciclo agrupa cuenta y posición; "
                "eligible_for_autonomous_metrics determina elegibilidad.",
            ),
            (
                "GET",
                "/v2/position-cycle-magics",
                "Bearer de lectura",
                "Sin parámetros. Respuesta: magics, hasta 100 identificadores.",
            ),
        ]
    )
    query = (
        "/v1/snapshot?source_id=demo-terminal-01"
        if version == "v1"
        else "/v2/activity?entity=deal&from_msc=1792886400000&to_msc=1792972800000&limit=50"
    )
    port = 8776 if version == "v1" else 8777
    return {
        "title": f"TradingLab — receptor {version}",
        "scope": "API local implementada. El transporte central remoto todavía está pendiente.",
        "authentication": "Bearer en Authorization, nunca en la URL. En v2 la credencial de "
        "lectura es distinta de las credenciales live/activity. Provisionar fuentes antes de enviar.",
        "conventions": "Consultas temporales [from_msc, to_msc); conservar la escala MT5. "
        "Reutilizar next_cursor sin modificarlo ni cambiar filtros. Tickets y Magic son texto. "
        "captured_at es UTC; los tiempos históricos MT5 no deben convertirse suponiendo un offset.",
        "durability": "V2 confirma después del commit SQLite. V1 solo garantiza persistencia "
        "en modo SQLite, no en modo memoria. Un ACK local no implica un ACK central remoto.",
        "errors": "400: solicitud inválida; 401: credencial inválida; 403: fuente no autorizada; "
        "409: conflicto de identidad/secuencia (requiere revisión); 413: cuerpo excesivo; "
        "415: Content-Type incorrecto; 503: almacenamiento no disponible. "
        "Ante timeout o 503, reintentar el mismo mensaje con backoff; no avanzar el cursor.",
        "routes": [
            dict(zip(("method", "path", "auth", "usage"), row, strict=True))
            for row in common + routes
        ],
        "examples": [
            f'curl "http://127.0.0.1:{port}{query}" -H "Authorization: Bearer <TOKEN_LECTURA>"',
            f'curl "http://127.0.0.1:{port}/{version}/telemetry" '
            '-H "Authorization: Bearer <TOKEN_PRODUCTOR>" '
            '-H "Content-Type: application/json" --data-binary @mensaje.json',
        ],
        "message_help": "mensaje.json debe contener un mensaje del collector de la misma "
        "versión. V2 exige schema_version, collector_version, source_id, session_id, sequence, "
        "event_id=session_id:sequence, captured_at, kind y payload. "
        "El payload depende del tipo: live_snapshot, activity_batch o heartbeat. "
        "position_reconcile es un reason de activity_batch, no un kind independiente. "
        "Ver docs/architecture/telemetry-v2-contract.md y tests/fixtures/telemetry_v2/ "
        "para cuerpos sintéticos completos. No enviar fixtures a una cuenta operativa.",
    }


def render_api_docs(catalog: dict[str, object]) -> bytes:
    """Render only static catalog values; never interpolate request headers or URLs."""
    sections = "".join(
        f"<p>{escape(str(catalog[key]))}</p>"
        for key in ("scope", "authentication", "conventions", "durability", "errors")
    )
    routes = "".join(
        f'<section id="route-{index}"><h2>{escape(route["method"])} '
        f"{escape(route['path'])}</h2><p>{escape(route['auth'])}</p>"
        f"<p>{escape(route['usage'])}</p></section>"
        for index, route in enumerate(catalog["routes"])
    )
    nav = " · ".join(
        f'<a href="#route-{index}">{escape(route["path"])}</a>'
        for index, route in enumerate(catalog["routes"])
    )
    examples = "".join(f"<pre>{escape(example)}</pre>" for example in catalog["examples"])
    return (
        '<!doctype html><html lang="es"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(str(catalog['title']))}</title><style>"
        "body{font:16px/1.55 system-ui;max-width:960px;margin:auto;padding:24px;"
        "color:#223039;background:#f5f7f8}section{border-top:1px solid #ccd4da;padding:12px 0}"
        "h2{font-size:18px}pre{overflow:auto;padding:16px;background:#e6edf1;font-size:13px}"
        "a{color:#23577b}nav{line-height:2} @media(prefers-color-scheme:dark){"
        "body{color:#dfe7ed;background:#182127}pre{background:#24343e}a{color:#a4d0ed}}"
        "</style><main>"
        f"<h1>{escape(str(catalog['title']))}</h1>{sections}<nav>{nav}</nav>{routes}"
        f"<h2>Ejemplos curl</h2>{examples}<p>{escape(str(catalog['message_help']))}</p>"
        "<p>Reemplazar los marcadores localmente. No hay consola de ejecución ni se guardan tokens.</p>"
        '<a href="/docs.json">Descargar catálogo JSON</a></main></html>'
    ).encode()


def serve_api_docs(handler: BaseHTTPRequestHandler, path: str, version: str) -> bool:
    """Serve exact static routes; no query strings or backend access."""
    if path not in {"/docs", "/docs.json"}:
        return False
    catalog = api_catalog(version)
    html = path == "/docs"
    data = (
        render_api_docs(catalog)
        if html
        else json.dumps(catalog, ensure_ascii=False).encode("utf-8")
    )
    handler.close_connection = True
    handler.send_response(200)
    handler.send_header(
        "Content-Type", ("text/html" if html else "application/json") + "; charset=utf-8"
    )
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header(
        "Content-Security-Policy",
        "default-src 'none'; style-src 'unsafe-inline'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    )
    handler.end_headers()
    handler.wfile.write(data)
    return True

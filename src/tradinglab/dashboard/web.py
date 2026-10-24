"""Dependency-free localhost HTTP boundary for the live dashboard."""

from __future__ import annotations

import gzip
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs

from tradinglab.dashboard.auth import SESSION_COOKIE, DashboardAuth
from tradinglab.dashboard.service import LiveDashboardService
from tradinglab.dashboard.snapshot import DashboardReadError
from tradinglab.dashboard.telemetry import TelemetryDealPage
from tradinglab.telemetry.http_server import BoundedHTTPServer

STATIC_ROOT = Path(__file__).with_name("static")
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/login": ("login.html", "text/html; charset=utf-8"),
    "/dashboard": ("dashboard.html", "text/html; charset=utf-8"),
    "/dashboard/": ("dashboard.html", "text/html; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/theme.js": ("theme.js", "text/javascript; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/assets/nav-icons.svg": ("nav-icons.svg", "image/svg+xml"),
    "/assets/logo_black.png": ("logo_black.png", "image/png"),
    "/assets/logo_white.png": ("logo_white.png", "image/png"),
    "/assets/favicon-black.ico": ("favicon-black.ico", "image/x-icon"),
    "/assets/favicon-white.ico": ("favicon-white.ico", "image/x-icon"),
    "/favicon.ico": ("favicon-black.ico", "image/x-icon"),
    "/assets/tradinglab-favicon-black-32.png": ("tradinglab-favicon-black-32.png", "image/png"),
    "/assets/tradinglab-favicon-white-32.png": ("tradinglab-favicon-white-32.png", "image/png"),
    "/assets/tradinglab-apple-touch-icon-black.png": (
        "tradinglab-apple-touch-icon-black.png",
        "image/png",
    ),
    "/assets/tradinglab-apple-touch-icon-white.png": (
        "tradinglab-apple-touch-icon-white.png",
        "image/png",
    ),
}

_STATIC_CACHE: dict[str, tuple[int, int, bytes, str]] = {}


class DealHistoryProvider(Protocol):
    def deal_history(
        self,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TelemetryDealPage: ...


def _read_static(filename: str) -> tuple[bytes, str]:
    """Read a static file from disk, caching bytes and a size+mtime ETag."""
    path = STATIC_ROOT / filename
    stat = path.stat()
    cached = _STATIC_CACHE.get(filename)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2], cached[3]
    data = path.read_bytes()
    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    _STATIC_CACHE[filename] = (stat.st_mtime_ns, stat.st_size, data, etag)
    return data, etag


def create_server(
    service: LiveDashboardService,
    *,
    port: int,
    dashboard_token: str,
    history_provider: DealHistoryProvider | None = None,
    max_connections: int = 16,
    request_timeout: float = 5.0,
) -> BoundedHTTPServer:
    """Create an authenticated server bound exclusively to IPv4 loopback."""

    if not 0 <= port <= 65535:
        raise ValueError("Puerto fuera de rango")
    if (
        isinstance(max_connections, bool)
        or not isinstance(max_connections, int)
        or not 1 <= max_connections <= 32
    ):
        raise ValueError("max_connections debe ser 1..32")
    if (
        isinstance(request_timeout, bool)
        or not isinstance(request_timeout, (int, float))
        or not 0.05 <= request_timeout <= 30
    ):
        raise ValueError("request_timeout debe ser 0.05..30 segundos")
    auth = DashboardAuth(dashboard_token)

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "TradingLabDashboard/0.1"
        protocol_version = "HTTP/1.1"

        def handle(self) -> None:
            try:
                super().handle()
            except TimeoutError, ConnectionError, OSError:
                # Browser disconnects and controlled shutdowns are normal network events.
                self.close_connection = True

        def do_GET(self) -> None:  # noqa: N802
            if not self._valid_host():
                self._send_json(
                    {"error": "host_not_allowed"}, status=HTTPStatus.MISDIRECTED_REQUEST
                )
                return
            path, _, raw_query = self.path.partition("?")
            query = parse_qs(raw_query)
            session = self._authorized_session()
            if path == "/login":
                if session is not None:
                    self._send_redirect("/dashboard")
                else:
                    self._send_login()
                return
            if path == "/api/state":
                if session is None:
                    self._send_json(
                        {"error": "authentication_required"}, status=HTTPStatus.UNAUTHORIZED
                    )
                    return
                since = (query.get("since") or [None])[0]
                try:
                    state = service.state(history_since=since)
                except ValueError:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Parámetro since inválido")
                    return
                self._send_json(state)
                return
            if path == "/api/deals":
                if session is None:
                    self._send_json(
                        {"error": "authentication_required"}, status=HTTPStatus.UNAUTHORIZED
                    )
                    return
                if history_provider is None:
                    self._send_json({"error": "history_unavailable"}, status=HTTPStatus.NOT_FOUND)
                    return
                try:
                    history_query = self._history_query(raw_query)
                    page = history_provider.deal_history(**history_query)
                except ValueError:
                    self._send_json(
                        {"error": "invalid_history_query"}, status=HTTPStatus.BAD_REQUEST
                    )
                    return
                except DashboardReadError:
                    self._send_json(
                        {"error": "history_unavailable"},
                        status=HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                self._send_json(page.as_dict())
                return
            if path == "/health":
                state = service.state()
                self._send_json({"status": state["status"]})
                return
            static = STATIC_ROUTES.get(path)
            if static:
                if path in {"/dashboard", "/dashboard/"} and session is None:
                    self._send_redirect("/login")
                    return
                filename, content_type = static
                data, etag = _read_static(filename)
                if self.headers.get("If-None-Match") == etag:
                    self._send_not_modified(etag)
                    return
                self._send_bytes(data, content_type, etag=etag, cache_control="no-cache")
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_HEAD(self) -> None:  # noqa: N802
            if not self._valid_host():
                self._send_json(
                    {"error": "host_not_allowed"}, status=HTTPStatus.MISDIRECTED_REQUEST
                )
                return
            path = self.path.split("?", 1)[0]
            session = self._authorized_session()
            if path == "/login" and session is not None:
                self._send_redirect("/dashboard")
                return
            if path in {"/dashboard", "/dashboard/"} and session is None:
                self._send_redirect("/login")
                return
            static = STATIC_ROUTES.get(path)
            if not static:
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
                return
            filename, content_type = static
            data, etag = _read_static(filename)
            self._send_bytes(
                data, content_type, etag=etag, cache_control="no-cache", head_only=True
            )

        def do_POST(self) -> None:  # noqa: N802
            if not self._valid_host():
                self._send_json(
                    {"error": "host_not_allowed"}, status=HTTPStatus.MISDIRECTED_REQUEST
                )
                return
            path = self.path.split("?", 1)[0]
            if path == "/login":
                self._handle_login()
                return
            if path == "/logout":
                if not self._empty_post_body():
                    self._send_json(
                        {"error": "invalid_logout_request"}, status=HTTPStatus.BAD_REQUEST
                    )
                    return
                session = self._authorized_session()
                if session is None:
                    self._send_redirect("/login", clear_cookie=True)
                    return
                auth.logout(session)
                self._send_redirect("/login", clear_cookie=True)
                return
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Dashboard de solo lectura")

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _send_json(self, payload: object, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            self._send_bytes(data, "application/json; charset=utf-8", status=status)

        def _handle_login(self) -> None:
            content_types = self.headers.get_all("Content-Type", failobj=[])
            lengths = self.headers.get_all("Content-Length", failobj=[])
            if (
                len(content_types) != 1
                or content_types[0].split(";", 1)[0].strip().lower()
                != "application/x-www-form-urlencoded"
                or len(lengths) != 1
                or self.headers.get("Transfer-Encoding") is not None
            ):
                self._send_json({"error": "invalid_login_request"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                length = int(lengths[0])
            except ValueError:
                length = -1
            if not 0 <= length <= 4096:
                self._send_json({"error": "invalid_login_request"}, status=HTTPStatus.BAD_REQUEST)
                return
            body = self.rfile.read(length)
            if len(body) != length:
                self._send_json({"error": "invalid_login_request"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                fields = parse_qs(
                    body.decode("utf-8"),
                    keep_blank_values=True,
                    strict_parsing=True,
                    max_num_fields=2,
                )
            except UnicodeError, ValueError:
                self._send_json({"error": "invalid_login_request"}, status=HTTPStatus.BAD_REQUEST)
                return
            if set(fields) != {"token"} or len(fields["token"]) != 1:
                self._send_json({"error": "invalid_login_request"}, status=HTTPStatus.BAD_REQUEST)
                return
            session = auth.login(fields["token"][0])
            if session is None:
                self._send_login(invalid=True)
                return
            self._send_redirect("/dashboard", session=session)

        def _send_login(self, *, invalid: bool = False) -> None:
            data, etag = _read_static("login.html")
            message = (
                '<p class="login-error" role="alert">El token no es válido.</p>'.encode()
                if invalid
                else b""
            )
            data = data.replace(b"<!--LOGIN_ERROR-->", message)
            self._send_bytes(
                data,
                "text/html; charset=utf-8",
                etag=etag,
                status=HTTPStatus.UNAUTHORIZED if invalid else HTTPStatus.OK,
            )

        def _send_redirect(
            self,
            location: str,
            *,
            session: str | None = None,
            clear_cookie: bool = False,
        ) -> None:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            if session is not None:
                self.send_header(
                    "Set-Cookie",
                    f"{SESSION_COOKIE}={session}; Path=/; HttpOnly; SameSite=Strict; "
                    f"Max-Age={auth.session_seconds}",
                )
            elif clear_cookie:
                self.send_header(
                    "Set-Cookie",
                    f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0",
                )
            self.end_headers()

        def _authorized_session(self) -> str | None:
            cookies = self.headers.get_all("Cookie", failobj=[])
            if len(cookies) > 1:
                return None
            return auth.authorized_session(cookies[0] if cookies else None)

        def _valid_host(self) -> bool:
            hosts = self.headers.get_all("Host", failobj=[])
            if len(hosts) != 1:
                return False
            authority = hosts[0].strip().lower()
            port = self.server.server_port
            return authority in {
                "127.0.0.1",
                "localhost",
                f"127.0.0.1:{port}",
                f"localhost:{port}",
            }

        def _empty_post_body(self) -> bool:
            if self.headers.get("Transfer-Encoding") is not None:
                return False
            lengths = self.headers.get_all("Content-Length", failobj=[])
            return not lengths or (len(lengths) == 1 and lengths[0] == "0")

        @staticmethod
        def _history_query(raw_query: str) -> dict[str, Any]:
            values = parse_qs(
                raw_query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=5,
            )
            required = {"from_msc", "to_msc"}
            allowed = required | {"magic_number", "limit", "cursor"}
            if not required <= set(values) or not set(values) <= allowed:
                raise ValueError("Parámetros históricos inválidos")
            if any(len(items) != 1 for items in values.values()):
                raise ValueError("Parámetros históricos repetidos")

            def integer(name: str, default: str | None = None) -> int:
                value = values.get(name, [default])[0]
                if value is None or not value.isascii() or not value.isdecimal():
                    raise ValueError("Entero histórico inválido")
                parsed = int(value)
                if str(parsed) != value:
                    raise ValueError("Entero histórico inválido")
                return parsed

            from_msc = integer("from_msc")
            to_msc = integer("to_msc")
            limit = integer("limit", "50")
            if not 0 <= from_msc < to_msc < 2**63 or not 1 <= limit <= 100:
                raise ValueError("Límites históricos inválidos")
            return {
                "from_msc": from_msc,
                "to_msc": to_msc,
                "magic_number": values.get("magic_number", [None])[0],
                "limit": limit,
                "cursor": values.get("cursor", [None])[0],
            }

        def _send_not_modified(self, etag: str) -> None:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Vary", "Accept-Encoding")
            self.end_headers()

        def _send_bytes(
            self,
            data: bytes,
            content_type: str,
            *,
            etag: str | None = None,
            cache_control: str = "no-store",
            head_only: bool = False,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            self.send_response(status)
            accept_encoding = self.headers.get("Accept-Encoding", "")
            if len(data) > 1024 and "gzip" in accept_encoding:
                compressed = gzip.compress(data)
                if len(compressed) < len(data):
                    data = compressed
                    self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache_control)
            self.send_header("Vary", "Accept-Encoding")
            if etag:
                self.send_header("ETag", etag)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
                "script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            if not head_only:
                self.wfile.write(data)

    return BoundedHTTPServer(
        ("127.0.0.1", port),
        DashboardHandler,
        max_connections=max_connections,
        request_timeout=float(request_timeout),
    )

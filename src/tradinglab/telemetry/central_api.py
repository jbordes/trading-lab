"""Opt-in central FastAPI adapter over existing durable receivers."""

from __future__ import annotations

import hmac
import re
import sqlite3
from contextlib import ExitStack, asynccontextmanager, closing
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import anyio
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tradinglab.telemetry import api_models as m
from tradinglab.telemetry.admission_v2 import (
    V2AuthenticationError,
    V2AuthorizationError,
    V2ConflictError,
    V2StaleSequenceError,
)
from tradinglab.telemetry.central_schema import validate_central_schema
from tradinglab.telemetry.contract import MAX_BODY_BYTES, TelemetryValidationError, parse_envelope
from tradinglab.telemetry.contract_v2 import parse_envelope_v2
from tradinglab.telemetry.http_contracts_v2 import (
    parse_activity_query,
    parse_position_cycles_query,
    position_cycle_item,
)
from tradinglab.telemetry.persistent_receiver import PersistentTelemetryReceiver
from tradinglab.telemetry.persistent_receiver_v2 import PersistentV2TelemetryReceiver
from tradinglab.telemetry.sqlite_store import (
    DealHistoryCursor,
    MessageAdmissionError,
    MessageConflictError,
    MessageStaleError,
    TelemetryStorageError,
)
from tradinglab.telemetry.sqlite_store_v2 import V2StorageError

_SNAPSHOT_PRODUCER = HTTPBearer(auto_error=False, scheme_name="AccountStateProducer")
_EVENTS_PRODUCER = HTTPBearer(auto_error=False, scheme_name="TradingEventsProducer")
_ACCOUNT_READER = HTTPBearer(auto_error=False, scheme_name="AccountRead")
_TRADING_READER = HTTPBearer(auto_error=False, scheme_name="TradingRead")


def _origin_key(value: str) -> tuple[str, str, int]:
    """Parse a single canonical HTTP(S) origin, never a URL with extra components."""
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 2048
        or any(not 33 <= ord(character) <= 126 for character in value)
    ):
        raise ValueError("Origen inválido")
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    port = parsed.port
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not host
        or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        )
        or (port is not None and not 1 <= port <= 65535)
        or value != f"{parsed.scheme}://{host}{f':{port}' if port is not None else ''}"
    ):
        raise ValueError("Origen inválido")
    return (
        parsed.scheme,
        host,
        port if port is not None else (443 if parsed.scheme == "https" else 80),
    )


@dataclass(frozen=True)
class CentralSettings:
    database: Path
    source_id: str
    account_id: str
    snapshot_ingest: str = field(repr=False)
    account_read: str = field(repr=False)
    live_ingest: str = field(repr=False)
    activity_ingest: str = field(repr=False)
    trading_read: str = field(repr=False)
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")
    public_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        keys = (
            self.snapshot_ingest,
            self.account_read,
            self.live_ingest,
            self.activity_ingest,
            self.trading_read,
        )
        if any(
            not isinstance(key, str)
            or not 24 <= len(key) <= 256
            or not key.isascii()
            or any(not 33 <= ord(c) <= 126 for c in key)
            for key in keys
        ):
            raise ValueError("Credenciales centrales inválidas")
        if len(set(keys)) != len(keys):
            raise ValueError("Cada productor y lectura requiere una credencial distinta")
        if not self.allowed_hosts or any(
            not host or "*" in host or "/" in host for host in self.allowed_hosts
        ):
            raise ValueError("Configure hosts explícitos")
        if not isinstance(self.public_origins, tuple) or len(self.public_origins) > 16:
            raise ValueError("Configure una lista acotada de orígenes públicos explícitos")
        origins = tuple(_origin_key(origin) for origin in self.public_origins)
        if len(set(origins)) != len(origins) or any(
            scheme != "https" or host not in self.allowed_hosts for scheme, host, _ in origins
        ):
            raise ValueError(
                "Orígenes públicos HTTPS únicos y asociados a hosts permitidos requeridos"
            )


@dataclass(frozen=True)
class CentralServices:
    account_state: PersistentTelemetryReceiver
    trading_events: PersistentV2TelemetryReceiver


def _single_query(request: Request, allowed: set[str]) -> None:
    pairs = request.query_params.multi_items()
    if len({key for key, _ in pairs}) != len(pairs) or any(key not in allowed for key, _ in pairs):
        raise ValueError("Consulta inválida")


def create_central_app(settings: CentralSettings) -> FastAPI:
    public_origins = frozenset(_origin_key(origin) for origin in settings.public_origins)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = settings.database.resolve(strict=True)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as registry:
            validate_central_schema(registry)
            source = registry.execute(
                "SELECT account_id, role FROM sources WHERE source_id = ?",
                (settings.source_id,),
            ).fetchone()
            if source != (settings.account_id, "snapshot"):
                raise ValueError("La fuente de telemetría no corresponde a la cuenta central")
        with ExitStack() as stack:
            v1 = PersistentTelemetryReceiver(settings.database, source_id=settings.source_id)
            stack.callback(v1.close)
            v2 = PersistentV2TelemetryReceiver(
                settings.database,
                account_id=settings.account_id,
                live_authorization=settings.live_ingest,
                activity_authorization=settings.activity_ingest,
            )
            stack.callback(v2.close)
            app.state.services = CentralServices(v1, v2)
            try:
                yield
            finally:
                del app.state.services

    app = FastAPI(
        title="TradingLab Central API",
        version="0.2.0",
        lifespan=lifespan,
        swagger_ui_parameters={"persistAuthorization": False, "validatorUrl": None},
        description="API optativa con SQLite durable. Captura UTC y tiempos MT5 se conservan por separado.",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    errors = {
        code: {"model": m.ApiError} for code in (400, 401, 403, 408, 409, 411, 413, 415, 500, 503)
    }

    def services(request: Request) -> CentralServices:
        return request.app.state.services

    def authorize(request: Request, keys: tuple[str, ...]) -> str:
        values = request.headers.getlist("authorization")
        if len(values) != 1 or not values[0].isascii():
            raise HTTPException(401, "unauthorized")
        matches = [hmac.compare_digest(values[0], f"Bearer {key}") for key in keys]
        if not any(matches):
            raise HTTPException(401, "unauthorized")
        return values[0]

    def account_read(
        request: Request,
        credential: Annotated[HTTPAuthorizationCredentials | None, Depends(_ACCOUNT_READER)],
    ) -> None:
        authorize(request, (settings.account_read,))

    def trading_read(
        request: Request,
        credential: Annotated[HTTPAuthorizationCredentials | None, Depends(_TRADING_READER)],
    ) -> None:
        authorize(request, (settings.trading_read,))

    @app.middleware("http")
    async def safe_headers(request: Request, call_next):
        origins = request.headers.getlist("origin")
        hosts = request.headers.getlist("host")
        if len(hosts) != 1:
            response = JSONResponse({"error": "invalid_host"}, status_code=400)
        elif origins:
            try:
                if len(origins) != 1:
                    raise ValueError("Orígenes duplicados")
                origin = _origin_key(origins[0])
                same_origin = _origin_key(f"{request.url.scheme}://{hosts[0]}")
                local_same_origin = origin == same_origin and origin[1] in {
                    "127.0.0.1",
                    "localhost",
                }
                if not local_same_origin and origin not in public_origins:
                    raise ValueError("Origen no permitido")
            except ValueError:
                response = JSONResponse({"error": "origin_not_allowed"}, status_code=403)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            }
        )
        return response

    async def error_response(request: Request, exc: Exception):
        mapping = {
            V2AuthenticationError: (401, "unauthorized"),
            V2AuthorizationError: (403, "source_not_allowed"),
            MessageAdmissionError: (403, "source_not_allowed"),
            V2ConflictError: (409, "idempotency_conflict"),
            MessageConflictError: (409, "idempotency_conflict"),
            V2StaleSequenceError: (409, "stale_sequence"),
            MessageStaleError: (409, "stale_sequence"),
            TelemetryValidationError: (400, "invalid_message"),
            V2StorageError: (503, "storage_unavailable"),
            TelemetryStorageError: (503, "storage_unavailable"),
            ResponseValidationError: (500, "invalid_response"),
        }
        status, error = mapping.get(
            type(exc),
            next(
                (value for kind, value in mapping.items() if isinstance(exc, kind)),
                (400, "invalid_query"),
            ),
        )
        return JSONResponse({"error": error}, status_code=status)

    for kind in (
        V2AuthenticationError,
        V2AuthorizationError,
        MessageAdmissionError,
        V2ConflictError,
        MessageConflictError,
        V2StaleSequenceError,
        MessageStaleError,
        TelemetryValidationError,
        V2StorageError,
        TelemetryStorageError,
        RequestValidationError,
        ResponseValidationError,
    ):
        app.add_exception_handler(kind, error_response)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = (
            exc.detail if isinstance(exc.detail, str) and len(exc.detail) < 80 else "http_error"
        )
        return JSONResponse({"error": detail}, status_code=exc.status_code)

    async def body(request: Request) -> bytes:
        lengths = request.headers.getlist("content-length")
        if request.headers.getlist("transfer-encoding") or len(lengths) > 1:
            raise HTTPException(400, "ambiguous_framing")
        try:
            length = int(lengths[0]) if lengths else 0
        except ValueError:
            length = 0
        if length < 1:
            raise HTTPException(411, "content_length")
        if length > MAX_BODY_BYTES:
            raise HTTPException(413, "too_large")
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            raise HTTPException(415, "content_type")
        data = bytearray()
        try:
            with anyio.fail_after(5):
                async for chunk in request.stream():
                    data.extend(chunk)
                    if len(data) > MAX_BODY_BYTES:
                        raise HTTPException(413, "too_large")
        except TimeoutError:
            raise HTTPException(408, "request_timeout") from None
        if len(data) != length:
            raise HTTPException(400, "incomplete_body")
        return bytes(data)

    schemas = {}

    def request_schema(adapter, example):
        schema = adapter.json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(schema.pop("$defs", {}))
        return {
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": schema, "example": example}},
            }
        }

    @app.post(
        "/api/account-state",
        tags=["Ingesta"],
        status_code=202,
        response_model=m.AccountStateAck,
        responses={**errors, 200: {"model": m.AccountStateAck}},
        openapi_extra=request_schema(m.ACCOUNT_STATE_REQUEST, m.EXAMPLE_ACCOUNT_STATE),
    )
    async def ingest_account_state(
        request: Request,
        response: Response,
        credential: Annotated[HTTPAuthorizationCredentials | None, Depends(_SNAPSHOT_PRODUCER)],
    ):
        authorize(request, (settings.snapshot_ingest,))
        if request.query_params:
            raise HTTPException(400, "invalid_query")
        raw = await body(request)
        envelope = parse_envelope(raw)
        try:
            m.ACCOUNT_STATE_REQUEST.validate_python(envelope.as_dict())
        except ValidationError:
            raise HTTPException(400, "invalid_message") from None
        result = await anyio.to_thread.run_sync(services(request).account_state.accept, envelope)
        response.status_code = 200 if result.status == "duplicate" else 202
        return m.AccountStateAck(status=result.status, sequence_gap=result.sequence_gap)

    @app.post(
        "/api/trading-events",
        tags=["Ingesta"],
        status_code=202,
        response_model=m.TradingEventsAck,
        responses={**errors, 200: {"model": m.TradingEventsAck}},
        openapi_extra=request_schema(m.TRADING_EVENTS_REQUEST, m.EXAMPLE_TRADING_EVENTS),
    )
    async def ingest_trading_events(
        request: Request,
        response: Response,
        credential: Annotated[HTTPAuthorizationCredentials | None, Depends(_EVENTS_PRODUCER)],
    ):
        authorization = authorize(request, (settings.live_ingest, settings.activity_ingest))
        if request.query_params:
            raise HTTPException(400, "invalid_query")
        raw = await body(request)
        envelope = parse_envelope_v2(raw)
        try:
            m.TRADING_EVENTS_REQUEST.validate_python(envelope.as_dict())
        except ValidationError:
            raise HTTPException(400, "invalid_message") from None
        result = await anyio.to_thread.run_sync(
            services(request).trading_events._accept_validated, envelope, authorization
        )
        response.status_code = 200 if result.disposition.value == "duplicate" else 202
        return m.TradingEventsAck(
            status=result.disposition.value,
            sequence_gap=result.sequence_gap,
            out_of_order=result.out_of_order,
        )

    @app.get("/health", response_model=m.Health, tags=["Operación"], responses=errors)
    def health(request: Request):
        current = services(request)
        current.account_state.state(include_latest=False)
        current.trading_events.state()
        return m.Health(
            status="ready",
            storage="sqlite",
            services={"account_state": "ready", "trading_events": "ready"},
        )

    @app.get(
        "/api/accounts/health",
        response_model=m.AccountStateHealth,
        dependencies=[Depends(account_read)],
        tags=["Estado de cuenta"],
        responses=errors,
    )
    def account_health(request: Request):
        if request.query_params:
            raise HTTPException(400, "invalid_query")
        return services(request).account_state.state(include_latest=False)

    @app.get(
        "/api/accounts/snapshot",
        response_model=m.AccountStateSnapshot,
        response_model_exclude_unset=True,
        dependencies=[Depends(account_read)],
        tags=["Estado de cuenta"],
        responses={**errors, 404: {"model": m.ApiError}},
    )
    def snapshot(request: Request, source_id: str):
        try:
            _single_query(request, {"source_id"})
            result = services(request).account_state.latest_account_snapshot(source_id)
        except ValueError:
            raise HTTPException(400, "invalid_source") from None
        if result is None:
            raise HTTPException(404, "snapshot_unavailable")
        return result

    def integer(value: str) -> int:
        if not value.isascii() or not value.isdecimal() or str(int(value)) != value:
            raise ValueError("Entero canónico requerido")
        return int(value)

    @app.get(
        "/api/accounts/deals",
        response_model=m.DealPage,
        dependencies=[Depends(account_read)],
        tags=["Estado de cuenta"],
        responses=errors,
    )
    def deals(
        request: Request,
        source_id: str,
        from_msc: str,
        to_msc: str,
        magic_number: str | None = None,
        limit: str = "50",
        cursor: str | None = None,
    ):
        try:
            _single_query(
                request, {"source_id", "from_msc", "to_msc", "magic_number", "limit", "cursor"}
            )
            start, end = integer(from_msc), integer(to_msc)
            page = services(request).account_state.deal_history(
                source_id,
                from_msc=start,
                to_msc=end,
                magic_number=magic_number,
                limit=integer(limit),
                cursor=DealHistoryCursor.decode(cursor) if cursor is not None else None,
            )
        except ValueError:
            raise HTTPException(400, "invalid_history_query") from None
        return {
            "account_id": page.account_id,
            "source_id": source_id,
            "from_msc": start,
            "to_msc": end,
            "magic_number": magic_number,
            "deals": [deal.as_dict() for deal in page.deals],
            "next_cursor": page.next_cursor.encode() if page.next_cursor else None,
        }

    @app.get(
        "/api/accounts/history",
        response_model=m.AccountHistory,
        dependencies=[Depends(account_read)],
        tags=["Estado de cuenta"],
        responses=errors,
    )
    def account_history(request: Request, source_id: str, from_msc: str, to_msc: str):
        try:
            _single_query(request, {"source_id", "from_msc", "to_msc"})
            return services(request).account_state.account_history(
                source_id, from_msc=integer(from_msc), to_msc=integer(to_msc)
            )
        except ValueError:
            raise HTTPException(400, "invalid_history_query") from None

    @app.get(
        "/api/trading/activity",
        response_model=m.ActivityPage,
        dependencies=[Depends(trading_read)],
        tags=["Actividad de trading"],
        responses=errors,
    )
    def activity(
        request: Request,
        entity: Literal["deal", "order"],
        from_msc: str,
        to_msc: str,
        magic_number: str | None = None,
        limit: str = "50",
        cursor: str | None = None,
    ):
        try:
            query = parse_activity_query(request.url.query)
            page, coverage = services(request).trading_events.activity_history(**query)
        except ValueError:
            raise HTTPException(400, "invalid_activity_query") from None
        return {
            "account_id": page.account_id,
            "entity_type": page.entity_type,
            "from_msc": query["from_msc"],
            "to_msc": query["to_msc"],
            "magic_number": query["magic_number"],
            "items": [asdict(item) for item in page.items],
            "next_cursor": page.next_cursor,
            "coverage": {
                "complete_ranges": [
                    {"from_msc": start, "to_msc": end} for start, end in coverage.complete_ranges
                ],
                "incomplete_batches": coverage.incomplete_batches,
            },
        }

    @app.get(
        "/api/trading/activity-progress",
        response_model=m.ProgressResponse,
        dependencies=[Depends(trading_read)],
        response_model_exclude_unset=True,
        tags=["Actividad de trading"],
        responses=errors,
    )
    def progress(request: Request):
        if request.query_params:
            raise HTTPException(400, "invalid_query")
        result = services(request).trading_events.activity_progress()
        return {"activity_progress": asdict(result) if result else None}

    @app.get(
        "/api/trading/position-cycle-magics",
        response_model=m.Magics,
        dependencies=[Depends(trading_read)],
        tags=["Actividad de trading"],
        responses=errors,
    )
    def magics(request: Request):
        if request.query_params:
            raise HTTPException(400, "invalid_query")
        return {"magics": list(services(request).trading_events.position_cycle_magics())}

    @app.get(
        "/api/trading/position-cycles",
        response_model=m.CyclePage,
        dependencies=[Depends(trading_read)],
        tags=["Actividad de trading"],
        responses=errors,
    )
    def cycles(
        request: Request,
        owner_magic: str | None = None,
        owner_magics: str | None = None,
        from_msc: str | None = None,
        to_msc: str | None = None,
        closed_only: Literal["true", "false"] = "false",
        order: Literal["asc", "desc"] = "desc",
        include_details: Literal["true", "false"] = "true",
        limit: str = "50",
        cursor: str | None = None,
    ):
        try:
            query = parse_position_cycles_query(request.url.query)
            page = services(request).trading_events.position_cycles(**query)
        except ValueError:
            raise HTTPException(400, "invalid_position_cycles_query") from None
        return jsonable_encoder(
            {
                "account_id": page.account_id,
                "owner_magic": page.owner_magic,
                "items": [position_cycle_item(item) for item in page.items],
                "next_cursor": page.next_cursor,
            }
        )

    def openapi():
        if app.openapi_schema is None:
            document = get_openapi(
                title=app.title, version=app.version, routes=app.routes, description=app.description
            )
            document.setdefault("components", {}).setdefault("schemas", {}).update(schemas)
            for operations in document["paths"].values():
                for operation in operations.values():
                    if isinstance(operation, dict):
                        operation.get("responses", {}).pop("422", None)
            app.openapi_schema = document
        return app.openapi_schema

    app.openapi = openapi
    return app

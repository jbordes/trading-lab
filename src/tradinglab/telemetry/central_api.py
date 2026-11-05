"""Opt-in central FastAPI adapter over existing durable receivers."""

from __future__ import annotations

import hmac
import sqlite3
from contextlib import ExitStack, asynccontextmanager, closing
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Annotated, Literal

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

_V1_PRODUCER = HTTPBearer(auto_error=False, scheme_name="V1Producer")
_V2_PRODUCER = HTTPBearer(auto_error=False, scheme_name="V2Producer")
_V1_READER = HTTPBearer(auto_error=False, scheme_name="V1Read")
_V2_READER = HTTPBearer(auto_error=False, scheme_name="V2Read")


@dataclass(frozen=True)
class CentralSettings:
    database: Path
    source_id: str
    account_id: str
    v1_ingest: str = field(repr=False)
    v1_read: str = field(repr=False)
    v2_live: str = field(repr=False)
    v2_activity: str = field(repr=False)
    v2_read: str = field(repr=False)
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")

    def __post_init__(self) -> None:
        keys = (self.v1_ingest, self.v1_read, self.v2_live, self.v2_activity, self.v2_read)
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


@dataclass(frozen=True)
class CentralServices:
    v1: PersistentTelemetryReceiver
    v2: PersistentV2TelemetryReceiver


def _single_query(request: Request, allowed: set[str]) -> None:
    pairs = request.query_params.multi_items()
    if len({key for key, _ in pairs}) != len(pairs) or any(key not in allowed for key, _ in pairs):
        raise ValueError("Consulta inválida")


def create_central_app(settings: CentralSettings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = settings.database.resolve(strict=True)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as registry:
            validate_central_schema(registry)
            source = registry.execute(
                "SELECT account_id, role FROM sources WHERE source_id = ?",
                (settings.source_id,),
            ).fetchone()
            if source != (settings.account_id, "telemetry-v1"):
                raise ValueError("La fuente de telemetría no corresponde a la cuenta central")
        with ExitStack() as stack:
            v1 = PersistentTelemetryReceiver(settings.database, source_id=settings.source_id)
            stack.callback(v1.close)
            v2 = PersistentV2TelemetryReceiver(
                settings.database,
                account_id=settings.account_id,
                live_authorization=settings.v2_live,
                activity_authorization=settings.v2_activity,
            )
            stack.callback(v2.close)
            app.state.services = CentralServices(v1, v2)
            try:
                yield
            finally:
                del app.state.services

    app = FastAPI(
        title="TradingLab Central API",
        version="0.1.0",
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

    def read1(
        request: Request,
        credential: Annotated[HTTPAuthorizationCredentials | None, Depends(_V1_READER)],
    ) -> None:
        authorize(request, (settings.v1_read,))

    def read2(
        request: Request,
        credential: Annotated[HTTPAuthorizationCredentials | None, Depends(_V2_READER)],
    ) -> None:
        authorize(request, (settings.v2_read,))

    @app.middleware("http")
    async def safe_headers(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host', '')}":
            return JSONResponse({"error": "origin_not_allowed"}, status_code=403)
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
        "/v1/telemetry",
        tags=["Ingesta"],
        status_code=202,
        response_model=m.AckV1,
        responses={**errors, 200: {"model": m.AckV1}},
        openapi_extra=request_schema(m.V1_REQUEST, m.EXAMPLE_V1),
    )
    async def ingest1(
        request: Request,
        response: Response,
        credential: Annotated[HTTPAuthorizationCredentials | None, Depends(_V1_PRODUCER)],
    ):
        authorize(request, (settings.v1_ingest,))
        if request.query_params:
            raise HTTPException(400, "invalid_query")
        raw = await body(request)
        envelope = parse_envelope(raw)
        try:
            m.V1_REQUEST.validate_python(envelope.as_dict())
        except ValidationError:
            raise HTTPException(400, "invalid_message") from None
        result = await anyio.to_thread.run_sync(services(request).v1.accept, envelope)
        response.status_code = 200 if result.status == "duplicate" else 202
        return m.AckV1(status=result.status, sequence_gap=result.sequence_gap)

    @app.post(
        "/v2/telemetry",
        tags=["Ingesta"],
        status_code=202,
        response_model=m.AckV2,
        responses={**errors, 200: {"model": m.AckV2}},
        openapi_extra=request_schema(m.V2_REQUEST, m.EXAMPLE_V2),
    )
    async def ingest2(
        request: Request,
        response: Response,
        credential: Annotated[HTTPAuthorizationCredentials | None, Depends(_V2_PRODUCER)],
    ):
        authorization = authorize(request, (settings.v2_live, settings.v2_activity))
        if request.query_params:
            raise HTTPException(400, "invalid_query")
        raw = await body(request)
        envelope = parse_envelope_v2(raw)
        try:
            m.V2_REQUEST.validate_python(envelope.as_dict())
        except ValidationError:
            raise HTTPException(400, "invalid_message") from None
        result = await anyio.to_thread.run_sync(services(request).v2.accept, raw, authorization)
        response.status_code = 200 if result.disposition.value == "duplicate" else 202
        return m.AckV2(
            status=result.disposition.value,
            sequence_gap=result.sequence_gap,
            out_of_order=result.out_of_order,
        )

    @app.get("/health", response_model=m.Health, tags=["Operación"], responses=errors)
    def health(request: Request):
        current = services(request)
        current.v1.state(include_latest=False)
        current.v2.state()
        return m.Health(status="ready", storage="sqlite", services={"v1": "ready", "v2": "ready"})

    @app.get(
        "/v1/health",
        response_model=m.V1Health,
        dependencies=[Depends(read1)],
        tags=["Lecturas v1"],
        responses=errors,
    )
    def v1_health(request: Request):
        if request.query_params:
            raise HTTPException(400, "invalid_query")
        return services(request).v1.state(include_latest=False)

    @app.get(
        "/v1/snapshot",
        response_model=m.V1Snapshot,
        response_model_exclude_unset=True,
        dependencies=[Depends(read1)],
        tags=["Lecturas v1"],
        responses={**errors, 404: {"model": m.ApiError}},
    )
    def snapshot(request: Request, source_id: str):
        try:
            _single_query(request, {"source_id"})
            result = services(request).v1.latest_account_snapshot(source_id)
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
        "/v1/deals",
        response_model=m.V1DealPage,
        dependencies=[Depends(read1)],
        tags=["Lecturas v1"],
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
            page = services(request).v1.deal_history(
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
        "/v1/account-history",
        response_model=m.AccountHistory,
        dependencies=[Depends(read1)],
        tags=["Lecturas v1"],
        responses=errors,
    )
    def account_history(request: Request, source_id: str, from_msc: str, to_msc: str):
        try:
            _single_query(request, {"source_id", "from_msc", "to_msc"})
            return services(request).v1.account_history(
                source_id, from_msc=integer(from_msc), to_msc=integer(to_msc)
            )
        except ValueError:
            raise HTTPException(400, "invalid_history_query") from None

    @app.get(
        "/v2/activity",
        response_model=m.ActivityPage,
        dependencies=[Depends(read2)],
        tags=["Lecturas v2"],
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
            page, coverage = services(request).v2.activity_history(**query)
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
        "/v2/activity-progress",
        response_model=m.ProgressResponse,
        dependencies=[Depends(read2)],
        response_model_exclude_unset=True,
        tags=["Lecturas v2"],
        responses=errors,
    )
    def progress(request: Request):
        if request.query_params:
            raise HTTPException(400, "invalid_query")
        result = services(request).v2.activity_progress()
        return {"activity_progress": asdict(result) if result else None}

    @app.get(
        "/v2/position-cycle-magics",
        response_model=m.Magics,
        dependencies=[Depends(read2)],
        tags=["Lecturas v2"],
        responses=errors,
    )
    def magics(request: Request):
        if request.query_params:
            raise HTTPException(400, "invalid_query")
        return {"magics": list(services(request).v2.position_cycle_magics())}

    @app.get(
        "/v2/position-cycles",
        response_model=m.CyclePage,
        dependencies=[Depends(read2)],
        tags=["Lecturas v2"],
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
            page = services(request).v2.position_cycles(**query)
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

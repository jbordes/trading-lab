"""Read the validated loopback telemetry projection into dashboard snapshots."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Protocol

from tradinglab.dashboard.snapshot import (
    DashboardReadError,
    LiveSnapshot,
    OperationSnapshot,
    ReceiverHealth,
    SourceHealth,
    utc_iso,
)
from tradinglab.telemetry.contract import (
    DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS,
    IDENTIFIER,
    MAX_BODY_BYTES,
    TelemetryEnvelope,
    TelemetryValidationError,
    parse_envelope,
)

TELEMETRY_TOKEN_ENV = "TRADINGLAB_TELEMETRY_TOKEN"
_POSITION_TYPES = {0: "buy", 1: "sell"}
_ORDER_TYPES = {
    0: "buy",
    1: "sell",
    2: "buy_limit",
    3: "sell_limit",
    4: "buy_stop",
    5: "sell_stop",
    6: "buy_stop_limit",
    7: "sell_stop_limit",
    8: "close_by",
}


class TelemetrySnapshotClient(Protocol):
    """Small read-only boundary used by the telemetry dashboard adapter."""

    def latest(self) -> TelemetryEnvelope: ...

    def health(self) -> ReceiverHealth: ...


_COUNTER_FIELDS = ("accepted", "duplicates", "missing_sequences", "retained", "retained_sessions")
_HISTORY_STATUSES = {"complete", "truncated", "error", "unavailable"}


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Turn every redirect into an HTTPError without issuing a second request."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


class LoopbackTelemetryClient:
    """Fetch the newest snapshot from the authenticated loopback receiver."""

    def __init__(
        self,
        *,
        token: str,
        source_id: str,
        port: int = 8766,
        timeout_seconds: float = 2.0,
    ) -> None:
        if len(token) < 24 or not token.isascii() or any(not 33 <= ord(c) <= 126 for c in token):
            raise ValueError("El token de telemetría no cumple el formato requerido")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("El puerto de telemetría está fuera de rango")
        if not IDENTIFIER.fullmatch(source_id):
            raise ValueError("source_id de telemetría inválido")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0.05 <= timeout_seconds <= 30
        ):
            raise ValueError("El timeout de telemetría debe ser 0.05..30 segundos")
        query = urllib.parse.urlencode({"source_id": source_id})
        self._url = f"http://127.0.0.1:{port}/v1/snapshot?{query}"
        self._health_url = f"http://127.0.0.1:{port}/health"
        self._authorization = f"Bearer {token}"
        self._timeout_seconds = float(timeout_seconds)
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _RejectRedirects(),
        )

    def latest(self) -> TelemetryEnvelope:
        request = urllib.request.Request(
            self._url,
            headers={"Authorization": self._authorization, "Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                body = response.read(MAX_BODY_BYTES + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            if 300 <= exc.code < 400:
                raise DashboardReadError(
                    "El receptor intentó una redirección no permitida"
                ) from exc
            if exc.code == 401:
                raise DashboardReadError("El receptor rechazó la autenticación") from exc
            if exc.code == 404:
                raise DashboardReadError(
                    "El receptor aún no recibió una muestra de cuenta"
                ) from exc
            raise DashboardReadError(f"El receptor respondió HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DashboardReadError("No se pudo leer el receptor de telemetría local") from exc
        if len(body) > MAX_BODY_BYTES:
            raise DashboardReadError("La respuesta de telemetría supera el límite permitido")
        try:
            return parse_envelope(body)
        except TelemetryValidationError as exc:
            raise DashboardReadError("El receptor devolvió una muestra inválida") from exc

    def health(self) -> ReceiverHealth:
        request = urllib.request.Request(
            self._health_url,
            headers={"Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                body = response.read(MAX_BODY_BYTES + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            if 300 <= exc.code < 400:
                raise DashboardReadError(
                    "El receptor intentó una redirección no permitida"
                ) from exc
            raise DashboardReadError(f"El receptor respondió HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DashboardReadError("No se pudo leer el estado del receptor local") from exc
        if len(body) > MAX_BODY_BYTES:
            raise DashboardReadError("La respuesta del receptor supera el límite permitido")
        try:
            payload = json.loads(body)
        except (ValueError, TypeError) as exc:
            raise DashboardReadError("El receptor devolvió un estado inválido") from exc
        return _receiver_health(payload)


def _receiver_health(payload: object) -> ReceiverHealth:
    if not isinstance(payload, dict):
        raise DashboardReadError("El receptor devolvió un estado inválido")
    counters: dict[str, int] = {}
    for field in _COUNTER_FIELDS:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DashboardReadError("El receptor devolvió contadores inválidos")
        counters[field] = value
    history_status = payload.get("history_status")
    if not isinstance(history_status, str) or history_status not in _HISTORY_STATUSES:
        raise DashboardReadError("El receptor devolvió un estado de historial inválido")
    return ReceiverHealth(
        accepted=counters["accepted"],
        duplicates=counters["duplicates"],
        missing_sequences=counters["missing_sequences"],
        retained=counters["retained"],
        retained_sessions=counters["retained_sessions"],
        history_status=history_status,
    )


class TelemetrySnapshotSource:
    """Map one recent, validated telemetry envelope to the dashboard projection."""

    def __init__(
        self,
        client: TelemetrySnapshotClient,
        *,
        source_id: str,
        max_age: timedelta = timedelta(seconds=30),
        future_tolerance: timedelta = timedelta(seconds=DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS),
    ) -> None:
        if not IDENTIFIER.fullmatch(source_id):
            raise ValueError("source_id de telemetría inválido")
        if max_age <= timedelta(0):
            raise ValueError("La antigüedad máxima debe ser positiva")
        if future_tolerance < timedelta(0):
            raise ValueError("La tolerancia futura no puede ser negativa")
        self._client = client
        self._source_id = source_id
        self._max_age = max_age
        self._future_tolerance = future_tolerance
        self._collector_version: str | None = None

    def collect(self, observed_at: datetime) -> LiveSnapshot:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at debe incluir zona horaria")
        envelope = self._client.latest()
        if envelope.kind != "account_snapshot":
            raise DashboardReadError("El receptor no devolvió una muestra de cuenta")
        if envelope.source_id != self._source_id:
            raise DashboardReadError("La muestra pertenece a otra fuente de telemetría")
        self._collector_version = envelope.collector_version
        captured_at = datetime.fromisoformat(envelope.captured_at[:-1] + "+00:00")
        age = observed_at.astimezone(UTC) - captured_at
        if age > self._max_age:
            raise DashboardReadError("La telemetría está desactualizada")
        if age < -self._future_tolerance:
            raise DashboardReadError("El reloj del colector está adelantado")

        payload = envelope.payload
        account = payload["account"]
        positions = sorted((_position(row) for row in payload["positions"]), key=_sort_key)
        orders = sorted((_order(row) for row in payload["orders"]), key=_sort_key)
        history = payload.get("history")
        activity_window_hours = 1
        if history is not None:
            seconds = int(history["to_server_seconds"]) - int(history["from_server_seconds"])
            activity_window_hours = max(1, round(seconds / 3600))
        return LiveSnapshot(
            source="mt5-telemetry",
            account_reference=account["login_masked"],
            server=account["server"],
            currency=account["currency"],
            observed_at=envelope.captured_at,
            balance=float(account["balance"]),
            equity=float(account["equity"]),
            floating_profit=float(account["profit"]),
            margin=float(account["margin"]),
            margin_free=float(account["margin_free"]),
            margin_level=float(account["margin_level"]),
            open_positions=payload["positions_total"],
            active_orders=payload["orders_total"],
            operations=tuple(positions + orders),
            operations_truncated=(
                len(positions) < payload["positions_total"] or len(orders) < payload["orders_total"]
            ),
            # Deal timestamps retain the MT5 server scale until it is validated.
            recent_activity=(),
            activity_window_hours=activity_window_hours,
        )

    def health(self, observed_at: datetime) -> SourceHealth:
        checked_at = utc_iso(observed_at)
        try:
            receiver = self._client.health()
        except DashboardReadError as exc:
            return SourceHealth(
                availability="unavailable",
                source_id=self._source_id,
                collector_version=self._collector_version,
                checked_at=checked_at,
                error=_safe_health_message(exc),
                receiver=None,
            )
        return SourceHealth(
            availability="available",
            source_id=self._source_id,
            collector_version=self._collector_version,
            checked_at=checked_at,
            error=None,
            receiver=receiver,
        )


def _safe_health_message(exc: DashboardReadError) -> str:
    return str(exc).replace("\r", " ").replace("\n", " ").strip()[:240]


def _position(row: dict[str, object]) -> OperationSnapshot:
    return OperationSnapshot(
        kind="position",
        ticket=str(row["ticket"]),
        magic_number=str(row["magic_number"]),
        symbol=str(row["symbol"]),
        operation_type=_POSITION_TYPES[int(row["operation_type"])],
        volume=float(row["volume"]),
        price_open=float(row["price_open"]),
        price_current=float(row["price_current"]),
        stop_loss=_optional_nonzero(row["stop_loss"]),
        take_profit=_optional_nonzero(row["take_profit"]),
        floating_profit=float(row["profit"]),
        opened_at=None,
        comment=str(row["comment"]),
    )


def _order(row: dict[str, object]) -> OperationSnapshot:
    return OperationSnapshot(
        kind="order",
        ticket=str(row["ticket"]),
        magic_number=str(row["magic_number"]),
        symbol=str(row["symbol"]),
        operation_type=_ORDER_TYPES[int(row["order_type"])],
        volume=float(row["volume"]),
        price_open=float(row["price_open"]),
        price_current=float(row["price_current"]),
        stop_loss=_optional_nonzero(row["stop_loss"]),
        take_profit=_optional_nonzero(row["take_profit"]),
        floating_profit=None,
        opened_at=None,
        comment=str(row["comment"]),
    )


def _optional_nonzero(value: object) -> float | None:
    number = float(value)
    return None if number == 0 else number


def _sort_key(item: OperationSnapshot) -> tuple[int, int]:
    return (int(item.magic_number), int(item.ticket))

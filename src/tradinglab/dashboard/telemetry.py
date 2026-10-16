"""Read the validated loopback telemetry projection into dashboard snapshots."""

from __future__ import annotations

import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Protocol

from tradinglab.dashboard.snapshot import DashboardReadError, LiveSnapshot, OperationSnapshot
from tradinglab.telemetry.contract import (
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


class LoopbackTelemetryClient:
    """Fetch the newest snapshot from the authenticated loopback receiver."""

    def __init__(self, *, token: str, port: int = 8766, timeout_seconds: float = 2.0) -> None:
        if len(token) < 24 or not token.isascii() or any(not 33 <= ord(c) <= 126 for c in token):
            raise ValueError("El token de telemetría no cumple el formato requerido")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("El puerto de telemetría está fuera de rango")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0.05 <= timeout_seconds <= 30
        ):
            raise ValueError("El timeout de telemetría debe ser 0.05..30 segundos")
        self._url = f"http://127.0.0.1:{port}/v1/snapshot"
        self._authorization = f"Bearer {token}"
        self._timeout_seconds = float(timeout_seconds)

    def latest(self) -> TelemetryEnvelope:
        request = urllib.request.Request(
            self._url,
            headers={"Authorization": self._authorization, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                body = response.read(MAX_BODY_BYTES + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
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


class TelemetrySnapshotSource:
    """Map one recent, validated telemetry envelope to the dashboard projection."""

    def __init__(
        self,
        client: TelemetrySnapshotClient,
        *,
        source_id: str,
        max_age: timedelta = timedelta(seconds=30),
        future_tolerance: timedelta = timedelta(seconds=30),
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

    def collect(self, observed_at: datetime) -> LiveSnapshot:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at debe incluir zona horaria")
        envelope = self._client.latest()
        if envelope.kind != "account_snapshot":
            raise DashboardReadError("El receptor no devolvió una muestra de cuenta")
        if envelope.source_id != self._source_id:
            raise DashboardReadError("La muestra pertenece a otra fuente de telemetría")
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
            # Deal timestamps retain the MT5 server scale until it is validated.
            recent_activity=(),
            activity_window_hours=activity_window_hours,
        )


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

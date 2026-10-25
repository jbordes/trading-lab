"""Read the validated loopback telemetry projection into dashboard snapshots."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from tradinglab.dashboard.snapshot import (
    DashboardReadError,
    LiveSnapshot,
    OperationSnapshot,
    ReceiverHealth,
    SourceHealth,
    utc_iso,
)
from tradinglab.metrics import WorkbookMetricSelection, calculate_closed_deal_metrics
from tradinglab.telemetry.contract import (
    DECIMAL_INTEGER,
    DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS,
    IDENTIFIER,
    MAX_BODY_BYTES,
    MAX_INT64,
    MAX_UINT64,
    UTC_TIMESTAMP,
    TelemetryEnvelope,
    TelemetryValidationError,
    parse_envelope,
)
from tradinglab.telemetry.sqlite_store import DealHistoryCursor

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


@dataclass(frozen=True, slots=True)
class TelemetryDeal:
    account_id: str
    source_id: str
    message_id: int
    captured_at: str
    ticket: str
    order_id: str
    position_id: str
    magic_number: str
    time_msc: int
    deal_type: int
    entry: int
    symbol: str
    volume: float
    price: float
    profit: float
    commission: float
    swap: float
    fee: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TelemetryDealPage:
    account_id: str
    source_id: str
    from_msc: int
    to_msc: int
    magic_number: str | None
    deals: tuple[TelemetryDeal, ...]
    next_cursor: str | None
    coverage: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        result = {
            "account_id": self.account_id,
            "source_id": self.source_id,
            "from_msc": self.from_msc,
            "to_msc": self.to_msc,
            "magic_number": self.magic_number,
            "deals": [deal.as_dict() for deal in self.deals],
            "next_cursor": self.next_cursor,
        }
        if self.coverage is not None:
            result["coverage"] = self.coverage
        return result


@dataclass(frozen=True, slots=True)
class TelemetryPerformance:
    """Bounded workbook-v1 result ready for the authenticated dashboard."""

    account_id: str
    source_id: str
    from_msc: int
    to_msc: int
    magic_number: str | None
    selection: WorkbookMetricSelection

    def as_dict(self) -> dict[str, object]:
        metrics = self.selection.metrics
        return {
            "account_id": self.account_id,
            "source_id": self.source_id,
            "from_msc": self.from_msc,
            "to_msc": self.to_msc,
            "magic_number": self.magic_number,
            "formula_version": metrics.formula_version,
            "reference_capital": float(metrics.reference_capital),
            "risk_amount": float(metrics.risk_amount),
            "source_deal_count": self.selection.source_deal_count,
            "ignored_opening_deals": self.selection.ignored_opening_deals,
            "ignored_non_trade_deals": self.selection.ignored_non_trade_deals,
            "trade_count": metrics.trade_count,
            "net_profit": float(metrics.net_profit),
            "profit_factor": _optional_decimal(metrics.profit_factor),
            "winning_percentage": _optional_decimal(metrics.winning_percentage),
            "average_trade": _optional_decimal(metrics.average_trade),
            "maximum_drawdown": float(metrics.maximum_drawdown),
            "maximum_drawdown_percentage": float(metrics.maximum_drawdown_percentage),
            "current_drawdown": float(metrics.current_drawdown),
            "current_drawdown_percentage": float(metrics.current_drawdown_percentage),
            "return_drawdown_ratio": _optional_decimal(metrics.return_drawdown_ratio),
            "expectancy_r": _optional_decimal(metrics.expectancy_r),
            "standard_deviation": _optional_decimal(metrics.standard_deviation),
            "series": [
                {
                    "ticket": result.ticket,
                    "time_msc": result.time_msc,
                    "net_profit": float(result.net_profit),
                    "cumulative_profit": float(metrics.cumulative_profit[index]),
                    "drawdown": float(metrics.drawdown_curve[index]),
                    "rolling_average_20": float(metrics.rolling_average_20[index]),
                }
                for index, result in enumerate(self.selection.closed_results)
            ],
        }


def _optional_decimal(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


class TelemetrySnapshotClient(Protocol):
    """Small read-only boundary used by the telemetry dashboard adapter."""

    def latest(self) -> TelemetryEnvelope: ...

    def health(self) -> ReceiverHealth: ...

    def deal_history(
        self,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TelemetryDealPage: ...


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
        self._source_id = source_id
        self._url = f"http://127.0.0.1:{port}/v1/snapshot?{query}"
        self._health_url = f"http://127.0.0.1:{port}/health"
        self._deals_url = f"http://127.0.0.1:{port}/v1/deals"
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

    def deal_history(
        self,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TelemetryDealPage:
        if (
            isinstance(from_msc, bool)
            or not isinstance(from_msc, int)
            or isinstance(to_msc, bool)
            or not isinstance(to_msc, int)
            or not 0 <= from_msc < to_msc
        ):
            raise ValueError("Período de historial inválido")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("El límite de historial debe ser 1..100")
        if magic_number is not None:
            try:
                parsed_magic = int(magic_number)
            except (TypeError, ValueError) as exc:
                raise ValueError("Magic Number inválido") from exc
            if str(parsed_magic) != magic_number or not -(2**63) <= parsed_magic < 2**63:
                raise ValueError("Magic Number inválido")
        if cursor is not None:
            DealHistoryCursor.decode(cursor)
        parameters: dict[str, str | int] = {
            "source_id": self._source_id,
            "from_msc": from_msc,
            "to_msc": to_msc,
            "limit": limit,
        }
        if magic_number is not None:
            parameters["magic_number"] = magic_number
        if cursor is not None:
            parameters["cursor"] = cursor
        request = urllib.request.Request(
            f"{self._deals_url}?{urllib.parse.urlencode(parameters)}",
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
                raise DashboardReadError("El receptor no ofrece historial durable") from exc
            raise DashboardReadError(f"El receptor respondió HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DashboardReadError("No se pudo leer el historial de telemetría local") from exc
        if len(body) > MAX_BODY_BYTES:
            raise DashboardReadError("La respuesta histórica supera el límite permitido")
        try:
            payload = json.loads(body)
            return _deal_history_page(
                payload,
                source_id=self._source_id,
                from_msc=from_msc,
                to_msc=to_msc,
                magic_number=magic_number,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DashboardReadError("El receptor devolvió un historial inválido") from exc


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


_DEAL_PAGE_FIELDS = {
    "account_id",
    "source_id",
    "from_msc",
    "to_msc",
    "magic_number",
    "deals",
    "next_cursor",
}
_DEAL_FIELDS = set(TelemetryDeal.__dataclass_fields__)


def _deal_history_page(
    payload: object,
    *,
    source_id: str,
    from_msc: int,
    to_msc: int,
    magic_number: str | None,
) -> TelemetryDealPage:
    if not isinstance(payload, dict) or set(payload) != _DEAL_PAGE_FIELDS:
        raise ValueError("Respuesta histórica inválida")
    account_id = payload["account_id"]
    if not isinstance(account_id, str) or not IDENTIFIER.fullmatch(account_id):
        raise ValueError("Cuenta histórica inválida")
    if payload["source_id"] != source_id:
        raise ValueError("Fuente histórica inesperada")
    if (payload["from_msc"], payload["to_msc"], payload["magic_number"]) != (
        from_msc,
        to_msc,
        magic_number,
    ):
        raise ValueError("Filtros históricos inesperados")
    rows = payload["deals"]
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("Cantidad histórica inválida")
    deals = tuple(_telemetry_deal(row, account_id=account_id) for row in rows)
    for previous, current in zip(deals, deals[1:], strict=False):
        if (previous.time_msc, int(previous.ticket)) <= (current.time_msc, int(current.ticket)):
            raise ValueError("Orden histórico inválido")
    if any(not from_msc <= deal.time_msc < to_msc for deal in deals):
        raise ValueError("Deal fuera del período solicitado")
    if magic_number is not None and any(deal.magic_number != magic_number for deal in deals):
        raise ValueError("Magic Number histórico inesperado")
    next_cursor = payload["next_cursor"]
    if next_cursor is not None:
        decoded = DealHistoryCursor.decode(next_cursor)
        if not deals or (decoded.time_msc, decoded.ticket) != (
            deals[-1].time_msc,
            deals[-1].ticket,
        ):
            raise ValueError("Cursor histórico inconsistente")
    return TelemetryDealPage(
        account_id=account_id,
        source_id=source_id,
        from_msc=from_msc,
        to_msc=to_msc,
        magic_number=magic_number,
        deals=deals,
        next_cursor=next_cursor,
    )


def _telemetry_deal(row: object, *, account_id: str) -> TelemetryDeal:
    if not isinstance(row, dict) or set(row) != _DEAL_FIELDS:
        raise ValueError("Deal histórico inválido")
    if row["account_id"] != account_id:
        raise ValueError("Procedencia histórica inválida")
    observed_source = row["source_id"]
    if not isinstance(observed_source, str) or not IDENTIFIER.fullmatch(observed_source):
        raise ValueError("Fuente histórica inválida")
    message_id = _bounded_integer(row["message_id"], minimum=1, maximum=MAX_INT64)
    captured_at = row["captured_at"]
    if not isinstance(captured_at, str) or not UTC_TIMESTAMP.fullmatch(captured_at):
        raise ValueError("Captura histórica inválida")
    ticket = _decimal_identifier(row["ticket"], minimum=1, maximum=MAX_UINT64)
    order_id = _decimal_identifier(row["order_id"], minimum=0, maximum=MAX_INT64)
    position_id = _decimal_identifier(row["position_id"], minimum=0, maximum=MAX_INT64)
    magic = _signed_identifier(row["magic_number"])
    time_msc = _bounded_integer(row["time_msc"], minimum=0, maximum=MAX_INT64)
    deal_type = _bounded_integer(row["deal_type"], minimum=0, maximum=17)
    entry = _bounded_integer(row["entry"], minimum=0, maximum=3)
    symbol = row["symbol"]
    if not isinstance(symbol, str) or len(symbol) > 128:
        raise ValueError("Símbolo histórico inválido")
    numbers = {
        field: _finite_number(row[field])
        for field in ("volume", "price", "profit", "commission", "swap", "fee")
    }
    if numbers["volume"] < 0:
        raise ValueError("Volumen histórico inválido")
    return TelemetryDeal(
        account_id=account_id,
        source_id=observed_source,
        message_id=message_id,
        captured_at=captured_at,
        ticket=ticket,
        order_id=order_id,
        position_id=position_id,
        magic_number=magic,
        time_msc=time_msc,
        deal_type=deal_type,
        entry=entry,
        symbol=symbol,
        **numbers,
    )


def _bounded_integer(value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError("Entero histórico inválido")
    return value


def _decimal_identifier(value: object, *, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError("Identificador histórico inválido")
    parsed = int(value)
    if str(parsed) != value or not minimum <= parsed <= maximum:
        raise ValueError("Identificador histórico inválido")
    return value


def _signed_identifier(value: object) -> str:
    if not isinstance(value, str) or not DECIMAL_INTEGER.fullmatch(value):
        raise ValueError("Magic Number histórico inválido")
    if not -(2**63) <= int(value) <= MAX_INT64:
        raise ValueError("Magic Number histórico inválido")
    return value


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Número histórico inválido")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Número histórico inválido")
    return number


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

    def deal_history(
        self,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TelemetryDealPage:
        return self._client.deal_history(
            from_msc=from_msc,
            to_msc=to_msc,
            magic_number=magic_number,
            limit=limit,
            cursor=cursor,
        )

    def performance_metrics(
        self,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
    ) -> TelemetryPerformance:
        """Calculate exact workbook metrics from at most 500 verified deals."""
        deals: list[TelemetryDeal] = []
        cursor: str | None = None
        account_id: str | None = None
        while True:
            remaining = 500 - len(deals)
            if remaining <= 0:
                raise DashboardReadError("El período supera el límite seguro de 500 deals")
            page = self.deal_history(
                from_msc=from_msc,
                to_msc=to_msc,
                magic_number=magic_number,
                limit=min(100, remaining),
                cursor=cursor,
            )
            if account_id is not None and page.account_id != account_id:
                raise DashboardReadError("La cuenta cambió durante el cálculo")
            account_id = page.account_id
            deals.extend(page.deals)
            cursor = page.next_cursor
            if cursor is None:
                break
        if account_id is None:
            raise DashboardReadError("El receptor no informó la cuenta")
        return TelemetryPerformance(
            account_id=account_id,
            source_id=self._source_id,
            from_msc=from_msc,
            to_msc=to_msc,
            magic_number=magic_number,
            selection=calculate_closed_deal_metrics(deals),
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

"""Small, source-independent snapshot used by the first local dashboard."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


class DashboardReadError(RuntimeError):
    """Raised when a read-only source cannot produce a valid snapshot."""


class SnapshotSource(Protocol):
    """Minimal boundary required by the dashboard polling loop."""

    def collect(self, observed_at: datetime) -> LiveSnapshot: ...


@dataclass(frozen=True, slots=True)
class OperationSnapshot:
    """One currently open position or active pending order."""

    kind: str
    ticket: str
    magic_number: str
    symbol: str
    operation_type: str
    volume: float
    price_open: float
    price_current: float | None
    stop_loss: float | None
    take_profit: float | None
    floating_profit: float | None
    opened_at: str | None
    comment: str


@dataclass(frozen=True, slots=True)
class ActivitySnapshot:
    """One recent deal or completed historical order reported by MT5."""

    category: str
    ticket: str
    order_ticket: str | None
    position_id: str | None
    magic_number: str
    symbol: str
    event_type: str
    event_state: str | None
    volume: float
    price: float
    profit: float | None
    commission: float | None
    swap: float | None
    fee: float | None
    occurred_at: str
    comment: str


@dataclass(frozen=True, slots=True)
class LiveSnapshot:
    """Latest account-level values that both supported sources can eventually provide."""

    source: str
    account_reference: str
    server: str
    currency: str
    observed_at: str
    balance: float
    equity: float
    floating_profit: float
    margin: float
    margin_free: float
    margin_level: float | None
    open_positions: int
    active_orders: int
    operations: tuple[OperationSnapshot, ...] = ()
    recent_activity: tuple[ActivitySnapshot, ...] = ()
    activity_window_hours: int = 24

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation."""

        return asdict(self)

    def as_history_dict(self) -> dict[str, object]:
        """Return account values without repeating operation detail in history."""

        result = self.as_dict()
        result.pop("operations")
        result.pop("recent_activity")
        return result


class Mt5LiveClient(Protocol):
    """Read-only portion of the MetaTrader5 module used by the local dashboard."""

    def initialize(self) -> bool: ...

    def shutdown(self) -> None: ...

    def last_error(self) -> object: ...

    def account_info(self) -> object | None: ...

    def positions_get(self) -> object | None: ...

    def orders_get(self) -> object | None: ...

    def history_orders_get(self, date_from: datetime, date_to: datetime) -> object | None: ...

    def history_deals_get(self, date_from: datetime, date_to: datetime) -> object | None: ...


class Mt5SnapshotSource:
    """Collect one account snapshot without exposing MT5 trading operations."""

    def __init__(
        self,
        client: Mt5LiveClient,
        *,
        activity_lookback: timedelta = timedelta(hours=24),
        activity_overlap: timedelta = timedelta(minutes=2),
        activity_full_refresh: timedelta = timedelta(minutes=5),
        activity_limit: int = 200,
    ) -> None:
        if activity_lookback <= timedelta(0):
            raise ValueError("La ventana de actividad debe ser positiva")
        if activity_overlap < timedelta(0) or activity_overlap >= activity_lookback:
            raise ValueError("El solapamiento de actividad es inválido")
        if activity_full_refresh <= timedelta(0):
            raise ValueError("La reconciliación de actividad debe ser positiva")
        if activity_limit < 1:
            raise ValueError("El límite de actividad debe ser positivo")
        self._client = client
        self._activity_lookback = activity_lookback
        self._activity_overlap = activity_overlap
        self._activity_full_refresh = activity_full_refresh
        self._activity_limit = activity_limit
        self._activity_cursor: datetime | None = None
        self._activity_last_full_refresh: datetime | None = None
        self._activity: dict[tuple[str, str], ActivitySnapshot] = {}

    def collect(self, observed_at: datetime) -> LiveSnapshot:
        _require_aware(observed_at)
        if not self._client.initialize():
            raise DashboardReadError(
                f"No se pudo inicializar MT5: {_safe_error(self._client.last_error())}"
            )
        try:
            account = self._client.account_info()
            positions = self._client.positions_get()
            orders = self._client.orders_get()
            if account is None:
                raise DashboardReadError("MT5 no devolvió información de la cuenta")
            if positions is None:
                raise DashboardReadError("MT5 no devolvió las posiciones abiertas")
            if orders is None:
                raise DashboardReadError("MT5 no devolvió las órdenes activas")
            position_list = _records(positions, "posiciones")
            order_list = _records(orders, "órdenes")
            activity = self._refresh_activity(observed_at)
            return LiveSnapshot(
                source="mt5",
                account_reference=_mask_account(_field(account, "login", "unknown")),
                server=str(_field(account, "server", "MT5")),
                currency=str(_field(account, "currency", "")),
                observed_at=_utc_iso(observed_at),
                balance=_number(_field(account, "balance", 0.0), "balance"),
                equity=_number(_field(account, "equity", 0.0), "equity"),
                floating_profit=_number(_field(account, "profit", 0.0), "profit"),
                margin=_number(_field(account, "margin", 0.0), "margin"),
                margin_free=_number(_field(account, "margin_free", 0.0), "margin_free"),
                margin_level=_optional_number(
                    _field(account, "margin_level", None), "margin_level"
                ),
                open_positions=len(position_list),
                active_orders=len(order_list),
                operations=_operation_snapshots(position_list, order_list),
                recent_activity=activity,
                activity_window_hours=max(1, round(self._activity_lookback.total_seconds() / 3600)),
            )
        finally:
            self._client.shutdown()

    def _refresh_activity(self, observed_at: datetime) -> tuple[ActivitySnapshot, ...]:
        cutoff = observed_at - self._activity_lookback
        full_refresh_due = (
            self._activity_last_full_refresh is None
            or observed_at - self._activity_last_full_refresh >= self._activity_full_refresh
        )
        date_from = (
            cutoff
            if full_refresh_due or self._activity_cursor is None
            else max(cutoff, self._activity_cursor - self._activity_overlap)
        )
        deals = self._client.history_deals_get(date_from, observed_at)
        orders = self._client.history_orders_get(date_from, observed_at)
        if deals is None:
            raise DashboardReadError(
                f"MT5 no devolvió deals recientes: {_safe_error(self._client.last_error())}"
            )
        if orders is None:
            raise DashboardReadError(
                f"MT5 no devolvió órdenes históricas: {_safe_error(self._client.last_error())}"
            )

        additions = [_deal_activity(record) for record in _records(deals, "deals recientes")] + [
            _historical_order_activity(record) for record in _records(orders, "órdenes históricas")
        ]
        updated = dict(self._activity)
        for item in additions:
            updated[(item.category, item.ticket)] = item
        cutoff_iso = _utc_iso(cutoff)
        retained = [item for item in updated.values() if item.occurred_at >= cutoff_iso]
        retained.sort(key=lambda item: (item.occurred_at, item.category, item.ticket), reverse=True)
        retained = retained[: self._activity_limit]
        self._activity = {(item.category, item.ticket): item for item in retained}
        self._activity_cursor = observed_at
        if full_refresh_due:
            self._activity_last_full_refresh = observed_at
        return tuple(retained)


class DemoSnapshotSource:
    """Deterministic source for local UI validation without broker credentials."""

    _MOVES = (0.0, 42.0, 18.0, -25.0, -8.0, 55.0, 31.0, 76.0)

    def __init__(self) -> None:
        self._index = 0

    def collect(self, observed_at: datetime) -> LiveSnapshot:
        _require_aware(observed_at)
        move = self._MOVES[self._index % len(self._MOVES)]
        self._index += 1
        balance = 100_000.0
        return LiveSnapshot(
            source="demo",
            account_reference="DEMO-0001",
            server="TradingLab Demo",
            currency="USD",
            observed_at=_utc_iso(observed_at),
            balance=balance,
            equity=balance + move,
            floating_profit=move,
            margin=1_250.0,
            margin_free=98_750.0 + move,
            margin_level=8_000.0,
            open_positions=2,
            active_orders=1,
            operations=(
                OperationSnapshot(
                    "position",
                    "810001",
                    "11122",
                    "EURUSD",
                    "buy",
                    0.1,
                    1.0842,
                    1.0851,
                    1.081,
                    1.091,
                    move,
                    _utc_iso(observed_at),
                    "demo-alpha",
                ),
                OperationSnapshot(
                    "position",
                    "810002",
                    "33007",
                    "XAUUSD",
                    "sell",
                    0.05,
                    2675.4,
                    2673.9,
                    None,
                    2660.0,
                    0.0,
                    _utc_iso(observed_at),
                    "demo-gold",
                ),
                OperationSnapshot(
                    "order",
                    "910001",
                    "11122",
                    "GBPUSD",
                    "buy_limit",
                    0.1,
                    1.264,
                    1.2662,
                    1.258,
                    1.276,
                    None,
                    _utc_iso(observed_at),
                    "demo-pending",
                ),
            ),
            recent_activity=(
                ActivitySnapshot(
                    category="deal",
                    ticket="710003",
                    order_ticket="710002",
                    position_id="610001",
                    magic_number="11122",
                    symbol="EURUSD",
                    event_type="sell_out",
                    event_state=None,
                    volume=0.1,
                    price=1.0851,
                    profit=42.0,
                    commission=-0.7,
                    swap=0.0,
                    fee=0.0,
                    occurred_at=_utc_iso(observed_at - timedelta(minutes=3)),
                    comment="demo-close",
                ),
                ActivitySnapshot(
                    category="order",
                    ticket="710002",
                    order_ticket=None,
                    position_id="610001",
                    magic_number="11122",
                    symbol="EURUSD",
                    event_type="sell",
                    event_state="filled",
                    volume=0.1,
                    price=1.0851,
                    profit=None,
                    commission=None,
                    swap=None,
                    fee=None,
                    occurred_at=_utc_iso(observed_at - timedelta(minutes=3)),
                    comment="demo-order",
                ),
            ),
        )


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
_ORDER_STATES = {
    0: "started",
    1: "placed",
    2: "canceled",
    3: "partial",
    4: "filled",
    5: "rejected",
    6: "expired",
    7: "request_add",
    8: "request_modify",
    9: "request_cancel",
}
_DEAL_TYPES = {
    0: "buy",
    1: "sell",
    2: "balance",
    3: "credit",
    4: "charge",
    5: "correction",
    6: "bonus",
    7: "commission",
    8: "commission_daily",
    9: "commission_monthly",
    10: "commission_agent_daily",
    11: "commission_agent_monthly",
    12: "interest",
    13: "buy_canceled",
    14: "sell_canceled",
    15: "dividend",
    16: "dividend_franked",
    17: "tax",
}
_DEAL_ENTRIES = {0: "in", 1: "out", 2: "inout", 3: "out_by"}


def _deal_activity(record: object) -> ActivitySnapshot:
    deal_type = _type_name(_field(record, "type", None), _DEAL_TYPES, "deal.type")
    if deal_type in {"buy", "sell"}:
        entry = _type_name(_field(record, "entry", None), _DEAL_ENTRIES, "deal.entry")
        deal_type = f"{deal_type}_{entry}"
    return ActivitySnapshot(
        category="deal",
        ticket=_identifier(_field(record, "ticket", None), "deal.ticket"),
        order_ticket=_optional_identifier(_field(record, "order", 0), "deal.order"),
        position_id=_optional_identifier(_field(record, "position_id", 0), "deal.position_id"),
        magic_number=_identifier(_field(record, "magic", 0), "deal.magic"),
        symbol=_activity_symbol(_field(record, "symbol", "")),
        event_type=deal_type,
        event_state=None,
        volume=_number(_field(record, "volume", 0.0), "deal.volume"),
        price=_number(_field(record, "price", 0.0), "deal.price"),
        profit=_number(_field(record, "profit", 0.0), "deal.profit"),
        commission=_number(_field(record, "commission", 0.0), "deal.commission"),
        swap=_number(_field(record, "swap", 0.0), "deal.swap"),
        fee=_number(_field(record, "fee", 0.0), "deal.fee"),
        occurred_at=_record_timestamp(record, "time_msc", "time", "deal.time"),
        comment=_display_text(_field(record, "comment", ""), 160),
    )


def _historical_order_activity(record: object) -> ActivitySnapshot:
    return ActivitySnapshot(
        category="order",
        ticket=_identifier(_field(record, "ticket", None), "order.ticket"),
        order_ticket=None,
        position_id=_optional_identifier(_field(record, "position_id", 0), "order.position_id"),
        magic_number=_identifier(_field(record, "magic", 0), "order.magic"),
        symbol=_activity_symbol(_field(record, "symbol", "")),
        event_type=_type_name(_field(record, "type", None), _ORDER_TYPES, "order.type"),
        event_state=_type_name(_field(record, "state", None), _ORDER_STATES, "order.state"),
        volume=_number(_field(record, "volume_initial", 0.0), "order.volume_initial"),
        price=_number(_field(record, "price_open", 0.0), "order.price_open"),
        profit=None,
        commission=None,
        swap=None,
        fee=None,
        occurred_at=_historical_order_timestamp(record),
        comment=_display_text(_field(record, "comment", ""), 160),
    )


def _operation_snapshots(
    positions: list[object], orders: list[object]
) -> tuple[OperationSnapshot, ...]:
    operations = [_position_snapshot(position) for position in positions] + [
        _order_snapshot(order) for order in orders
    ]
    operations.sort(
        key=lambda item: (
            0 if item.kind == "position" else 1,
            int(item.magic_number),
            int(item.ticket),
        )
    )
    return tuple(operations)


def _position_snapshot(position: object) -> OperationSnapshot:
    return OperationSnapshot(
        kind="position",
        ticket=_identifier(_field(position, "ticket", None), "ticket"),
        magic_number=_identifier(_field(position, "magic", 0), "magic number"),
        symbol=_symbol(_field(position, "symbol", "")),
        operation_type=_type_name(_field(position, "type", None), _POSITION_TYPES, "position.type"),
        volume=_number(_field(position, "volume", 0.0), "position.volume"),
        price_open=_number(_field(position, "price_open", 0.0), "position.price_open"),
        price_current=_optional_number(
            _field(position, "price_current", None), "position.price_current"
        ),
        stop_loss=_optional_nonzero_number(_field(position, "sl", 0.0), "position.sl"),
        take_profit=_optional_nonzero_number(_field(position, "tp", 0.0), "position.tp"),
        floating_profit=_number(_field(position, "profit", 0.0), "position.profit"),
        opened_at=_timestamp(_field(position, "time", None), "position.time"),
        comment=_display_text(_field(position, "comment", ""), 160),
    )


def _order_snapshot(order: object) -> OperationSnapshot:
    volume = _field(order, "volume_current", None)
    if volume is None:
        volume = _field(order, "volume_initial", 0.0)
    return OperationSnapshot(
        kind="order",
        ticket=_identifier(_field(order, "ticket", None), "ticket"),
        magic_number=_identifier(_field(order, "magic", 0), "magic number"),
        symbol=_symbol(_field(order, "symbol", "")),
        operation_type=_type_name(_field(order, "type", None), _ORDER_TYPES, "order.type"),
        volume=_number(volume, "order.volume"),
        price_open=_number(_field(order, "price_open", 0.0), "order.price_open"),
        price_current=_optional_number(_field(order, "price_current", None), "order.price_current"),
        stop_loss=_optional_nonzero_number(_field(order, "sl", 0.0), "order.sl"),
        take_profit=_optional_nonzero_number(_field(order, "tp", 0.0), "order.tp"),
        floating_profit=None,
        opened_at=_timestamp(_field(order, "time_setup", None), "order.time_setup"),
        comment=_display_text(_field(order, "comment", ""), 160),
    )


def _identifier(value: object, name: str) -> str:
    if isinstance(value, bool):
        raise DashboardReadError(f"MT5 devolvió {name} inválido")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise DashboardReadError(f"MT5 devolvió {name} inválido") from exc
    if number < 0 or str(value).strip() not in {str(number), f"{number}.0"}:
        raise DashboardReadError(f"MT5 devolvió {name} inválido")
    return str(number)


def _optional_identifier(value: object, name: str) -> str | None:
    identifier = _identifier(value, name)
    return None if identifier == "0" else identifier


def _type_name(value: object, names: Mapping[int, str], name: str) -> str:
    identifier = int(_identifier(value, name))
    return names.get(identifier, f"type_{identifier}")


def _symbol(value: object) -> str:
    text = str(value).strip()
    if not text or len(text) > 64 or any(character in text for character in "\r\n\0"):
        raise DashboardReadError("MT5 devolvió symbol inválido")
    return text


def _activity_symbol(value: object) -> str:
    text = str(value).strip()
    if not text:
        return "CUENTA"
    return _symbol(text)


def _display_text(value: object, limit: int) -> str:
    text = " ".join(str(value).replace("\0", "").split())
    return text[:limit]


def _timestamp(value: object, name: str) -> str | None:
    if value is None or value == 0:
        return None
    seconds = _number(value, name)
    if seconds < 0:
        raise DashboardReadError(f"MT5 devolvió {name} inválido")
    try:
        return _utc_iso(datetime.fromtimestamp(seconds, tz=UTC))
    except (OSError, OverflowError, ValueError) as exc:
        raise DashboardReadError(f"MT5 devolvió {name} inválido") from exc


def _record_timestamp(record: object, milliseconds_name: str, seconds_name: str, label: str) -> str:
    milliseconds = _field(record, milliseconds_name, 0)
    if milliseconds not in {None, 0}:
        timestamp = _timestamp(_number(milliseconds, label) / 1000, label)
    else:
        timestamp = _timestamp(_field(record, seconds_name, None), label)
    if timestamp is None:
        raise DashboardReadError(f"MT5 devolvió {label} inválido")
    return timestamp


def _historical_order_timestamp(record: object) -> str:
    done_milliseconds = _field(record, "time_done_msc", 0)
    done_seconds = _field(record, "time_done", 0)
    if done_milliseconds not in {None, 0} or done_seconds not in {None, 0}:
        return _record_timestamp(record, "time_done_msc", "time_done", "order.time_done")
    return _record_timestamp(record, "time_setup_msc", "time_setup", "order.time_setup")


def _field(record: object, name: str, default: object) -> object:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _records(value: object, label: str) -> list[object]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Iterable):
        raise DashboardReadError(f"MT5 devolvió {label} con un formato inesperado")
    return list(value)


def _number(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DashboardReadError(f"MT5 devolvió {name} inválido") from exc
    if not math.isfinite(number):
        raise DashboardReadError(f"MT5 devolvió {name} no finito")
    return number


def _optional_number(value: object, name: str) -> float | None:
    return None if value is None else _number(value, name)


def _optional_nonzero_number(value: object, name: str) -> float | None:
    number = _optional_number(value, name)
    return None if number == 0 else number


def _mask_account(value: object) -> str:
    text = str(value)
    if len(text) <= 4:
        return text
    return f"{'*' * (len(text) - 4)}{text[-4:]}"


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observed_at debe incluir zona horaria")


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_error(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    return text[:240]

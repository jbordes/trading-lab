"""Small, source-independent snapshot used by the first local dashboard."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
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

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation."""

        return asdict(self)

    def as_history_dict(self) -> dict[str, object]:
        """Return account values without repeating operation detail in history."""

        result = self.as_dict()
        result.pop("operations")
        return result


class Mt5LiveClient(Protocol):
    """Read-only portion of the MetaTrader5 module used by the local dashboard."""

    def initialize(self) -> bool: ...

    def shutdown(self) -> None: ...

    def last_error(self) -> object: ...

    def account_info(self) -> object | None: ...

    def positions_get(self) -> object | None: ...

    def orders_get(self) -> object | None: ...


class Mt5SnapshotSource:
    """Collect one account snapshot without exposing MT5 trading operations."""

    def __init__(self, client: Mt5LiveClient) -> None:
        self._client = client

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
            )
        finally:
            self._client.shutdown()


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
        raise DashboardReadError(f"MT5 devolviÃ³ {name} invÃ¡lido")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise DashboardReadError(f"MT5 devolviÃ³ {name} invÃ¡lido") from exc
    if number < 0 or str(value).strip() not in {str(number), f"{number}.0"}:
        raise DashboardReadError(f"MT5 devolviÃ³ {name} invÃ¡lido")
    return str(number)


def _type_name(value: object, names: Mapping[int, str], name: str) -> str:
    identifier = int(_identifier(value, name))
    return names.get(identifier, f"type_{identifier}")


def _symbol(value: object) -> str:
    text = str(value).strip()
    if not text or len(text) > 64 or any(character in text for character in "\r\n\0"):
        raise DashboardReadError("MT5 devolviÃ³ symbol invÃ¡lido")
    return text


def _display_text(value: object, limit: int) -> str:
    text = " ".join(str(value).replace("\0", "").split())
    return text[:limit]


def _timestamp(value: object, name: str) -> str | None:
    if value is None or value == 0:
        return None
    seconds = _number(value, name)
    if seconds < 0:
        raise DashboardReadError(f"MT5 devolviÃ³ {name} invÃ¡lido")
    try:
        return _utc_iso(datetime.fromtimestamp(seconds, tz=UTC))
    except (OSError, OverflowError, ValueError) as exc:
        raise DashboardReadError(f"MT5 devolviÃ³ {name} invÃ¡lido") from exc


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

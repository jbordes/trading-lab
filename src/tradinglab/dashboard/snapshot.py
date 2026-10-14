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

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation."""

        return asdict(self)


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
        )


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

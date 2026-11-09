"""Pure, bounded consolidation of observed account samples into one broker day."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from tradinglab.telemetry.contract import IDENTIFIER


@dataclass(frozen=True)
class AccountObservation:
    """One validated capture; broker wall time is not a guessed UTC instant."""

    account_id: str
    captured_at_utc: datetime
    broker_time: datetime
    balance: Decimal
    equity: Decimal
    floating_pnl: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, str) or not IDENTIFIER.fullmatch(self.account_id):
            raise ValueError("Invalid account identity")
        if (
            not isinstance(self.captured_at_utc, datetime)
            or self.captured_at_utc.utcoffset() is None
            or not isinstance(self.broker_time, datetime)
            or self.broker_time.tzinfo is not None
        ):
            raise ValueError("Capture requires aware UTC time and naive broker wall time")
        if any(
            not isinstance(value, Decimal) or not value.is_finite()
            for value in (self.balance, self.equity, self.floating_pnl)
        ):
            raise ValueError("Account amounts must be finite decimals")


@dataclass(frozen=True)
class DailyAccountObservation:
    """Last observed value, not a guaranteed midnight valuation or realized PnL."""

    account_id: str
    broker_day: date
    first_captured_at_utc: datetime
    close: AccountObservation
    min_balance: Decimal
    max_balance: Decimal
    min_equity: Decimal
    max_equity: Decimal


def consolidate_broker_day(
    observations: Iterable[AccountObservation],
    *,
    account_id: str,
    broker_day: date,
    current_broker_day: date,
) -> DailyAccountObservation | None:
    """Reduce one closed day in O(1) memory, regardless of arrival order.

    The caller supplies the current broker date; the machine's local date or
    current broker offset cannot define historical days. Replaying identical
    input gives the same result. No samples means no synthetic daily record.
    """
    if not isinstance(account_id, str) or not IDENTIFIER.fullmatch(account_id):
        raise ValueError("Invalid account identity")
    if type(broker_day) is not date or type(current_broker_day) is not date:
        raise ValueError("Broker days must be dates")
    if broker_day >= current_broker_day:
        raise ValueError("Only a closed broker day can be consolidated")

    close: AccountObservation | None = None
    conflicting_close = False
    first: datetime | None = None
    min_balance = max_balance = min_equity = max_equity = Decimal(0)
    for sample in observations:
        if sample.account_id != account_id:
            raise ValueError("Cannot consolidate observations from another account")
        if sample.broker_time.date() != broker_day:
            continue
        captured = sample.captured_at_utc.astimezone(UTC)
        if close is None:
            close = sample
            first = captured
            min_balance = max_balance = sample.balance
            min_equity = max_equity = sample.equity
        else:
            previous = close.captured_at_utc.astimezone(UTC)
            if captured == previous and (
                sample.broker_time,
                sample.balance,
                sample.equity,
                sample.floating_pnl,
            ) != (close.broker_time, close.balance, close.equity, close.floating_pnl):
                conflicting_close = True
            if captured > previous:
                close = sample
                conflicting_close = False
            first = min(first, captured)
            min_balance = min(min_balance, sample.balance)
            max_balance = max(max_balance, sample.balance)
            min_equity = min(min_equity, sample.equity)
            max_equity = max(max_equity, sample.equity)

    if close is None:
        return None
    if conflicting_close:
        raise ValueError("Conflicting closing observations at the same instant")
    assert first is not None
    return DailyAccountObservation(
        account_id, broker_day, first, close, min_balance, max_balance, min_equity, max_equity
    )

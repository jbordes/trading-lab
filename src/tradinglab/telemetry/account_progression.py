"""Account ledger projection, distinct from EA metrics and observed equity."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

DAY_MSC = 86_400_000


def _number(amount: Decimal) -> float:
    value = float(amount)
    if not math.isfinite(value):
        raise ValueError("El resultado excede el rango financiero representable")
    return value


def progression_bucket_msc(from_msc: int, to_msc: int) -> int:
    """Validate a request and return a bucket width yielding at most 480 points."""
    if (
        type(from_msc) is not int
        or type(to_msc) is not int
        or not 0 <= from_msc < to_msc < 253402300799000
        or to_msc - from_msc > 366 * DAY_MSC
    ):
        raise ValueError("La ventana debe abarcar hasta 12 meses")
    return max(60_000, (to_msc - from_msc + 479) // 480)


@dataclass(frozen=True)
class LedgerMovement:
    time_msc: int
    deal_type: int
    profit: Decimal
    commission: Decimal = Decimal(0)
    swap: Decimal = Decimal(0)
    fee: Decimal = Decimal(0)


@dataclass(frozen=True)
class BalanceAnchor:
    server_msc: int
    balance: Decimal


def _components(row: LedgerMovement) -> tuple[Decimal, Decimal, Decimal, Decimal, bool]:
    values = (row.profit, row.commission, row.swap, row.fee)
    if any(not value.is_finite() for value in values):
        raise ValueError("El movimiento contiene importes no finitos")
    costs = row.commission + row.swap + row.fee
    net = row.profit + costs
    if row.deal_type in {0, 1, 4, 7, 8, 9, 10, 11, 12, 15, 16, 17}:
        return net, Decimal(0), Decimal(0), net, True
    if row.deal_type in {2, 6}:  # Balance transfers and bonuses are not trading profit.
        return costs, row.profit, Decimal(0), net, True
    if row.deal_type == 5:  # Broker corrections remain explicit, not trading performance.
        return costs, Decimal(0), row.profit, net, True
    if row.deal_type == 3:  # Credit changes equity/credit, not account balance.
        return costs, Decimal(0), Decimal(0), costs, True
    # Cancelled historical deals require broker-specific reconciliation.
    return Decimal(0), Decimal(0), Decimal(0), Decimal(0), False


def project_account_progression(
    movements: Iterable[LedgerMovement],
    *,
    from_msc: int,
    to_msc: int,
    complete_ranges: tuple[tuple[int, int], ...],
    anchor: BalanceAnchor | None = None,
    conflicts: bool = False,
) -> dict[str, object]:
    """Project at most 480 buckets using constant memory and exact monetary sums.

    Times use the broker's wall-clock scale, never a guessed historical UTC offset.
    Missing evidence yields nulls, not flat zero-profit or invented balance curves.
    An anchor is second-resolution; any ledger event in that second invalidates it.
    """
    bucket = progression_bucket_msc(from_msc, to_msc)
    count = (to_msc - from_msc + bucket - 1) // bucket
    covered_starts = [max(a, from_msc) for a, b in complete_ranges if b > from_msc and a < to_msc]
    pnl_start = min(covered_starts) if covered_starts else None
    buckets = [[Decimal(0) for _ in range(4)] for _ in range(count)]
    tail = Decimal(0)
    post_anchor = Decimal(0)
    uncertain = conflicts
    anchor_busy = False
    for row in movements:
        if type(row.time_msc) is not int or row.time_msc < from_msc:
            raise ValueError("Movimiento fuera del inicio solicitado")
        pnl, cash, adjustment, balance_delta, supported = _components(row)
        uncertain |= not supported
        if anchor is not None and anchor.server_msc <= row.time_msc < anchor.server_msc + 1000:
            anchor_busy = True
        if row.time_msc < to_msc and pnl_start is not None and row.time_msc >= pnl_start:
            index = (row.time_msc - from_msc) // bucket
            for column, amount in enumerate((pnl, cash, adjustment, balance_delta)):
                buckets[index][column] += amount
            if anchor is not None and row.time_msc >= anchor.server_msc:
                post_anchor += balance_delta
        elif anchor is not None and to_msc <= row.time_msc < anchor.server_msc:
            tail += balance_delta

    def covered(start: int, end: int) -> bool:
        return any(a <= start and b >= end for a, b in complete_ranges)

    ledger_complete = covered(from_msc, to_msc) and not uncertain
    balance_status = "missing_anchor"
    if anchor is not None:
        if not anchor.balance.is_finite() or anchor.server_msc % 1000:
            raise ValueError("Referencia de balance inválida")
        balance_status = "available"
        if (pnl_start is not None and anchor.server_msc < pnl_start) or anchor_busy:
            balance_status = "ambiguous_anchor"
        elif pnl_start is None or not covered(pnl_start, anchor.server_msc + 1000) or uncertain:
            balance_status = "incomplete_ledger"
    opening = None
    if balance_status == "available" and anchor is not None:
        opening = anchor.balance - tail - sum((row[3] for row in buckets), Decimal(0)) + post_anchor
    pnl_sum = cash_sum = adjustment_sum = balance_sum = Decimal(0)
    points = []
    for index, row in enumerate(buckets):
        pnl_sum += row[0]
        cash_sum += row[1]
        adjustment_sum += row[2]
        balance_sum += row[3]
        end = min(to_msc, from_msc + (index + 1) * bucket)
        known = (
            pnl_start is not None and end > pnl_start and covered(pnl_start, end) and not uncertain
        )
        points.append(
            {
                "time_msc": str(end - 1),
                "realized_pnl": _number(pnl_sum) if known else None,
                "net_cash_flow": _number(cash_sum) if known else None,
                "adjustments": _number(adjustment_sum) if known else None,
                "balance": _number(opening + balance_sum)
                if opening is not None and known and anchor is not None and end <= anchor.server_msc
                else None,
            }
        )
    return {
        "from_server_msc": from_msc,
        "to_server_msc": to_msc,
        "time_basis": "broker_wall_clock",
        "calculation_version": "account-ledger-v1",
        "bucket_msc": bucket,
        "status": "complete" if ledger_complete else "partial",
        "balance_status": balance_status,
        "pnl_from_server_msc": str(pnl_start) if pnl_start is not None else None,
        "anchor_server_msc": str(anchor.server_msc) if balance_status == "available" else None,
        "points": points,
    }

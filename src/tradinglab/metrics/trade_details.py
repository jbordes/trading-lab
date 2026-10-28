"""Compact presentation facts from one validated position reconciliation."""

from decimal import Decimal

from tradinglab.metrics.position_cycles import PositionCycle


def trade_details(cycle: PositionCycle, payload: dict[str, object]) -> dict[str, object]:
    """Aggregate only this cycle's evidence; never infer a pip size or final stops."""
    deals = sorted(
        (row for row in payload["deals"]["items"] if row["deal_type"] in (0, 1)),
        key=lambda row: (int(row["time_msc"]), int(row["ticket"])),
    )
    if tuple(row["ticket"] for row in deals) != cycle.deal_tickets or any(
        row["position_id"] != cycle.position_id for row in deals
    ):
        raise ValueError("La evidencia no corresponde al ciclo")
    entries = [row for row in deals if row["entry"] == 0]
    exits = [row for row in deals if row["entry"] in (1, 3)]
    simple = bool(entries and exits) and all(row["entry"] in (0, 1, 3) for row in deals)
    simple = simple and len({row["deal_type"] for row in entries}) == 1
    simple = simple and all(row["deal_type"] != entries[0]["deal_type"] for row in exits)
    side = ("long" if entries[0]["deal_type"] == 0 else "short") if simple else None
    symbols = {row["symbol"] for row in deals}

    def total(rows: list[dict[str, object]], field: str) -> Decimal:
        return sum((Decimal(str(row[field])) for row in rows), Decimal(0))

    def mean_price(rows: list[dict[str, object]]) -> float | None:
        volume = total(rows, "volume")
        if not simple or not volume:
            return None
        return float(
            sum(
                (Decimal(str(row["price"])) * Decimal(str(row["volume"])) for row in rows),
                Decimal(0),
            )
            / volume
        )

    if (
        sum((total(deals, field) for field in ("profit", "swap", "commission", "fee")), Decimal(0))
        != cycle.observed_net_result
    ):
        raise ValueError("Los costos no coinciden con el resultado del ciclo")

    orders = {row["ticket"]: row for row in payload["orders"]["items"]}
    opening_tickets = list(dict.fromkeys(row["order_id"] for row in entries))
    # A closing market order with zero stops does not prove stops were removed.
    # Nonzero exit-order levels are observations at exit, never a full stop history.
    exit_levels = [
        orders[row["order_id"]]
        for row in exits
        if row["order_id"] in orders
        and any(orders[row["order_id"]][field] != 0 for field in ("stop_loss", "take_profit"))
    ]
    initial_levels = [orders[ticket] for ticket in opening_tickets if ticket in orders]
    levels = exit_levels[-1] if exit_levels else initial_levels[0] if initial_levels else None
    return {
        "side": side,
        "symbol": next(iter(symbols)) if len(symbols) == 1 else None,
        "opening_tickets": opening_tickets,
        "volume": float(total(entries, "volume")) if simple else None,
        "open_price": mean_price(entries),
        "close_price": mean_price(exits),
        "gross_profit": float(total(deals, "profit")),
        "swap": float(total(deals, "swap")),
        "commission": float(total(deals, "commission")),
        "fee": float(total(deals, "fee")),
        "take_profit": levels["take_profit"] if levels else None,
        "stop_loss": levels["stop_loss"] if levels else None,
        "levels_basis": "exit_order" if exit_levels else "initial_order" if levels else "unknown",
        "pips": None,
        "duration_hours": (cycle.last_event_at_msc - cycle.started_at_msc) / 3_600_000,
    }

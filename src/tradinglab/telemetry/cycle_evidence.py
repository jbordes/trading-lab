"""Convert validated MT5 rows to the shared position-cycle model."""

from dataclasses import dataclass

from tradinglab.metrics.position_cycles import PositionCycle, reconstruct_position_cycles


@dataclass(frozen=True, slots=True)
class _PositionDeal:
    account_id: str
    ticket: str
    position_id: str
    magic_number: str
    time_msc: int
    deal_type: int
    entry: int
    volume: float
    profit: float
    commission: float
    swap: float
    fee: float


def cycle_document(cycle: PositionCycle) -> dict[str, object]:
    return {
        "account_id": cycle.account_id,
        "position_id": cycle.position_id,
        "owner_magic": cycle.owner_magic,
        "observed_magics": cycle.observed_magics,
        "started_at_msc": cycle.started_at_msc,
        "last_event_at_msc": cycle.last_event_at_msc,
        "lifecycle": cycle.lifecycle.value,
        "remaining_signed_volume": str(cycle.remaining_signed_volume),
        "observed_net_result": str(cycle.observed_net_result),
        "deal_tickets": cycle.deal_tickets,
        "exclusions": tuple(reason.value for reason in cycle.exclusions),
    }


def position_cycle(account_id: str, rows: list[dict[str, object]]) -> PositionCycle:
    deals = tuple(
        _PositionDeal(
            account_id=account_id,
            ticket=str(row["ticket"]),
            position_id=str(row["position_id"]),
            magic_number=str(row["magic_number"]),
            time_msc=int(str(row["time_msc"])),
            deal_type=int(row["deal_type"]),
            entry=int(row["entry"]),
            volume=float(row["volume"]),
            profit=float(row["profit"]),
            commission=float(row["commission"]),
            swap=float(row["swap"]),
            fee=float(row["fee"]),
        )
        for row in rows
    )
    position_id = deals[0].position_id
    selection = reconstruct_position_cycles(
        deals,
        coverage_confirmed={(account_id, position_id)},
    )
    if len(selection.cycles) != 1:
        raise ValueError("La reconciliación no produjo un único ciclo de posición")
    return selection.cycles[0]

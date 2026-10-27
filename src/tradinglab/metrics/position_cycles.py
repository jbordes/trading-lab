"""Conservative reconstruction of MT5 position lifecycles.

This module does not calculate performance metrics.  It turns verified deals into
auditable position cycles and only marks a cycle eligible when the caller can
prove that its evidence is complete.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Set
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

COMMERCIAL_DEAL_TYPES = frozenset((0, 1))
ENTRY_IN = 0
ZERO_IDENTIFIER = "0"

type PositionKey = tuple[str, str]


class DealForPositionCycle(Protocol):
    """Minimum verified deal shape required to reconstruct one position."""

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


class CycleLifecycle(StrEnum):
    """What the observed evidence proves about the position lifecycle."""

    CLOSED = "closed"
    OPEN = "open"
    INCOMPLETE = "incomplete"
    INCONSISTENT = "inconsistent"


class CycleExclusion(StrEnum):
    """Reasons why a cycle cannot represent autonomous EA performance."""

    INCOMPLETE_EVIDENCE = "incomplete_evidence"
    OPEN_POSITION = "open_position"
    INCONSISTENT_LIFECYCLE = "inconsistent_lifecycle"
    UNATTRIBUTED_OWNER = "unattributed_owner"
    UNATTRIBUTED_ACTION = "unattributed_action"
    MIXED_MAGIC = "mixed_magic"


@dataclass(frozen=True, slots=True)
class PositionCycle:
    """One position lifecycle reconstructed without erasing its source deals."""

    account_id: str
    position_id: str
    owner_magic: str | None
    observed_magics: tuple[str, ...]
    started_at_msc: int
    last_event_at_msc: int
    lifecycle: CycleLifecycle
    remaining_signed_volume: Decimal
    observed_net_result: Decimal
    deal_tickets: tuple[str, ...]
    exclusions: tuple[CycleExclusion, ...]

    @property
    def eligible_for_autonomous_metrics(self) -> bool:
        return not self.exclusions

    @property
    def definitive_net_result(self) -> Decimal | None:
        if not self.eligible_for_autonomous_metrics:
            return None
        return self.observed_net_result


@dataclass(frozen=True, slots=True)
class PositionCycleSelection:
    """Reconstruction result with explicit evidence of ignored MT5 entities."""

    cycles: tuple[PositionCycle, ...]
    source_deal_count: int
    ignored_noncommercial_deals: int
    ignored_without_position: int

    @property
    def eligible_cycles(self) -> tuple[PositionCycle, ...]:
        return tuple(cycle for cycle in self.cycles if cycle.eligible_for_autonomous_metrics)


def reconstruct_position_cycles(
    deals: Iterable[DealForPositionCycle],
    *,
    coverage_confirmed: Set[PositionKey],
) -> PositionCycleSelection:
    """Group commercial deals by account and position and classify each cycle.

    ``coverage_confirmed`` is deliberately mandatory.  A bounded date query can
    start after a position opened or end before it closed, so balanced volume in
    that query is not sufficient proof of a complete lifecycle.
    """

    observed = tuple(deals)
    groups: dict[PositionKey, list[DealForPositionCycle]] = defaultdict(list)
    ignored_noncommercial = 0
    ignored_without_position = 0
    seen_tickets: set[tuple[str, str]] = set()

    for deal in observed:
        _validate_deal(deal)
        ticket_key = (deal.account_id, deal.ticket)
        if ticket_key in seen_tickets:
            raise ValueError("Deal duplicado dentro de la misma cuenta")
        seen_tickets.add(ticket_key)

        if deal.deal_type not in COMMERCIAL_DEAL_TYPES:
            ignored_noncommercial += 1
            continue
        if deal.position_id == ZERO_IDENTIFIER:
            ignored_without_position += 1
            continue
        _validate_commercial_deal(deal)
        groups[(deal.account_id, deal.position_id)].append(deal)

    cycles = tuple(
        _reconstruct_group(key, rows, coverage_confirmed=key in coverage_confirmed)
        for key, rows in sorted(groups.items())
    )
    return PositionCycleSelection(
        cycles=cycles,
        source_deal_count=len(observed),
        ignored_noncommercial_deals=ignored_noncommercial,
        ignored_without_position=ignored_without_position,
    )


def _reconstruct_group(
    key: PositionKey,
    deals: list[DealForPositionCycle],
    *,
    coverage_confirmed: bool,
) -> PositionCycle:
    ordered = sorted(deals, key=lambda deal: (deal.time_msc, int(deal.ticket)))
    first = ordered[0]
    owner_magic = first.magic_number if first.entry == ENTRY_IN else None
    if owner_magic == ZERO_IDENTIFIER:
        owner_magic = None

    evidence_complete = coverage_confirmed and first.entry == ENTRY_IN
    signed_volume = Decimal(0)
    net_result = Decimal(0)
    reached_zero_before_end = False
    inconsistent_transition = False
    for index, deal in enumerate(ordered):
        volume = _finite_decimal(deal.volume, "volumen")
        volume_change = volume if deal.deal_type == 0 else -volume
        if not _entry_transition_is_consistent(signed_volume, volume_change, deal.entry):
            inconsistent_transition = True
        signed_volume += volume_change
        net_result += sum(
            (
                _finite_decimal(deal.profit, "profit"),
                _finite_decimal(deal.commission, "commission"),
                _finite_decimal(deal.swap, "swap"),
                _finite_decimal(deal.fee, "fee"),
            ),
            Decimal(0),
        )
        if signed_volume == 0 and index < len(ordered) - 1:
            reached_zero_before_end = True

    observed_magics = tuple(sorted({deal.magic_number for deal in ordered}, key=int))
    nonzero_magics = {magic for magic in observed_magics if magic != ZERO_IDENTIFIER}
    exclusions: list[CycleExclusion] = []

    inconsistent = evidence_complete and (reached_zero_before_end or inconsistent_transition)
    if inconsistent:
        lifecycle = CycleLifecycle.INCONSISTENT
        exclusions.append(CycleExclusion.INCONSISTENT_LIFECYCLE)
    elif not evidence_complete:
        lifecycle = CycleLifecycle.INCOMPLETE
        exclusions.append(CycleExclusion.INCOMPLETE_EVIDENCE)
    elif signed_volume != 0:
        lifecycle = CycleLifecycle.OPEN
        exclusions.append(CycleExclusion.OPEN_POSITION)
    else:
        lifecycle = CycleLifecycle.CLOSED

    if owner_magic is None:
        exclusions.append(CycleExclusion.UNATTRIBUTED_OWNER)
    if ZERO_IDENTIFIER in observed_magics:
        # Magic 0 is enough to make autonomous attribution unsafe, but not to
        # claim manual intervention without order/deal reason evidence.
        exclusions.append(CycleExclusion.UNATTRIBUTED_ACTION)
    if len(nonzero_magics) > 1:
        exclusions.append(CycleExclusion.MIXED_MAGIC)

    return PositionCycle(
        account_id=key[0],
        position_id=key[1],
        owner_magic=owner_magic,
        observed_magics=observed_magics,
        started_at_msc=first.time_msc,
        last_event_at_msc=ordered[-1].time_msc,
        lifecycle=lifecycle,
        remaining_signed_volume=signed_volume,
        observed_net_result=net_result,
        deal_tickets=tuple(deal.ticket for deal in ordered),
        exclusions=tuple(dict.fromkeys(exclusions)),
    )


def _validate_deal(deal: DealForPositionCycle) -> None:
    if not isinstance(deal.account_id, str) or not deal.account_id:
        raise ValueError("account_id inválido")
    for value, label, allow_zero in (
        (deal.ticket, "ticket", False),
        (deal.position_id, "position_id", True),
    ):
        if (
            not isinstance(value, str)
            or not value.isdecimal()
            or (not allow_zero and int(value) == 0)
        ):
            raise ValueError(f"{label} inválido")
    if not isinstance(deal.magic_number, str):
        raise ValueError("magic_number inválido")
    try:
        int(deal.magic_number)
    except ValueError as exc:
        raise ValueError("magic_number inválido") from exc
    if not isinstance(deal.time_msc, int) or isinstance(deal.time_msc, bool) or deal.time_msc < 0:
        raise ValueError("Hora de deal inválida")
    if (
        not isinstance(deal.deal_type, int)
        or isinstance(deal.deal_type, bool)
        or deal.deal_type not in range(18)
    ):
        raise ValueError("Tipo de deal MT5 inválido")
    if (
        not isinstance(deal.entry, int)
        or isinstance(deal.entry, bool)
        or deal.entry not in range(4)
    ):
        raise ValueError("Tipo de entrada MT5 inválido")
    volume = _finite_decimal(deal.volume, "volumen")
    if volume < 0:
        raise ValueError("El volumen no puede ser negativo")
    for value, label in (
        (deal.profit, "profit"),
        (deal.commission, "commission"),
        (deal.swap, "swap"),
        (deal.fee, "fee"),
    ):
        _finite_decimal(value, label)


def _validate_commercial_deal(deal: DealForPositionCycle) -> None:
    if _finite_decimal(deal.volume, "volumen") <= 0:
        raise ValueError("El volumen comercial debe ser positivo")


def _entry_transition_is_consistent(previous: Decimal, change: Decimal, entry: int) -> bool:
    if entry == ENTRY_IN:
        return previous == 0 or (previous > 0) == (change > 0)
    if previous == 0 or (previous > 0) == (change > 0):
        return False
    if entry in {1, 3}:
        return abs(change) <= abs(previous)
    if entry == 2:
        return abs(change) > abs(previous)
    return False


def _finite_decimal(value: float, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} inválido")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"{label} debe ser finito")
    return result

from __future__ import annotations

import unittest
from dataclasses import dataclass
from decimal import Decimal

from tradinglab.metrics.position_cycles import (
    CycleExclusion,
    CycleLifecycle,
    reconstruct_position_cycles,
)


@dataclass(frozen=True)
class Deal:
    account_id: str
    ticket: str
    position_id: str
    magic_number: str
    time_msc: int
    deal_type: int
    entry: int
    volume: float
    profit: float = 0
    commission: float = 0
    swap: float = 0
    fee: float = 0


def deal(
    ticket: int,
    *,
    position: int = 10,
    magic: int = 11122,
    time: int | None = None,
    deal_type: int = 0,
    entry: int = 0,
    volume: float = 0.1,
    account: str = "account-a",
    profit: float = 0,
    commission: float = 0,
    swap: float = 0,
    fee: float = 0,
) -> Deal:
    return Deal(
        account_id=account,
        ticket=str(ticket),
        position_id=str(position),
        magic_number=str(magic),
        time_msc=ticket if time is None else time,
        deal_type=deal_type,
        entry=entry,
        volume=volume,
        profit=profit,
        commission=commission,
        swap=swap,
        fee=fee,
    )


class PositionCycleTest(unittest.TestCase):
    def test_complete_single_ea_cycle_is_eligible_and_includes_all_costs(self) -> None:
        selection = reconstruct_position_cycles(
            (
                deal(1, commission=-1),
                deal(2, deal_type=1, entry=1, profit=12, swap=-2, fee=-0.5),
            ),
            coverage_confirmed={("account-a", "10")},
        )

        cycle = selection.cycles[0]
        self.assertEqual(cycle.lifecycle, CycleLifecycle.CLOSED)
        self.assertEqual(cycle.owner_magic, "11122")
        self.assertEqual(cycle.observed_magics, ("11122",))
        self.assertEqual(cycle.observed_net_result, Decimal("8.5"))
        self.assertEqual(cycle.definitive_net_result, Decimal("8.5"))
        self.assertTrue(cycle.eligible_for_autonomous_metrics)

    def test_multiple_entries_and_partial_exits_form_one_definitive_cycle(self) -> None:
        selection = reconstruct_position_cycles(
            (
                deal(4, deal_type=1, entry=1, volume=0.1, profit=3),
                deal(1, volume=0.1),
                deal(3, deal_type=1, entry=1, volume=0.1, profit=-2),
                deal(2, volume=0.1),
            ),
            coverage_confirmed={("account-a", "10")},
        )

        cycle = selection.cycles[0]
        self.assertEqual(cycle.deal_tickets, ("1", "2", "3", "4"))
        self.assertEqual(cycle.remaining_signed_volume, Decimal(0))
        self.assertEqual(cycle.definitive_net_result, Decimal(1))

    def test_open_and_unconfirmed_cycles_never_produce_definitive_results(self) -> None:
        open_cycle = reconstruct_position_cycles(
            (deal(1),), coverage_confirmed={("account-a", "10")}
        ).cycles[0]
        incomplete_cycle = reconstruct_position_cycles(
            (deal(1), deal(2, deal_type=1, entry=1)), coverage_confirmed=set()
        ).cycles[0]

        self.assertEqual(open_cycle.lifecycle, CycleLifecycle.OPEN)
        self.assertIn(CycleExclusion.OPEN_POSITION, open_cycle.exclusions)
        self.assertIsNone(open_cycle.definitive_net_result)
        self.assertEqual(incomplete_cycle.lifecycle, CycleLifecycle.INCOMPLETE)
        self.assertIn(CycleExclusion.INCOMPLETE_EVIDENCE, incomplete_cycle.exclusions)
        self.assertIsNone(incomplete_cycle.definitive_net_result)

    def test_unattributed_or_other_ea_actions_exclude_the_whole_position(self) -> None:
        unattributed = reconstruct_position_cycles(
            (deal(1), deal(2, magic=0, deal_type=1, entry=1)),
            coverage_confirmed={("account-a", "10")},
        ).cycles[0]
        mixed = reconstruct_position_cycles(
            (deal(1), deal(2, magic=22222), deal(3, magic=22222, deal_type=1, entry=1, volume=0.2)),
            coverage_confirmed={("account-a", "10")},
        ).cycles[0]

        self.assertIn(CycleExclusion.UNATTRIBUTED_ACTION, unattributed.exclusions)
        self.assertIsNone(unattributed.definitive_net_result)
        self.assertIn(CycleExclusion.MIXED_MAGIC, mixed.exclusions)
        self.assertEqual(mixed.observed_magics, ("11122", "22222"))
        self.assertIsNone(mixed.definitive_net_result)

    def test_same_position_number_is_isolated_by_account(self) -> None:
        selection = reconstruct_position_cycles(
            (
                deal(1, account="account-a"),
                deal(2, account="account-a", deal_type=1, entry=1),
                deal(1, account="account-b", magic=22222),
                deal(2, account="account-b", magic=22222, deal_type=1, entry=1),
            ),
            coverage_confirmed={("account-a", "10"), ("account-b", "10")},
        )

        self.assertEqual(len(selection.cycles), 2)
        self.assertEqual(
            {(cycle.account_id, cycle.owner_magic) for cycle in selection.cycles},
            {("account-a", "11122"), ("account-b", "22222")},
        )

    def test_reversal_can_only_finish_when_the_position_returns_to_zero(self) -> None:
        selection = reconstruct_position_cycles(
            (
                deal(1, volume=0.1),
                deal(2, deal_type=1, entry=2, volume=0.2, profit=4),
                deal(3, deal_type=0, entry=1, volume=0.1, profit=-1),
            ),
            coverage_confirmed={("account-a", "10")},
        )

        cycle = selection.cycles[0]
        self.assertEqual(cycle.lifecycle, CycleLifecycle.CLOSED)
        self.assertEqual(cycle.definitive_net_result, Decimal(3))

    def test_impossible_entry_transition_is_not_eligible(self) -> None:
        cycle = reconstruct_position_cycles(
            (
                deal(1, volume=0.1),
                deal(2, deal_type=1, entry=1, volume=0.2),
                deal(3, deal_type=0, entry=1, volume=0.1),
            ),
            coverage_confirmed={("account-a", "10")},
        ).cycles[0]

        self.assertEqual(cycle.lifecycle, CycleLifecycle.INCONSISTENT)
        self.assertIn(CycleExclusion.INCONSISTENT_LIFECYCLE, cycle.exclusions)
        self.assertIsNone(cycle.definitive_net_result)

    def test_ignores_noncommercial_and_positionless_deals_but_rejects_duplicates(self) -> None:
        selection = reconstruct_position_cycles(
            (
                deal(1, deal_type=2, position=0, volume=0, profit=100),
                deal(2, position=0),
            ),
            coverage_confirmed=set(),
        )
        self.assertEqual(selection.cycles, ())
        self.assertEqual(selection.ignored_noncommercial_deals, 1)
        self.assertEqual(selection.ignored_without_position, 1)

        with self.assertRaisesRegex(ValueError, "duplicado"):
            reconstruct_position_cycles((deal(3), deal(3)), coverage_confirmed=set())

        with self.assertRaisesRegex(ValueError, "Tipo de deal"):
            reconstruct_position_cycles((deal(4, deal_type=18),), coverage_confirmed=set())


if __name__ == "__main__":
    unittest.main()

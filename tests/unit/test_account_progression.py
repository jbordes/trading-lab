from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.account_progression import (  # noqa: E402
    BalanceAnchor,
    LedgerMovement,
    project_account_progression,
)


def movement(
    at: int, kind: int, profit: str, commission: str = "0", fee: str = "0"
) -> LedgerMovement:
    return LedgerMovement(at, kind, Decimal(profit), Decimal(commission), fee=Decimal(fee))


class AccountProgressionTest(unittest.TestCase):
    def project(self, movements=(), **overrides):
        arguments = {"from_msc": 0, "to_msc": 240000, "complete_ranges": ((0, 400000),)}
        arguments.update(overrides)
        return project_account_progression(movements, **arguments)

    def test_deposits_credit_costs_and_anchor_are_not_trading_profit(self) -> None:
        result = self.project(
            [
                movement(1000, 2, "1000"),
                movement(2000, 0, "100", "-5", "-1"),
                movement(5000, 3, "500"),
                movement(8000, 7, "-3"),
                movement(250000, 1, "10"),
            ],
            anchor=BalanceAnchor(300000, Decimal("1101")),
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["balance_status"], "available")
        self.assertEqual(result["points"][-1]["realized_pnl"], 91)
        self.assertEqual(result["points"][-1]["net_cash_flow"], 1000)
        self.assertEqual(result["points"][-1]["balance"], 1091)
        self.assertNotIn("equity", result["points"][-1])

    def test_missing_reference_still_allows_pnl_and_corrections_stay_separate(self) -> None:
        result = self.project(
            [movement(1000, 5, "50"), movement(2000, 6, "10"), movement(3000, 1, "-4")]
        )
        self.assertEqual(result["balance_status"], "missing_anchor")
        point = result["points"][-1]
        self.assertEqual(
            (point["realized_pnl"], point["net_cash_flow"], point["adjustments"]), (-4, 10, 50)
        )
        self.assertIsNone(point["balance"])

    def test_gaps_and_absent_coverage_do_not_become_zero_profit(self) -> None:
        empty = self.project(complete_ranges=())
        self.assertEqual(empty["status"], "partial")
        self.assertTrue(all(row["realized_pnl"] is None for row in empty["points"]))
        gap = self.project([movement(1000, 1, "3")], complete_ranges=((0, 60000), (120000, 400000)))
        self.assertEqual(gap["points"][0]["realized_pnl"], 3)
        self.assertTrue(all(row["realized_pnl"] is None for row in gap["points"][1:]))

    def test_older_requested_period_starts_pnl_at_first_actual_coverage(self) -> None:
        result = self.project(
            [movement(30000, 1, "5"), movement(65000, 1, "10")],
            complete_ranges=((60000, 400000),),
            anchor=BalanceAnchor(300000, Decimal("110")),
        )
        self.assertEqual(result["pnl_from_server_msc"], "60000")
        self.assertIsNone(result["points"][0]["realized_pnl"])
        self.assertEqual(result["points"][-1]["realized_pnl"], 10)
        self.assertEqual(result["points"][-1]["balance"], 110)

    def test_second_resolution_anchor_is_rejected_if_a_deal_occurs_in_that_second(self) -> None:
        result = self.project(
            [movement(300123, 1, "10")], anchor=BalanceAnchor(300000, Decimal("110"))
        )
        self.assertEqual(result["balance_status"], "ambiguous_anchor")
        self.assertTrue(all(row["balance"] is None for row in result["points"]))

    def test_reference_before_period_end_does_not_extrapolate_future_balance(self) -> None:
        result = self.project(
            [movement(1000, 1, "10"), movement(200000, 1, "5")],
            anchor=BalanceAnchor(180000, Decimal("110")),
        )
        self.assertEqual(result["balance_status"], "available")
        self.assertEqual(result["points"][0]["balance"], 110)
        self.assertIsNone(result["points"][-1]["balance"])
        self.assertEqual(result["points"][-1]["realized_pnl"], 15)

    def test_cancelled_deals_and_conflicts_require_reconciliation(self) -> None:
        for options in ({"movements": [movement(1000, 13, "0")]}, {"conflicts": True}):
            result = self.project(**options)
            self.assertEqual(result["status"], "partial")
            self.assertTrue(all(row["realized_pnl"] is None for row in result["points"]))

    def test_decimal_aggregation_and_bounded_memory(self) -> None:
        result = self.project([movement(i, 1, "0.1") for i in range(3)])
        self.assertEqual(result["points"][-1]["realized_pnl"], 0.3)
        year = self.project(to_msc=366 * 86400000)
        self.assertLessEqual(len(year["points"]), 480)

    def test_invalid_ranges_and_nonfinite_amounts_are_explicit_errors(self) -> None:
        for args in ({"from_msc": True}, {"to_msc": 367 * 86400000}, {"to_msc": 0}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.project(**args)
        with self.assertRaises(ValueError):
            self.project([movement(1000, 1, "NaN")])
        with self.assertRaises(ValueError):
            self.project([movement(1000, 1, "1e308"), movement(2000, 1, "1e308")])


if __name__ == "__main__":
    unittest.main()

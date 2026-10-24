from __future__ import annotations

import unittest
from dataclasses import dataclass
from decimal import Decimal

from tradinglab.metrics.workbook_v1 import (
    FORMULA_VERSION,
    calculate_closed_deal_metrics,
    calculate_workbook_metrics,
)


@dataclass(frozen=True)
class Deal:
    ticket: str
    time_msc: int
    deal_type: int
    entry: int
    profit: float
    commission: float = 0
    swap: float = 0
    fee: float = 0


class WorkbookMetricsTest(unittest.TestCase):
    def test_selects_only_commercial_exits_and_includes_every_cost(self) -> None:
        selection = calculate_closed_deal_metrics(
            (
                Deal("4", 400, 2, 1, 500),
                Deal("3", 300, 1, 1, -20, commission=-1, swap=-2, fee=-3),
                Deal("1", 100, 0, 0, 0, commission=-0.5),
                Deal("2", 200, 0, 1, 10, commission=-1),
            )
        )

        self.assertEqual([result.ticket for result in selection.closed_results], ["2", "3"])
        self.assertEqual(
            [result.net_profit for result in selection.closed_results],
            [Decimal("9"), Decimal("-26")],
        )
        self.assertEqual(selection.metrics.net_profit, Decimal("-17"))
        self.assertEqual(selection.source_deal_count, 4)
        self.assertEqual(selection.ignored_opening_deals, 1)
        self.assertEqual(selection.ignored_non_trade_deals, 1)

    def test_matches_partner_workbook_observed_on_2026_10_24(self) -> None:
        values = tuple(
            Decimal(value)
            for value in (
                "48.28",
                "-191.17",
                "-189.27",
                "22.55",
                "130.33",
                "21.28",
                "150.83",
                "-64.87",
                "-194.47",
                "-187.22",
                "297.08",
                "62.53",
                "99.53",
                "-190.12",
                "5.33",
                "60.18",
            )
        )

        result = calculate_workbook_metrics(values)

        self.assertEqual(result.formula_version, FORMULA_VERSION)
        self.assertEqual(result.trade_count, 16)
        self.assertEqual(result.net_profit, Decimal("-119.20"))
        self.assertAlmostEqual(float(result.profit_factor), 0.8828063551989932)
        self.assertEqual(result.winning_percentage, Decimal("0.625"))
        self.assertEqual(result.average_trade, Decimal("-7.45"))
        self.assertEqual(result.maximum_drawdown, Decimal("502.01"))
        self.assertEqual(result.maximum_drawdown_percentage, Decimal("0.0050201"))
        self.assertEqual(result.current_drawdown, Decimal("167.48"))
        self.assertAlmostEqual(float(result.current_drawdown_percentage), 0.0016739917967604832)
        self.assertAlmostEqual(float(result.return_drawdown_ratio), -0.23744546921376297)
        self.assertEqual(result.expectancy_r, Decimal("-0.03725"))
        self.assertAlmostEqual(float(result.standard_deviation), 149.09848847881278)
        self.assertEqual(
            result.cumulative_profit[:3], (Decimal("48.28"), Decimal("-142.89"), Decimal("-332.16"))
        )
        self.assertEqual(
            result.drawdown_curve[:3], (Decimal("0"), Decimal("191.17"), Decimal("380.44"))
        )
        self.assertEqual(result.rolling_average_20[:2], (Decimal("48.28"), Decimal("-71.445")))

    def test_empty_and_single_result_have_explicit_unavailable_metrics(self) -> None:
        empty = calculate_workbook_metrics(())
        self.assertEqual(empty.trade_count, 0)
        self.assertEqual(empty.net_profit, Decimal(0))
        self.assertIsNone(empty.profit_factor)
        self.assertIsNone(empty.winning_percentage)
        self.assertIsNone(empty.average_trade)
        self.assertIsNone(empty.return_drawdown_ratio)
        self.assertIsNone(empty.expectancy_r)
        self.assertIsNone(empty.standard_deviation)

        single = calculate_workbook_metrics((Decimal("10"),))
        self.assertIsNone(single.profit_factor)
        self.assertIsNone(single.standard_deviation)
        self.assertEqual(single.winning_percentage, Decimal(1))

    def test_rejects_invalid_results_and_parameters(self) -> None:
        for value in (Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finitos"):
                calculate_workbook_metrics((value,))
        with self.assertRaisesRegex(ValueError, "capital"):
            calculate_workbook_metrics((), reference_capital=Decimal(0))
        with self.assertRaisesRegex(ValueError, "riesgo"):
            calculate_workbook_metrics((), risk_amount=Decimal("NaN"))


if __name__ == "__main__":
    unittest.main()

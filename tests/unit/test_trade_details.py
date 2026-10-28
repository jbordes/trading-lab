from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from tradinglab.metrics.position_cycles import reconstruct_position_cycles
from tradinglab.metrics.trade_details import trade_details


class TradeDetailsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(
            (
                Path(__file__).parents[1] / "fixtures/telemetry_v2/activity-position-reconcile.json"
            ).read_text(encoding="utf-8")
        )["payload"]

    def result(self) -> dict[str, object]:
        deals = [
            SimpleNamespace(
                **(row | {"account_id": "account-demo", "time_msc": int(row["time_msc"])})
            )
            for row in self.payload["deals"]["items"]
        ]
        cycle = reconstruct_position_cycles(
            deals,
            coverage_confirmed={("account-demo", deals[0].position_id)},
        ).cycles[0]
        return trade_details(cycle, self.payload)

    def test_long_uses_entry_direction_and_preserves_costs(self) -> None:
        result = self.result()
        self.assertEqual(result["side"], "long")
        self.assertEqual(result["open_price"], 4200)
        self.assertEqual(result["close_price"], 4210)
        self.assertEqual(result["gross_profit"], 10)
        self.assertEqual(result["commission"], -0.2)
        self.assertEqual(result["levels_basis"], "initial_order")
        self.assertEqual(result["take_profit"], 4240)
        self.assertIsNone(result["pips"])
        self.assertAlmostEqual(result["duration_hours"], 24 + 1 / 60)

    def test_short_with_exit_levels_and_fees(self) -> None:
        first, last = self.payload["deals"]["items"]
        first["deal_type"], last["deal_type"] = 1, 0
        last["fee"], last["swap"] = -0.3, -2
        self.payload["orders"]["items"][-1]["stop_loss"] = 4220
        result = self.result()
        self.assertEqual(result["side"], "short")
        self.assertEqual(result["fee"], -0.3)
        self.assertEqual(result["swap"], -2)
        self.assertEqual(result["levels_basis"], "exit_order")
        self.assertEqual(result["stop_loss"], 4220)

    def test_partial_closes_use_volume_weighted_prices(self) -> None:
        first, last = self.payload["deals"]["items"]
        first["volume"] = 0.04
        extra = last | {"ticket": "700000000000000003", "volume": 0.03, "price": 4220}
        self.payload["deals"]["items"].append(extra)
        result = self.result()
        self.assertEqual(result["volume"], 0.04)
        self.assertEqual(result["close_price"], 4217.5)

    def test_multiple_entries_use_volume_weighted_prices(self) -> None:
        first, last = self.payload["deals"]["items"]
        extra = first | {"ticket": "700000000000000003", "volume": 0.03, "price": 4210}
        last["volume"] = 0.04
        self.payload["deals"]["items"].append(extra)
        result = self.result()
        self.assertEqual(result["open_price"], 4207.5)
        self.assertEqual(result["volume"], 0.04)

    def test_reversal_does_not_invent_a_single_direction_or_price(self) -> None:
        self.payload["deals"]["items"][-1]["entry"] = 2
        result = self.result()
        self.assertIsNone(result["side"])
        self.assertIsNone(result["open_price"])

    def test_missing_orders_have_unknown_levels(self) -> None:
        self.payload["orders"]["items"] = []
        result = self.result()
        self.assertEqual(result["levels_basis"], "unknown")
        self.assertIsNone(result["take_profit"])


if __name__ == "__main__":
    unittest.main()

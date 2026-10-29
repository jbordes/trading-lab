from __future__ import annotations

import json
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from tradinglab.dashboard.telemetry_v2 import LoopbackV2HistoryClient, V2HistoryProvider
from tradinglab.metrics.position_cycles import CycleExclusion
from tradinglab.telemetry.admission_v2 import ProducerIdentity
from tradinglab.telemetry.ingest_v2 import create_v2_telemetry_server
from tradinglab.telemetry.persistent_receiver_v2 import PersistentV2TelemetryReceiver
from tradinglab.telemetry.provisioning_v2 import V2ProvisionPlan

FIXTURES = Path(__file__).parents[1] / "fixtures" / "telemetry_v2"
LIVE_AUTHORIZATION = "synthetic-live-authorization-safe-length"
ACTIVITY_AUTHORIZATION = "synthetic-activity-authorization-safe-length"
READ_AUTHORIZATION = "synthetic-read-authorization-safe-length"


class DashboardTelemetryV2Test(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = V2ProvisionPlan(
            Path(temporary.name),
            "pilot.sqlite3",
            "account-demo",
            "Demo",
            ProducerIdentity("****1234", "DEMO-SERVER", "USD"),
            "synthetic-live",
            "synthetic-activity",
        ).apply(clock=datetime(2026, 10, 25, 10, tzinfo=UTC))
        self.backend = PersistentV2TelemetryReceiver(
            database,
            account_id="account-demo",
            live_authorization=LIVE_AUTHORIZATION,
            activity_authorization=ACTIVITY_AUTHORIZATION,
            clock=lambda: datetime(2026, 10, 25, 11, tzinfo=UTC),
        )
        self.server = create_v2_telemetry_server(
            self.backend,
            port=0,
            read_authorization=READ_AUTHORIZATION,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        body = (FIXTURES / "activity-truncated.json").read_bytes()
        self.backend.accept(body, f"Bearer {ACTIVITY_AUTHORIZATION}")

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.backend.close()

    def client(self) -> LoopbackV2HistoryClient:
        return LoopbackV2HistoryClient(
            read_authorization=READ_AUTHORIZATION,
            activity_source_id="synthetic-activity",
            port=self.server.server_port,
        )

    def test_recovered_deal_and_coverage_reach_dashboard_shape(self) -> None:
        page = self.client().deal_history(
            from_msc=1792656000000,
            to_msc=1792656060001,
            magic_number="11122",
        )

        self.assertEqual(page.account_id, "account-demo")
        self.assertEqual(page.deals[0].ticket, "900000000000000002")
        self.assertEqual(page.deals[0].profit, -2)
        self.assertEqual(
            page.coverage,
            {"complete_ranges": [], "incomplete_batches": 1},
        )

    def test_existing_metric_formula_uses_recovered_v2_deals(self) -> None:
        result = V2HistoryProvider(self.client()).performance_metrics(
            from_msc=1792656000000,
            to_msc=1792656060001,
            magic_number="11122",
        )

        self.assertEqual(result.selection.metrics.trade_count, 1)
        self.assertEqual(float(result.selection.metrics.net_profit), -2.1)

    def test_canceled_order_reaches_validated_dashboard_shape(self) -> None:
        document = json.loads((FIXTURES / "activity-canceled-order.json").read_bytes())
        document["session_id"] = "synthetic-order-session"
        document["event_id"] = "synthetic-order-session:1"
        self.backend.accept(
            json.dumps(document, separators=(",", ":")).encode(),
            f"Bearer {ACTIVITY_AUTHORIZATION}",
        )

        page = V2HistoryProvider(self.client()).order_history(
            from_msc=1792656000000,
            to_msc=1792656060001,
            magic_number="11122",
        )

        self.assertEqual(page.account_id, "account-demo")
        self.assertEqual(page.source_id, "synthetic-activity")
        self.assertIsNone(page.next_cursor)
        order = page.orders[0]
        self.assertEqual(order.ticket, "900000000000000001")
        self.assertEqual(order.state, 2)
        self.assertEqual(order.position_id, "0")
        self.assertEqual(page.coverage["incomplete_batches"], 0)

    def test_reconciled_position_cycle_reaches_validated_dashboard_shape(self) -> None:
        body = (FIXTURES / "activity-position-reconcile.json").read_bytes()
        self.backend.accept(body, f"Bearer {ACTIVITY_AUTHORIZATION}")

        page = V2HistoryProvider(self.client()).position_cycles(owner_magic="11122")

        self.assertEqual(page.account_id, "account-demo")
        self.assertEqual(page.source_id, "synthetic-activity")
        self.assertEqual(page.owner_magic, "11122")
        self.assertIsNone(page.next_cursor)
        cycle = page.cycles[0].cycle
        self.assertEqual(cycle.position_id, "600000000000000001")
        self.assertEqual(str(cycle.observed_net_result), "9.8")
        self.assertTrue(cycle.eligible_for_autonomous_metrics)
        self.assertEqual(page.cycles[0].details["side"], "long")
        self.assertEqual(page.cycles[0].details["open_price"], 4200)
        self.assertEqual(page.cycles[0].as_dict()["details"]["gross_profit"], 10)
        multi = V2HistoryProvider(self.client()).position_cycles(owner_magics=("11122", "99999"))
        self.assertEqual(multi.cycles, page.cycles)
        self.assertEqual(self.client().position_cycle_magics(), ("11122",))

    def test_rejects_invalid_trade_details(self) -> None:
        self.backend.accept(
            (FIXTURES / "activity-position-reconcile.json").read_bytes(),
            f"Bearer {ACTIVITY_AUTHORIZATION}",
        )
        client = self.client()
        details = client.position_cycles().cycles[0].details
        for changes in (
            {"gross_profit": float("nan")},
            {"opening_tickets": ["not-a-ticket"]},
            {"side": "invented"},
            {"symbol": "\x00"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                client._trade_details(details | changes)

    def test_closed_cycle_metrics_use_reconciled_operations(self) -> None:
        body = (FIXTURES / "activity-position-reconcile.json").read_bytes()
        self.backend.accept(body, f"Bearer {ACTIVITY_AUTHORIZATION}")
        provider = V2HistoryProvider(self.client())

        page = provider.position_cycles(
            owner_magic="11122",
            from_msc=1792656000000,
            to_msc=1792656060001,
            closed_only=True,
        )
        performance = provider.cycle_performance_metrics(
            owner_magic="11122",
            from_msc=1792656000000,
            to_msc=1792656060001,
        ).as_dict()

        self.assertEqual(len(page.cycles), 1)
        self.assertEqual(performance["formula_version"], "position-cycle-v1")
        self.assertEqual(performance["trade_count"], 1)
        self.assertAlmostEqual(performance["net_profit"], 9.8)
        self.assertEqual(performance["coverage"]["incomplete_batches"], 1)
        self.assertEqual(len(performance["by_ea"]), 1)
        self.assertEqual(performance["by_ea"][0]["magic_number"], "11122")
        self.assertEqual(performance["by_ea"][0]["net_profit"], 9.8)

    def test_ea_comparison_separates_results_and_excludes_interventions(self) -> None:
        body = (FIXTURES / "activity-position-reconcile.json").read_bytes()
        self.backend.accept(body, f"Bearer {ACTIVITY_AUTHORIZATION}")
        performance = V2HistoryProvider(self.client()).cycle_performance_metrics(
            from_msc=1792656000000, to_msc=1792656060001
        )
        first = performance.cycles[0]

        def variation(magic: str, pnl: str, position: str):
            return replace(
                first,
                cycle=replace(
                    first.cycle,
                    position_id=position,
                    owner_magic=magic,
                    observed_net_result=Decimal(pnl),
                    last_event_at_msc=first.cycle.last_event_at_msc + int(position),
                ),
            )

        loss = variation("11122", "-5", "1")
        other = variation("22222", "20", "2")
        excluded = variation("11122", "1000", "3")
        excluded = replace(
            excluded, cycle=replace(excluded.cycle, exclusions=(CycleExclusion.MIXED_MAGIC,))
        )
        result = replace(performance, cycles=(other, excluded, loss, first)).as_dict()
        groups = {item["magic_number"]: item for item in result["by_ea"]}
        self.assertEqual(set(groups), {"11122", "22222"})
        self.assertEqual(groups["11122"]["trade_count"], 2)
        self.assertEqual(groups["11122"]["net_profit"], 4.8)
        self.assertEqual(groups["11122"]["maximum_drawdown"], 5)
        self.assertEqual(groups["11122"]["series"][-1]["cumulative_profit"], 4.8)
        self.assertEqual(groups["11122"]["series"][-1]["net_profit"], -5)
        self.assertEqual(groups["11122"]["series"][-1]["drawdown"], 5)
        self.assertEqual(groups["11122"]["series"][-1]["rolling_average_20"], 2.4)
        self.assertEqual(groups["22222"]["net_profit"], 20)
        self.assertEqual(groups["22222"]["maximum_drawdown"], 0)
        self.assertAlmostEqual(
            sum(item["net_profit"] for item in groups.values()), result["net_profit"]
        )
        self.assertEqual(replace(performance, cycles=()).as_dict()["by_ea"], [])
        subset = replace(performance, cycles=(other, excluded, loss, first)).as_dict(
            selected_magics=("11122",)
        )
        self.assertEqual(subset["trade_count"], 2)
        self.assertEqual(subset["net_profit"], 4.8)
        self.assertEqual(subset["profit_factor"], 1.96)
        self.assertEqual(subset["available_magics"], ["11122", "22222"])
        self.assertEqual(subset["selected_magics"], ["11122"])
        self.assertEqual(len(subset["by_ea"]), 1)
        self.assertEqual(performance.as_dict(selected_magics=("999",))["trade_count"], 0)


if __name__ == "__main__":
    unittest.main()

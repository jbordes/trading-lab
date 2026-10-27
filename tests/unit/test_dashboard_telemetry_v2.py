from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tradinglab.dashboard.telemetry_v2 import LoopbackV2HistoryClient, V2HistoryProvider
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


if __name__ == "__main__":
    unittest.main()

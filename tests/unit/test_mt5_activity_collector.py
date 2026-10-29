from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "apps/mt5-telemetry-collector/TradingLabActivity.mq5"


class Mql5ActivityCollectorSafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.normalized = cls.source.casefold().replace(" ", "")

    def test_source_is_read_only_loopback_v2(self) -> None:
        for pattern in ("ordersend(", "ctrade", "#import", "positionclose(", "orderdelete("):
            self.assertNotIn(pattern, self.normalized)
        self.assertIn('"http://127.0.0.1:8777/v2/telemetry"', self.source)
        self.assertIn("ACCOUNT_TRADE_MODE_DEMO", self.source)
        self.assertIn("login == expected_login && server == expected_server", self.source)
        self.assertIn("HistorySelect(", self.source)
        self.assertIn("HistoryOrderGetTicket(", self.source)
        self.assertIn("HistoryDealGetTicket(", self.source)

    def test_cursor_advances_only_after_receiver_ack(self) -> None:
        sender = self.source.split("bool TrySendPending", 1)[1].split("void ResetRetryState", 1)[0]
        success = sender.split("if(status == 200 || status == 202)", 1)[1]
        before_success = sender.split("if(status == 200 || status == 202)", 1)[0]
        self.assertNotIn("confirmed_from_msc =", before_success)
        self.assertIn("batch_waiting_for_positions = true", success)
        self.assertNotIn("confirmed_from_msc =", success)
        finalizer = self.source.split("bool FinalizeConfirmedBatch", 1)[1].split(
            "void ResetCandidatePositions", 1
        )[0]
        self.assertIn("PersistValue(selected_cursor_key, next_cursor)", finalizer)
        self.assertLess(
            finalizer.index("PersistValue(selected_cursor_key"),
            finalizer.index("confirmed_from_msc ="),
        )
        self.assertIn("pending_body", sender)

    def test_closed_position_evidence_precedes_cursor_advance(self) -> None:
        self.assertIn("HistorySelectByPosition((ulong)position_id)", self.source)
        self.assertIn("position_reconcile", self.source)
        self.assertIn("MathAbs(signed_volume) > 0.00000001", self.source)
        self.assertIn("has_opening_order", self.source)

        timer = self.source.split("void OnTimer()", 1)[1].split("void OnTradeTransaction", 1)[0]
        self.assertIn("ContinuePositionReconciliation()", timer)
        reconciler = self.source.split("void ContinuePositionReconciliation", 1)[1].split(
            "bool PersistValue", 1
        )[0]
        self.assertIn("BuildPositionReconcilePayload", reconciler)
        self.assertLess(
            reconciler.index("BuildPositionReconcilePayload"),
            reconciler.index("FinalizeConfirmedBatch"),
        )

    def test_saturation_splits_then_pages_without_early_cursor_advance(self) -> None:
        timer = self.source.split("void OnTimer()", 1)[1].split("void OnTradeTransaction", 1)[0]
        self.assertIn("while(true)", timer)
        self.assertIn("MinimumWindowSeconds", timer)
        self.assertIn("pending_blocks_recovery = truncated", timer)
        self.assertIn("BuildPagedActivityPayload", timer)
        self.assertIn("pagination_active", timer)
        sender = self.source.split("bool TrySendPending", 1)[1].split("bool PersistValue", 1)[0]
        blocked = sender.split("if(pending_blocks_recovery)", 1)[1].split("else", 1)[0]
        self.assertIn("PersistValue(selected_blocked_key, pending_from_msc)", blocked)
        self.assertIn("recovery_blocked = true", blocked)
        self.assertNotIn("confirmed_from_msc =", blocked)

    def test_unconfirmed_transport_failures_keep_same_batch(self) -> None:
        sender = self.source.split("bool TrySendPending", 1)[1].split("bool PersistValue", 1)[0]
        self.assertIn("retryable", sender)
        self.assertNotIn('pending_body = ""', sender.split("bool retryable", 1)[1])
        self.assertIn("StopForSafety()", sender)
        self.assertNotIn("Sleep(", self.source)

    def test_recent_capture_and_deep_recovery_have_independent_durable_cursors(self) -> None:
        self.assertIn('COLLECTOR_VERSION = "activity-0.5.0"', self.source)
        self.assertIn('recent_cursor_key = StringFormat("TL2.ACT.%08X.RECENT"', self.source)
        self.assertIn('recent_blocked_key = StringFormat("TL2.ACT.%08X.RBLOCK"', self.source)
        timer = self.source.split("void OnTimer()", 1)[1].split("void OnTradeTransaction", 1)[0]
        self.assertIn("bool recent_due", timer)
        self.assertIn("bool deep_due", timer)
        self.assertNotIn("CheckPilotSafety() || recovery_blocked", timer)
        self.assertIn("pending_is_recent = recent_due", timer)
        finalizer = self.source.split("bool FinalizeConfirmedBatch", 1)[1].split(
            "void ResetCandidatePositions", 1
        )[0]
        self.assertIn("selected_cursor_key", finalizer)
        self.assertIn("recent_confirmed_from_msc = next_cursor", finalizer)
        self.assertIn("confirmed_from_msc = next_cursor", finalizer)

    def test_trade_callback_only_enqueues_bounded_minimal_hints(self) -> None:
        callback = self.source.split("void OnTradeTransaction", 1)[1].split(
            "void EnqueueTransactionHint", 1
        )[0]
        self.assertIn("EnqueueTransactionHint(transaction)", callback)
        for forbidden in ("HistorySelect(", "SendMessage(", "Database", "FileWrite"):
            self.assertNotIn(forbidden, callback)
        enqueue = self.source.split("void EnqueueTransactionHint", 1)[1].split(
            "int DrainTransactionHints", 1
        )[0]
        self.assertIn("TRANSACTION_HINT_CAPACITY", enqueue)
        self.assertIn("transaction_hints_dropped++", enqueue)
        self.assertNotIn("ArrayResize", enqueue)
        self.assertIn("DrainTransactionHints()", self.source)

    def test_heartbeat_reports_progress_without_advancing_cursors(self) -> None:
        self.assertIn("BuildHeartbeatPayload", self.source)
        self.assertIn('"heartbeat"', self.source)
        heartbeat = self.source.split("string BuildHeartbeatPayload", 1)[1].split(
            "string BuildEnvelope", 1
        )[0]
        for field in (
            "recent_cursor_msc",
            "deep_cursor_msc",
            "backlog_msc",
            "recent_blocked",
            "deep_blocked",
            "queued_hints",
            "dropped_hints",
            "latest_deal_ticket",
            "latest_order_ticket",
            "latest_position_id",
        ):
            self.assertIn(field, heartbeat)
        self.assertNotIn("PersistValue", heartbeat)
        sender = self.source.split("bool TrySendPending", 1)[1].split("void ResetRetryState", 1)[0]
        heartbeat_ack = sender.split("if(pending_is_heartbeat)", 1)[1].split(
            "if(pending_is_position_reconcile)", 1
        )[0]
        self.assertNotIn("FinalizeConfirmedBatch", heartbeat_ack)
        self.assertNotIn("PersistValue", heartbeat_ack)

    def test_saturated_pages_use_stable_composite_keys_and_restart_changed_snapshot(self) -> None:
        pager = self.source.split("string BuildPagedActivityPayload", 1)[1].split(
            "string BuildHistoricalDeals", 1
        )[0]
        self.assertIn("CompareActivityPageKeys", pager)
        self.assertIn("time_msc", pager)
        self.assertIn("entity_type", pager)
        self.assertIn("ticket", pager)
        self.assertIn("remaining_count > key_count", pager)
        self.assertIn('page_status = has_more ? "partial" : "paged_complete"', pager)
        timer = self.source.split("void OnTimer()", 1)[1].split("void OnTradeTransaction", 1)[0]
        self.assertIn("pending_page_snapshot_id != pagination_snapshot_id", timer)
        self.assertIn("pagination_after.time_msc = 0", timer)
        finalizer = self.source.split("bool FinalizeConfirmedBatch", 1)[1].split(
            "int BuildPositionReconcilePayload", 1
        )[0]
        partial = finalizer.split("if(pending_is_paged && pending_page_has_more)", 1)[1]
        self.assertNotIn("PersistValue", partial.split("long next_cursor", 1)[0])


if __name__ == "__main__":
    unittest.main()

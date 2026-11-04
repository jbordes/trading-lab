from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "apps/mt5-telemetry-collector/TradingLabActivity.mq5"


class Mql5ActivityCollectorSafetyTest(unittest.TestCase):
    def test_all_collector_includes_remain_read_only(self) -> None:
        for path in SOURCE.parent.glob("*.mqh"):
            normalized = "".join(path.read_text(encoding="utf-8").casefold().split())
            for pattern in ("ordersend(", "ctrade", "#import", "positionclose(", "orderdelete("):
                self.assertNotIn(pattern, normalized, path.name)

    def test_preparation_and_reconciliation_have_bounded_work(self) -> None:
        self.assertIn("long candidate_position_ids[200]", self.source)
        adder = self.source.split("void AddCandidatePosition", 1)[1].split(
            "void ContinuePosition", 1
        )[0]
        self.assertNotIn("ArrayResize", adder)
        scanner = self.source.split("string BuildPagedActivityPayload", 1)[1].split(
            "string PagedCollectionJson", 1
        )[0]
        self.assertIn("processed >= MaxHistoryRowsPerCycle", scanner)
        self.assertIn("CycleBudgetMs", scanner)
        self.assertIn("page_scan.deal_index++", scanner)
        self.assertIn("page_scan.order_index++", scanner)
        self.assertNotIn("PersistValue", scanner)
        recon = self.source.split("void ContinuePositionReconciliation", 1)[1].split(
            "bool PersistValue", 1
        )[0]
        self.assertIn("processed++ < 2", recon)
        self.assertIn("CycleBudgetMs", recon)

    def test_partial_deep_pages_yield_to_recent_without_committing_range(self) -> None:
        finalizer = self.source.split("bool FinalizeConfirmedBatch", 1)[1].split(
            "int BuildPosition", 1
        )[0]
        partial = finalizer.split("long next_cursor", 1)[0]
        self.assertIn("saved_deep_page = pagination", partial)
        self.assertIn("saved_recent_page = pagination", partial)
        self.assertIn("prefer_recent = !pending.is_recent", partial)
        self.assertNotIn("PersistValue", partial)

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.common = (SOURCE.parent / "TradingLabCollectorCommon.mqh").read_text(encoding="utf-8")
        cls.normalized = (
            (
                cls.source
                + cls.common
                + (SOURCE.parent / "TradingLabActivityState.mqh").read_text(encoding="utf-8")
            )
            .casefold()
            .replace(" ", "")
        )

    def test_source_is_read_only_loopback_v2(self) -> None:
        for pattern in ("ordersend(", "ctrade", "#import", "positionclose(", "orderdelete("):
            self.assertNotIn(pattern, self.normalized)
        self.assertIn('"http://127.0.0.1:8777/v2/telemetry"', self.source)
        self.assertIn("ACCOUNT_TRADE_MODE_DEMO", self.common)
        self.assertIn("login == expected_login && server == expected_server", self.common)
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
        self.assertIn("pending.body", sender)

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
        self.assertNotIn("while(true)", timer)
        self.assertIn("preparation.active = true", timer)
        self.assertIn("MinimumWindowSeconds", timer)
        self.assertIn("pending.blocks_recovery = truncated", timer)
        self.assertIn("BuildPagedActivityPayload", timer)
        self.assertIn("pagination.active", timer)
        sender = self.source.split("bool TrySendPending", 1)[1].split("bool PersistValue", 1)[0]
        blocked = sender.split("if(pending.blocks_recovery)", 1)[1].split("else", 1)[0]
        self.assertIn("PersistValue(selected_blocked_key, pending.from_msc)", blocked)
        self.assertIn("recovery_blocked = true", blocked)
        self.assertNotIn("confirmed_from_msc =", blocked)

    def test_unconfirmed_transport_failures_keep_same_batch(self) -> None:
        sender = self.source.split("bool TrySendPending", 1)[1].split("bool PersistValue", 1)[0]
        self.assertIn("DELIVERY_ACCESS_BLOCKED", sender)
        self.assertIn("transport.Observe(status, now_ms)", sender)
        self.assertNotIn('pending.body = ""', sender.split("CollectorDelivery previous", 1)[1])
        self.assertIn("StopForSafety()", sender)
        self.assertNotIn("Sleep(", self.source)

    def test_recent_capture_and_deep_recovery_have_independent_durable_cursors(self) -> None:
        self.assertIn('COLLECTOR_VERSION = "activity-0.7.0"', self.source)
        self.assertIn('recent_cursor_key = StringFormat("TL2.ACT.%08X.RECENT"', self.source)
        self.assertIn('recent_blocked_key = StringFormat("TL2.ACT.%08X.RBLOCK"', self.source)
        timer = self.source.split("void OnTimer()", 1)[1].split("void OnTradeTransaction", 1)[0]
        self.assertIn("bool recent_due", timer)
        self.assertIn("bool deep_due", timer)
        self.assertNotIn("CheckPilotSafety() || recovery_blocked", timer)
        self.assertIn("pending.is_recent = recent_due", timer)
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
            "deep_paused",
            "queued_hints",
            "dropped_hints",
            "latest_deal_ticket",
            "latest_order_ticket",
            "latest_position_id",
        ):
            self.assertIn(field, heartbeat)
        self.assertNotIn("PersistValue", heartbeat)
        sender = self.source.split("bool TrySendPending", 1)[1].split("void ResetRetryState", 1)[0]
        heartbeat_ack = sender.split("if(pending.is_heartbeat)", 1)[1].split(
            "if(pending.is_position_reconcile)", 1
        )[0]
        self.assertNotIn("FinalizeConfirmedBatch", heartbeat_ack)
        self.assertNotIn("PersistValue", heartbeat_ack)

    def test_deep_recovery_can_pause_without_stopping_recent_capture(self) -> None:
        timer = self.source.split("void OnTimer()", 1)[1].split("void OnTradeTransaction", 1)[0]
        self.assertIn("EnableDeepRecovery && !recovery_blocked", timer)
        recent = timer.split("bool recent_due", 1)[1].split("bool deep_due", 1)[0]
        self.assertNotIn("EnableDeepRecovery", recent)
        self.assertIn("deep_paused", self.source)

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
        self.assertIn("pending.page_snapshot_id != pagination.snapshot_id", timer)
        self.assertIn("pagination.after.time_msc = 0", timer)
        finalizer = self.source.split("bool FinalizeConfirmedBatch", 1)[1].split(
            "int BuildPositionReconcilePayload", 1
        )[0]
        partial = finalizer.split("if(pending.is_paged && pending.page_has_more)", 1)[1]
        self.assertNotIn("PersistValue", partial.split("long next_cursor", 1)[0])


if __name__ == "__main__":
    unittest.main()

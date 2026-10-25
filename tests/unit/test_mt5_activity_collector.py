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
        sender = self.source.split("bool TrySendPending", 1)[1].split("bool PersistValue", 1)[0]
        success = sender.split("if(status == 200 || status == 202)", 1)[1]
        before_success = sender.split("if(status == 200 || status == 202)", 1)[0]
        self.assertNotIn("confirmed_from_msc =", before_success)
        self.assertIn("PersistValue(cursor_key, next_cursor)", success)
        self.assertLess(
            success.index("PersistValue(cursor_key"), success.index("confirmed_from_msc =")
        )
        self.assertIn("pending_body", sender)

    def test_saturation_splits_then_blocks_without_advancing(self) -> None:
        timer = self.source.split("void OnTimer()", 1)[1].split("void OnTradeTransaction", 1)[0]
        self.assertIn("while(true)", timer)
        self.assertIn("MinimumWindowSeconds", timer)
        self.assertIn("pending_blocks_recovery = truncated", timer)
        sender = self.source.split("bool TrySendPending", 1)[1].split("bool PersistValue", 1)[0]
        blocked = sender.split("if(pending_blocks_recovery)", 1)[1].split("else", 1)[0]
        self.assertIn("PersistValue(blocked_key, pending_from_msc)", blocked)
        self.assertIn("recovery_blocked = true", blocked)
        self.assertNotIn("confirmed_from_msc =", blocked)

    def test_unconfirmed_transport_failures_keep_same_batch(self) -> None:
        sender = self.source.split("bool TrySendPending", 1)[1].split("bool PersistValue", 1)[0]
        self.assertIn("retryable", sender)
        self.assertNotIn('pending_body = ""', sender.split("bool retryable", 1)[1])
        self.assertIn("StopForSafety()", sender)
        self.assertNotIn("Sleep(", self.source)


if __name__ == "__main__":
    unittest.main()

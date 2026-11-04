"""Source guards complement native logger tests; they do not execute MQL5."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLECTORS = ROOT / "apps/mt5-telemetry-collector"


class CollectorLoggingSourceTest(unittest.TestCase):
    def test_collectors_share_logger_without_logging_in_transaction_callback(self) -> None:
        for component in ("Telemetry", "Activity"):
            with self.subTest(component=component):
                source = (COLLECTORS / f"TradingLab{component}.mq5").read_text(encoding="utf-8")
                self.assertIn('#include "TradingLabCollectorLog.mqh"', source)
                self.assertIn(
                    f'logger.Configure("{component.lower()}", SourceId, COLLECTOR_VERSION)', source
                )
                callback = source.split("void OnTradeTransaction(", 1)[1].split("\n}\n", 1)[0]
                for forbidden in ("logger.", "File", "WebRequest(", "Print("):
                    self.assertNotIn(forbidden, callback)
                self.assertNotRegex(source, r"\bPrint(?:Format)?\(")
                self.assertNotRegex(source, r"logger\.\w+\([^;]*\bToken\b")
                self.assertIn('logger.Resolve("receiver_unavailable"', source)
                self.assertIn("last_request_error = GetLastError();", source)
                self.assertNotIn("receiver returned HTTP", source)

    def test_file_scope_quota_retention_and_bounded_work_are_explicit(self) -> None:
        source = (COLLECTORS / "TradingLabCollectorLog.mqh").read_text(encoding="utf-8")
        self.assertIn('FileOpen("TradingLab\\\\logs\\\\"', source)
        self.assertIn("1048576", source)
        self.assertIn("14 * 86400", source)
        self.assertIn("scanned < 64", source)
        self.assertIn("CollectorLogIncident incidents[32]", source)
        self.assertIn("OwnedOldFile(name, cutoff)", source)
        self.assertIn('FileDelete("TradingLab\\\\logs\\\\" + name)', source)
        self.assertNotIn("FILE_SHARE_WRITE", source)
        self.assertIn("IsSafeIdentifier(source_id)", source)
        self.assertIn('StringReplace(filename_source, ":", "~")', source)
        self.assertIn("retry_after_ms = now_ms + 60000", source)

    def test_only_errors_echo_and_details_are_bounded_and_escaped(self) -> None:
        source = (COLLECTORS / "TradingLabCollectorLog.mqh").read_text(encoding="utf-8")
        self.assertIn('if(level == "ERROR") Print(', source)
        self.assertIn("JsonEscape(Truncate(detail, 384))", source)
        self.assertIn("now - incidents[slot].last_written_ms < 60000", source)
        self.assertIn('Write("RESOLVED"', source)
        self.assertNotIn('Write("INFO"', source)

    def test_native_test_replaces_every_file_operation(self) -> None:
        source = (ROOT / "tests/mql5/collector_logger_test.mq5").read_text(encoding="utf-8")
        for operation in (
            "FileOpen",
            "FileSize",
            "FileSeek",
            "FileWriteArray",
            "FileFlush",
            "FileClose",
            "FileFindFirst",
            "FileFindNext",
            "FileFindClose",
            "FileDelete",
        ):
            self.assertIn(f"#define {operation} Fake", source)
        self.assertIn("#define TimeGMT FakeUtc", source)
        self.assertIn("#define GetTickCount64 FakeTicks", source)
        self.assertIn('PrintFormat("TradingLab logger tests: %d failure(s)", failures)', source)


if __name__ == "__main__":
    unittest.main()

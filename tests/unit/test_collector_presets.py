from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from tradinglab.collector_presets import create_presets
from tradinglab.installation_backend import LAYOUT


class CollectorPresetsTest(unittest.TestCase):
    def test_private_files_match_installed_contract_and_never_overwrite(self):
        config = SimpleNamespace(
            login_masked="****1234",
            server="Example",
            account_mode="real",
            snapshot_port=8876,
            activity_port=8877,
            snapshot_source_id="state",
            activity_source_id="activity",
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            names = (
                ("TRADINGLAB_TELEMETRY_TOKEN", "TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN")
                if LAYOUT == "local-dual-v1"
                else ("RELAY_LIVE_LOCAL_TOKEN", "RELAY_ACTIVITY_LOCAL_TOKEN")
            )
            filename = ".env.local" if LAYOUT == "local-dual-v1" else ".env.collectors"
            (directory / filename).write_text(f"{names[0]}={'a' * 32}\n{names[1]}={'b' * 32}\n")
            with patch("tradinglab.collector_presets.read_installation", return_value=config):
                for login, date in [("9999", "2026.01.01 00:00:00"), ("1234", "bad date")]:
                    with self.assertRaises(ValueError):
                        create_presets(directory, login, date)
                    self.assertFalse((directory / "collector-presets").exists())
                result = create_presets(directory, "1234", "2026.01.01 00:00:00")
                telemetry = (result / "TradingLabTelemetry.set").read_bytes()
                self.assertTrue(telemetry.startswith(b"\xff\xfe"))
                text = telemetry.decode("utf-16")
                self.assertIn("AllowRealAccount=true", text)
                self.assertIn("ExpectedDemoLogin=1234", text)
                self.assertIn(f"Token={'a' * 32}", text)
                activity = (result / "TradingLabActivity.set").read_text(encoding="utf-16")
                self.assertIn("HistoryStartServerTime=1767225600", activity)
                suffix = "/v2/telemetry" if LAYOUT == "local-dual-v1" else "/api/trading-events"
                self.assertIn(f"IngestUrl=http://127.0.0.1:8877{suffix}", activity)
                with self.assertRaises(FileExistsError):
                    create_presets(directory, "1234", "2026.01.01 00:00:00")
                self.assertEqual(telemetry, (result / "TradingLabTelemetry.set").read_bytes())
                create_presets(directory, "1234", "2026.01.01 00:00:00", resume=True)
                (result / "TradingLabActivity.set").unlink()
                create_presets(directory, "1234", "2026.01.01 00:00:00", resume=True)
                self.assertTrue((result / "TradingLabActivity.set").exists())
                self.assertEqual(telemetry, (result / "TradingLabTelemetry.set").read_bytes())
                with self.assertRaises(ValueError):
                    create_presets(directory, "1234", "2026.01.02 00:00:00", resume=True)


if __name__ == "__main__":
    unittest.main()

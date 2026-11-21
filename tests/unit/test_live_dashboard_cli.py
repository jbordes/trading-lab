from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

CLI_SPEC = importlib.util.spec_from_file_location(
    "live_dashboard_cli", ROOT / "scripts" / "live_dashboard.py"
)
assert CLI_SPEC and CLI_SPEC.loader
CLI = importlib.util.module_from_spec(CLI_SPEC)
CLI_SPEC.loader.exec_module(CLI)


class LiveDashboardCliTest(unittest.TestCase):
    def test_central_api_uses_one_port_and_requires_both_sources(self) -> None:
        base = ["--central-api-port", "8781", "--snapshot-source", "terminal-demo-01"]
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            CLI.parse_args(base)
        args = CLI.parse_args(base + ["--activity-source", "activity-01"])
        self.assertTrue(args.telemetry)
        self.assertEqual(args.central_api_port, 8781)
        for extra in (["--demo"], ["--port", "8781"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                CLI.parse_args(base + ["--activity-source", "activity-01"] + extra)

    def test_missing_central_read_token_does_not_fall_back_to_ingest_token(self) -> None:
        environment = {
            "TRADINGLAB_DASHBOARD_TOKEN": "example-dashboard-access-token",
            "TRADINGLAB_TELEMETRY_TOKEN": "example-ingestion-access-token",
            "CENTRAL_SNAPSHOT_INGEST": "synthetic-central-ingestion-token",
        }
        with contextlib.redirect_stderr(io.StringIO()):
            result = CLI.main(
                [
                    "--central-api-port",
                    "8781",
                    "--snapshot-source",
                    "terminal-demo-01",
                    "--activity-source",
                    "activity-01",
                ],
                environment=environment,
            )
        self.assertEqual(result, 2)

    def test_central_dashboard_wires_only_read_credentials(self) -> None:
        environment = {
            "TRADINGLAB_DASHBOARD_TOKEN": "example-dashboard-access-token",
            "CENTRAL_ACCOUNT_READ": "synthetic-central-v1-read-token",
            "CENTRAL_TRADING_READ": "synthetic-central-v2-read-token",
        }
        with (
            patch("tradinglab.dashboard.telemetry.LoopbackTelemetryClient") as v1,
            patch("tradinglab.dashboard.telemetry_v2.LoopbackV2HistoryClient") as v2,
            patch("tradinglab.dashboard.service.LiveDashboardService"),
            patch("tradinglab.dashboard.web.create_server") as server,
        ):
            server.return_value.serve_forever.side_effect = KeyboardInterrupt
            with contextlib.redirect_stdout(io.StringIO()):
                result = CLI.main(
                    [
                        "--central-api-port",
                        "8781",
                        "--snapshot-source",
                        "terminal-demo-01",
                        "--activity-source",
                        "activity-01",
                    ],
                    environment=environment,
                )
        self.assertEqual(result, 0)
        self.assertEqual(v1.call_args.kwargs["token"], environment["CENTRAL_ACCOUNT_READ"])
        self.assertTrue(v1.call_args.kwargs["central_api"])
        self.assertEqual(
            v2.call_args.kwargs["read_authorization"], environment["CENTRAL_TRADING_READ"]
        )
        self.assertEqual(v2.call_args.kwargs["port"], 8781)

    def test_dashboard_entrypoint_has_no_python_mt5_adapter(self) -> None:
        source = (ROOT / "scripts" / "live_dashboard.py").read_text(encoding="utf-8")

        self.assertNotIn("MetaTrader5", source)
        self.assertNotIn("Mt5SnapshotSource", source)

    def test_source_mode_is_always_explicit(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            CLI.parse_args([])

        self.assertTrue(CLI.parse_args(["--demo"]).demo)

    def test_legacy_receiver_flags_are_rejected(self) -> None:
        for flag in ("--telemetry", "--history-v2", "--telemetry-port"):
            with (
                self.subTest(flag=flag),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                CLI.parse_args(["--demo", flag])

    def test_demo_rejects_account_identity(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            CLI.parse_args(["--demo", "--snapshot-source", "terminal-demo-01"])


if __name__ == "__main__":
    unittest.main()

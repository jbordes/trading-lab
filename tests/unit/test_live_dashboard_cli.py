from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

CLI_SPEC = importlib.util.spec_from_file_location(
    "live_dashboard_cli", ROOT / "scripts" / "live_dashboard.py"
)
assert CLI_SPEC and CLI_SPEC.loader
CLI = importlib.util.module_from_spec(CLI_SPEC)
CLI_SPEC.loader.exec_module(CLI)


class LiveDashboardCliTest(unittest.TestCase):
    def test_dashboard_entrypoint_has_no_python_mt5_adapter(self) -> None:
        source = (ROOT / "scripts" / "live_dashboard.py").read_text(encoding="utf-8")

        self.assertNotIn("MetaTrader5", source)
        self.assertNotIn("Mt5SnapshotSource", source)

    def test_source_mode_is_always_explicit(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            CLI.parse_args([])

        self.assertTrue(CLI.parse_args(["--demo"]).demo)

    def test_telemetry_requires_explicit_source_id(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            CLI.parse_args(["--telemetry"])

        args = CLI.parse_args(["--telemetry", "--telemetry-source", "terminal-demo-01"])
        self.assertTrue(args.telemetry)
        self.assertEqual(args.telemetry_source, "terminal-demo-01")

    def test_demo_rejects_telemetry_identity(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            CLI.parse_args(["--demo", "--telemetry-source", "terminal-demo-01"])


if __name__ == "__main__":
    unittest.main()

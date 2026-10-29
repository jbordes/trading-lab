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
    "telemetry_component_cli", ROOT / "scripts" / "start_telemetry_v2_component.py"
)
assert CLI_SPEC and CLI_SPEC.loader
CLI = importlib.util.module_from_spec(CLI_SPEC)
CLI_SPEC.loader.exec_module(CLI)


class TelemetryComponentCliTest(unittest.TestCase):
    def test_requires_an_explicit_component(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            CLI.parse_args([])
        self.assertEqual(CLI.parse_args(["receivers"]).component, "receivers")
        self.assertEqual(CLI.parse_args(["dashboard"]).component, "dashboard")

    def test_database_arguments_are_filenames_not_paths(self) -> None:
        for value in ("nested/pilot.sqlite3", "pilot.db", "../pilot.sqlite3"):
            with (
                self.subTest(value=value),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                CLI.parse_args(["receivers", "--v1-database", value])


if __name__ == "__main__":
    unittest.main()

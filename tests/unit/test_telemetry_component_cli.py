from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_local_secrets_avoid_prompts_and_do_not_override_process_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            secrets_file = Path(temporary_directory) / ".env.local"
            secrets_file.write_text(
                "TRADINGLAB_TELEMETRY_TOKEN=file-token-123456789012345\n"
                "TRADINGLAB_TELEMETRY_LIVE_TOKEN=live-token-123456789012345\n"
                "TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN=activity-token-123456789012\n"
                "TRADINGLAB_TELEMETRY_READ_TOKEN=read-token-123456789012345\n",
                encoding="utf-8",
            )
            with (
                patch.dict(
                    CLI.os.environ,
                    {"TRADINGLAB_TELEMETRY_TOKEN": "process-token-123456789012"},
                    clear=True,
                ),
                patch.object(CLI.getpass, "getpass") as prompt,
            ):
                environment = CLI._read_environment("receivers", secrets_file)

        prompt.assert_not_called()
        self.assertEqual(
            environment["TRADINGLAB_TELEMETRY_TOKEN"], "process-token-123456789012"
        )
        self.assertEqual(
            environment["TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN"],
            "activity-token-123456789012",
        )

    def test_local_secrets_reject_unknown_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            secrets_file = Path(temporary_directory) / ".env.local"
            secrets_file.write_text("UNEXPECTED_SECRET=value\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Variable no permitida"):
                CLI._read_environment("dashboard", secrets_file)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from collections import namedtuple
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

CLI_SPEC = importlib.util.spec_from_file_location(
    "mt5_diagnostic_cli", ROOT / "scripts" / "mt5_diagnostic.py"
)
assert CLI_SPEC and CLI_SPEC.loader
CLI = importlib.util.module_from_spec(CLI_SPEC)
CLI_SPEC.loader.exec_module(CLI)

from tradinglab.incubation.diagnostic import (  # noqa: E402
    CaptureValidationError,
    CaptureWindow,
    EvidenceConflictError,
    Mt5InitializationError,
    Mt5ReadError,
    collect_mt5_diagnostic,
    load_capture_evidence,
    write_capture_evidence,
)

Account = namedtuple("Account", "login server balance")
Terminal = namedtuple("Terminal", "connected build")
Order = namedtuple("Order", "ticket position_id magic")
Deal = namedtuple("Deal", "ticket order position_id magic profit")
Position = namedtuple("Position", "ticket position_id magic profit")


class FakeMt5:
    def __init__(self) -> None:
        self.initialized = False
        self.shutdown_called = False
        self.fail_initialize = False
        self.fail_endpoint: str | None = None

    def initialize(self) -> bool:
        self.initialized = not self.fail_initialize
        return self.initialized

    def shutdown(self) -> None:
        self.shutdown_called = True

    def last_error(self) -> object:
        return (500, "controlled test error")

    def account_info(self) -> object | None:
        return self._value("account_info", Account(90000001, "DEMO-SERVER", 10000.0))

    def terminal_info(self) -> object | None:
        return self._value("terminal_info", Terminal(True, 5000))

    def history_orders_get(self, date_from: datetime, date_to: datetime) -> object | None:
        del date_from, date_to
        return self._value("history_orders_get", (Order(1, 10, 900001),))

    def history_deals_get(self, date_from: datetime, date_to: datetime) -> object | None:
        del date_from, date_to
        return self._value("history_deals_get", (Deal(2, 1, 10, 900001, 3.5),))

    def positions_get(self) -> object | None:
        return self._value("positions_get", (Position(11, 11, 900001, 1.5),))

    def orders_get(self) -> object | None:
        return self._value("orders_get", ())

    def _value(self, endpoint: str, value: object) -> object | None:
        return None if self.fail_endpoint == endpoint else value


class Mt5DiagnosticTest(unittest.TestCase):
    def setUp(self) -> None:
        self.captured_at = datetime(2026, 10, 14, 18, tzinfo=UTC)
        self.window = CaptureWindow(
            self.captured_at - timedelta(days=1),
            self.captured_at,
        )

    def test_collects_all_read_only_datasets_and_shuts_down(self) -> None:
        client = FakeMt5()

        payload = collect_mt5_diagnostic(
            client,
            self.window,
            captured_at=self.captured_at,
        )

        self.assertTrue(client.initialized)
        self.assertTrue(client.shutdown_called)
        self.assertEqual(payload["account"]["login"], 90000001)
        self.assertEqual(payload["history_orders"][0]["magic"], 900001)
        self.assertEqual(payload["history_deals"][0]["position_id"], 10)
        self.assertEqual(payload["open_positions"][0]["profit"], 1.5)
        self.assertEqual(payload["active_orders"], [])

    def test_initialization_failure_is_explicit(self) -> None:
        client = FakeMt5()
        client.fail_initialize = True

        with self.assertRaises(Mt5InitializationError):
            collect_mt5_diagnostic(client, self.window, captured_at=self.captured_at)

        self.assertFalse(client.shutdown_called)

    def test_read_failure_still_shuts_down(self) -> None:
        client = FakeMt5()
        client.fail_endpoint = "history_deals_get"

        with self.assertRaises(Mt5ReadError):
            collect_mt5_diagnostic(client, self.window, captured_at=self.captured_at)

        self.assertTrue(client.shutdown_called)

    def test_capture_window_requires_aware_ordered_instants(self) -> None:
        with self.assertRaisesRegex(ValueError, "zona horaria"):
            CaptureWindow(datetime(2026, 10, 14), self.captured_at)
        with self.assertRaisesRegex(ValueError, "anterior"):
            CaptureWindow(self.captured_at, self.captured_at)

    def test_evidence_write_is_idempotent_but_never_overwrites(self) -> None:
        payload = collect_mt5_diagnostic(
            FakeMt5(),
            self.window,
            captured_at=self.captured_at,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"

            first = write_capture_evidence(payload, path)
            second = write_capture_evidence(payload, path)

            self.assertFalse(first.already_existed)
            self.assertTrue(second.already_existed)
            self.assertEqual(first.sha256, second.sha256)
            self.assertTrue(first.manifest_path.is_file())

            changed = dict(payload)
            changed["captured_at"] = "2026-10-14T18:01:00Z"
            with self.assertRaises(EvidenceConflictError):
                write_capture_evidence(changed, path)

    def test_golden_fixture_satisfies_capture_contract(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "incubation" / "mt5_capture_golden_v1.json"

        payload = load_capture_evidence(fixture)

        self.assertEqual(payload["account"]["name"], "ANONYMIZED ACCOUNT")
        self.assertEqual(payload["history_deals"][0]["magic"], 900001)
        self.assertEqual(len(payload["open_positions"]), 1)
        self.assertEqual(len(payload["active_orders"]), 1)

    def test_invalid_fixture_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps([]), encoding="utf-8")

            with self.assertRaises(CaptureValidationError):
                load_capture_evidence(path)

    def test_output_is_restricted_to_ignored_storage(self) -> None:
        inside = CLI.resolve_output_path(ROOT, ROOT / "_storage" / "capture.json", self.captured_at)

        self.assertTrue(inside.is_relative_to((ROOT / "_storage").resolve()))
        with self.assertRaisesRegex(ValueError, "_storage"):
            CLI.resolve_output_path(ROOT, ROOT / "docs" / "capture.json", self.captured_at)

    def test_cli_dry_run_uses_console_safe_output(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = CLI.main(
                [
                    "--date-from",
                    "2026-10-13T18:00:00Z",
                    "--date-to",
                    "2026-10-14T18:00:00Z",
                    "--dry-run",
                ]
            )

        self.assertEqual(result, 0)
        self.assertIn(" -> ", output.getvalue())


if __name__ == "__main__":
    unittest.main()

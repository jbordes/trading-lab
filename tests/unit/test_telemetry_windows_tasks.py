from __future__ import annotations

import io
import runpy
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.windows_tasks import task_plan  # noqa: E402


class TelemetryWindowsTasksTest(unittest.TestCase):
    def test_daily_account_is_opt_in_and_never_sent_to_api_process(self) -> None:
        api, maintenance = task_plan(
            Path("checkout"),
            Path("data"),
            start_date=date(2026, 11, 6),
            daily_account_id="test-account",
        )
        self.assertNotIn("--daily-account-id", api.arguments)
        self.assertIn("--daily-account-id", maintenance.arguments)
        self.assertIn("test-account", maintenance.arguments)
        with self.assertRaises(ValueError):
            task_plan(
                Path("checkout"),
                Path("data"),
                start_date=date(2026, 11, 6),
                daily_account_id="bad/../id",
            )

    def test_public_host_is_preserved_in_api_task_and_not_added_to_maintenance(self) -> None:
        root = Path("Trading Lab & checkout")
        storage = Path("Trading Lab data")
        api, maintenance = task_plan(
            root, storage, start_date=date(2026, 11, 5), tailscale_host="mac.example.ts.net"
        )
        self.assertEqual(api.arguments[-2:], ("--tailscale-host", "mac.example.ts.net"))
        self.assertNotIn("--tailscale-host", maintenance.arguments)
        xml = ET.fromstring(api.xml(user_id="demo-user"))
        namespace = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(
            xml.findtext("t:Actions/t:Exec/t:Arguments", namespaces=namespace),
            subprocess.list2cmdline(list(api.arguments)),
        )

    def test_default_task_preserves_local_only_arguments(self) -> None:
        root, storage = Path("checkout"), Path("data")
        api, _ = task_plan(root, storage, start_date=date(2026, 11, 5))
        self.assertEqual(
            api.arguments,
            (str(root / "scripts/run_central_api_job.py"), "--data-dir", str(storage)),
        )

    def test_plan_rejects_invalid_public_hosts_before_building_tasks(self) -> None:
        for host in (
            "",
            "https://mac.example.ts.net",
            "*.example.ts.net",
            "mac.example.ts.net:443",
            "mac.example.ts.net;command",
            "other.invalid",
        ):
            with self.subTest(host=host), self.assertRaises(ValueError):
                task_plan(
                    Path("checkout"),
                    Path("data"),
                    start_date=date(2026, 11, 5),
                    tailscale_host=host,
                )

    def test_installer_preview_shows_public_origin_without_touching_task_scheduler(self) -> None:
        root = Path(__file__).resolve().parents[2]
        main = runpy.run_path(str(root / "scripts/configure_telemetry_windows_tasks.py"))["main"]
        with tempfile.TemporaryDirectory() as temporary:
            for host in (None, "mac.example.ts.net"):
                output = io.StringIO()
                arguments = ["--data-dir", temporary]
                if host:
                    arguments += ["--tailscale-host", host]
                with (
                    self.subTest(host=host),
                    patch.object(Path, "is_file", return_value=True),
                    patch("subprocess.run") as command,
                    redirect_stdout(output),
                ):
                    self.assertEqual(main(arguments), 0)
                    command.assert_not_called()
                self.assertIn("Vista previa", output.getvalue())
                self.assertIn(
                    "https://mac.example.ts.net" if host else "solo por loopback", output.getvalue()
                )

    def test_installer_rejects_invalid_host_without_installation(self) -> None:
        root = Path(__file__).resolve().parents[2]
        main = runpy.run_path(str(root / "scripts/configure_telemetry_windows_tasks.py"))["main"]
        with patch("subprocess.run") as command, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as failure:
                main(
                    [
                        "--data-dir",
                        "unused",
                        "--tailscale-host",
                        "https://mac.example.ts.net",
                        "--apply",
                    ]
                )
            self.assertEqual(failure.exception.code, 2)
            command.assert_not_called()

    def test_plan_separates_jobs_and_never_embeds_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / "storage"
            receivers, maintenance = task_plan(root, storage, start_date=date(2026, 10, 29))
            receiver_xml = receivers.xml(user_id="demo-user")
            maintenance_xml = maintenance.xml(user_id="demo-user")
        self.assertIn("LogonTrigger", receiver_xml)
        self.assertIn("RestartOnFailure", receiver_xml)
        self.assertIn("run_central_api_job.py", receiver_xml)
        self.assertIn("CalendarTrigger", maintenance_xml)
        self.assertIn("2026-10-29T03:30:00", maintenance_xml)
        self.assertIn("run_telemetry_maintenance.py", maintenance_xml)
        self.assertNotIn("TRADINGLAB_TELEMETRY_TOKEN", receiver_xml + maintenance_xml)
        self.assertNotIn("Bearer", receiver_xml + maintenance_xml)
        self.assertIn("IgnoreNew", receiver_xml + maintenance_xml)
        ET.fromstring(receiver_xml)
        ET.fromstring(maintenance_xml)


if __name__ == "__main__":
    unittest.main()

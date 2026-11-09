from __future__ import annotations

import io
import plistlib
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path, PurePosixPath
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry import maintenance_schedule as scheduling
from tradinglab.telemetry.central_schema import create_central_database


class MaintenanceScheduleTest(unittest.TestCase):
    def plan(self, **overrides) -> scheduling.MaintenanceSchedule:
        values = dict(
            root=PurePosixPath("/srv/Trading Lab's checkout"),
            storage=PurePosixPath("/srv/trading data"),
            database="pilot.sqlite3",
            account_id="test-account",
        )
        return scheduling.MaintenanceSchedule(**(values | overrides))

    def result(self, code=0, output="", error=""):
        return subprocess.CompletedProcess([], code, output, error)

    def test_paths_identifiers_and_times_are_validated(self):
        for changes in (
            {"root": Path("relative")},
            {"database": "../other.sqlite3"},
            {"account_id": "bad\nid"},
            {"hour": 24},
            {"minute": -1},
            {"hour": True},
            {"storage": PurePosixPath("/bad\npath")},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.plan(**changes)

    def test_cron_quotes_shell_characters_and_has_no_credentials(self):
        import shlex

        plan = self.plan()
        line = plan.cron_block().splitlines()[1]
        words = shlex.split(line)[5:]
        self.assertEqual(words, [str(plan.python("cron")), *plan.arguments()])
        self.assertNotIn("token", line.lower())
        self.assertNotIn(".env", line)
        self.assertIn("--database pilot.sqlite3", line)

    def test_cron_rejects_percent_and_backslash_in_paths(self):
        for root in (PurePosixPath("/srv/100%data"), PurePosixPath("/srv/back\\slash")):
            with self.subTest(root=root), self.assertRaises(ValueError):
                self.plan(root=root).cron_block()

    def test_crontab_preserves_other_jobs_and_is_idempotent(self):
        plan = self.plan()
        existing = "MAILTO=admin\n0 1 * * * /usr/bin/true"
        merged = scheduling.merge_crontab(existing, plan)
        self.assertTrue(merged.startswith(existing + "\n"))
        self.assertEqual(scheduling.merge_crontab(merged, plan), merged)
        with self.assertRaises(ValueError):
            scheduling.merge_crontab(merged, self.plan(hour=5))
        with self.assertRaises(ValueError):
            scheduling.merge_crontab("# " + plan.label, plan)

    def test_launchd_is_structured_without_immediate_run_or_retries(self):
        plan = self.plan()
        data = plistlib.loads(plan.launchd_plist())
        self.assertEqual(data["ProgramArguments"], [str(plan.python("launchd")), *plan.arguments()])
        self.assertEqual(data["StartCalendarInterval"], {"Hour": 3, "Minute": 30})
        self.assertFalse(data["RunAtLoad"])
        self.assertFalse(data["KeepAlive"])

    def test_cron_install_preserves_existing_and_detects_racing_edit(self):
        plan = self.plan()
        with (
            patch.object(scheduling, "validate_target"),
            patch.object(
                scheduling,
                "_command",
                side_effect=[
                    self.result(output="old\n"),
                    self.result(output="old\n"),
                    self.result(),
                ],
            ) as command,
        ):
            scheduling.install_schedule(
                plan, "cron", user_id="user", home=Path("unused"), now=datetime(2026, 11, 9)
            )
            self.assertEqual(command.call_args.kwargs["input_text"], "old\n" + plan.cron_block())
        with (
            patch.object(scheduling, "validate_target"),
            patch.object(
                scheduling,
                "_command",
                side_effect=[self.result(output="old\n"), self.result(output="changed\n")],
            ) as command,
            self.assertRaises(RuntimeError),
        ):
            scheduling.install_schedule(
                plan, "cron", user_id="user", home=Path("unused"), now=datetime(2026, 11, 9)
            )
        self.assertEqual(command.call_count, 2)

    def test_cron_query_permission_error_never_becomes_empty_crontab(self):
        with (
            patch.object(
                scheduling, "_command", return_value=self.result(1, error="permission denied")
            ),
            self.assertRaises(RuntimeError),
        ):
            scheduling._read_crontab()
        with patch.object(
            scheduling, "_command", return_value=self.result(1, error="no crontab for tester\n")
        ):
            self.assertEqual(scheduling._read_crontab(), "")
        with patch.object(
            scheduling,
            "_command",
            return_value=self.result(1, error="crontab: no crontab for tester\n"),
        ):
            self.assertEqual(scheduling._read_crontab(), "")

    def test_external_commands_are_bounded_and_never_use_shell(self):
        with patch("subprocess.run", return_value=self.result()) as command:
            scheduling._command(["crontab", "-l"])
        self.assertEqual(command.call_args.kwargs["timeout"], 20)
        self.assertFalse(command.call_args.kwargs["shell"])
        self.assertEqual(command.call_args.kwargs["env"]["LC_ALL"], "C")

    def test_windows_installs_only_maintenance_and_next_trigger_is_future(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = self.plan(root=Path(temporary), storage=Path(temporary))

            def command(arguments, **kwargs):
                if "/Query" in arguments:
                    return self.result(1)
                xml = Path(arguments[-1]).read_text(encoding="utf-16")
                self.assertIn("2026-11-10T03:30:00", xml)
                self.assertIn("pilot.sqlite3", xml)
                self.assertNotIn("run_central_api_job.py", xml)
                self.assertNotIn("RestartOnFailure", xml)
                return self.result()

            with (
                patch.object(scheduling, "validate_target"),
                patch.object(scheduling, "_command", side_effect=command),
            ):
                scheduling.install_schedule(
                    plan,
                    "windows",
                    user_id="tester",
                    home=Path(temporary),
                    now=datetime(2026, 11, 9, 15),
                )

    def test_windows_existing_task_is_not_overwritten(self):
        with (
            patch.object(scheduling, "validate_target"),
            patch.object(scheduling, "_command", return_value=self.result()) as command,
            self.assertRaises(FileExistsError),
        ):
            scheduling.install_schedule(
                self.plan(),
                "windows",
                user_id="tester",
                home=Path("unused"),
                now=datetime(2026, 11, 9),
            )
        self.assertEqual(command.call_count, 1)

    def test_launchd_failed_registration_preserves_plist_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            plan = self.plan()
            with (
                patch.object(scheduling, "validate_target"),
                patch.object(scheduling.os, "getuid", return_value=123, create=True),
                patch.object(scheduling, "_command", return_value=self.result(1)) as command,
            ):
                with self.assertRaises(RuntimeError):
                    scheduling.install_schedule(
                        plan, "launchd", user_id="tester", home=home, now=datetime(2026, 11, 9)
                    )
                file = home / "Library/LaunchAgents" / f"{plan.label}.plist"
                self.assertEqual(file.read_bytes(), plan.launchd_plist())
                with self.assertRaises(FileExistsError):
                    scheduling.install_schedule(
                        plan, "launchd", user_id="tester", home=home, now=datetime(2026, 11, 9)
                    )
                self.assertEqual(command.call_count, 1)

    def test_preflight_needs_registered_account_but_no_secret_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self.plan(root=root, storage=root)
            python = plan.python("windows")
            python.parent.mkdir(parents=True)
            python.touch()
            script = root / "scripts/run_telemetry_maintenance.py"
            script.parent.mkdir()
            script.touch()
            create_central_database(root / plan.database)
            with self.assertRaisesRegex(ValueError, "fuente"):
                scheduling.validate_target(plan, "windows")

    def test_cli_preview_never_touches_scheduler(self):
        root = Path(__file__).resolve().parents[2]
        main = runpy.run_path(str(root / "scripts/configure_telemetry_maintenance.py"))["main"]
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(scheduling, "validate_target"),
            patch.object(scheduling, "install_schedule") as install,
            redirect_stdout(io.StringIO()),
            patch.object(sys, "platform", "win32"),
        ):
            self.assertEqual(
                main(
                    [
                        "--data-dir",
                        temporary,
                        "--database",
                        "pilot.sqlite3",
                        "--account-id",
                        "test-account",
                    ]
                ),
                0,
            )
            install.assert_not_called()

    def test_cli_invalid_time_or_incompatible_scheduler_never_installs(self):
        root = Path(__file__).resolve().parents[2]
        main = runpy.run_path(str(root / "scripts/configure_telemetry_maintenance.py"))["main"]
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(scheduling, "validate_target") as validate,
            patch.object(scheduling, "install_schedule") as install,
            redirect_stderr(io.StringIO()),
            patch.object(sys, "platform", "win32"),
        ):
            for extra in (["--time", "99:99"], ["--time", "3:30"], ["--scheduler", "cron"]):
                self.assertEqual(
                    main(
                        ["--data-dir", temporary, "--account-id", "test-account", "--apply", *extra]
                    ),
                    1,
                )
            validate.assert_not_called()
            install.assert_not_called()


if __name__ == "__main__":
    unittest.main()

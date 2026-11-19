from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "bootstrap_installation", ROOT / "scripts/bootstrap_installation.py"
)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapInstallationTest(unittest.TestCase):
    def test_preview_never_downloads_or_runs_installation(self):
        with (
            patch.object(bootstrap.shutil, "which", return_value="uv"),
            patch.object(bootstrap.subprocess, "run") as run,
        ):
            self.assertEqual(
                bootstrap.main(["--config", "example.json", "--data-dir", "example"]), 0
            )
        run.assert_not_called()

    def test_failed_dependency_sync_never_provisions(self):
        import subprocess

        with (
            patch.object(bootstrap.shutil, "which", return_value="uv"),
            patch.object(
                bootstrap.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "uv")
            ) as run,
        ):
            self.assertEqual(
                bootstrap.main(["--config", "example.json", "--data-dir", "example", "--apply"]), 1
            )
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ["uv", "sync", "--locked", "--no-dev"])

    def test_apply_forwards_explicit_real_permission_without_starting(self):
        with (
            patch.object(bootstrap.shutil, "which", return_value="uv"),
            patch.object(bootstrap.subprocess, "run") as run,
            patch.object(bootstrap.subprocess, "call") as start,
        ):
            self.assertEqual(
                bootstrap.main(
                    [
                        "--config",
                        "example.json",
                        "--data-dir",
                        "example",
                        "--apply",
                        "--allow-real-account",
                    ]
                ),
                0,
            )
        self.assertEqual(run.call_count, 2)
        self.assertIn("--allow-real-account", run.call_args.args[0])
        self.assertIn("--apply", run.call_args.args[0])
        start.assert_not_called()

    def test_resume_validates_without_provisioning(self):
        with (
            patch.object(bootstrap.shutil, "which", return_value="uv"),
            patch.object(bootstrap.subprocess, "run") as run,
        ):
            self.assertEqual(
                bootstrap.main(
                    ["--config", "example.json", "--data-dir", "existing", "--apply", "--resume"]
                ),
                0,
            )
        command = run.call_args.args[0]
        self.assertTrue(any(part.endswith("run_tradinglab.py") for part in command))
        self.assertIn("--dry-run", command)
        self.assertIn("--expected-config", command)
        self.assertFalse(any(part.endswith("install_tradinglab.py") for part in command))


if __name__ == "__main__":
    unittest.main()

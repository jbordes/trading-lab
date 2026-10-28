from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.runtime_v2 import (  # noqa: E402
    V2PilotRuntimeConfig,
    run_v2_pilot,
)

TEST_ENV = {
    "TRADINGLAB_TELEMETRY_TOKEN": "example-v1-credential-not-for-use",
    "TRADINGLAB_DASHBOARD_TOKEN": "example-dashboard-credential-not-for-use",
    "TRADINGLAB_TELEMETRY_LIVE_TOKEN": "example-v2-live-credential-not-for-use",
    "TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN": "example-v2-activity-credential-not-for-use",
    "TRADINGLAB_TELEMETRY_READ_TOKEN": "example-v2-read-credential-not-for-use",
}


class V2PilotRuntimeTest(unittest.TestCase):
    def configured(self, root: Path) -> V2PilotRuntimeConfig:
        storage = root / "_storage"
        storage.mkdir()
        v1 = storage / "piloto.sqlite3"
        v2 = storage / "piloto-v2.sqlite3"
        v1.touch()
        v2.touch()
        return V2PilotRuntimeConfig(
            "juampi-demo-01",
            "juampi-demo-activity-v2",
            "cuenta-demo-juampi",
            v1,
            v2,
        )

    def test_spawns_three_isolated_processes_and_cleans_its_children(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.configured(root)
            v1, v2, dashboard = Mock(), Mock(), Mock()
            v1.poll.return_value = None
            v2.poll.return_value = None
            dashboard.poll.return_value = 1
            spawn = Mock(side_effect=[v1, v2, dashboard])

            with self.assertRaisesRegex(RuntimeError, "dashboard"):
                run_v2_pilot(
                    root,
                    config,
                    TEST_ENV,
                    spawn=spawn,
                    check_port=Mock(),
                    ready=Mock(return_value=True),
                    report=Mock(),
                )

            self.assertEqual(spawn.call_count, 3)
            commands = [call.args[0] for call in spawn.call_args_list]
            self.assertIn("telemetry_receiver.py", commands[0][1])
            self.assertIn("telemetry_receiver_v2.py", commands[1][1])
            self.assertIn("live_dashboard.py", commands[2][1])
            self.assertIn("--history-v2", commands[2])
            self.assertEqual(
                commands[2][commands[2].index("--broker-utc-offset-minutes") + 1],
                "120",
            )
            for credential in TEST_ENV.values():
                self.assertNotIn(credential, str(commands))
            self.assertNotIn("TRADINGLAB_DASHBOARD_TOKEN", spawn.call_args_list[0].kwargs["env"])
            self.assertNotIn("TRADINGLAB_TELEMETRY_TOKEN", spawn.call_args_list[1].kwargs["env"])
            self.assertNotIn(
                "TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN",
                spawn.call_args_list[2].kwargs["env"],
            )
            v1.terminate.assert_called_once()
            v2.terminate.assert_called_once()

    def test_rejects_reused_credentials_before_ports_or_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.configured(root)
            environment = dict(TEST_ENV)
            environment["TRADINGLAB_TELEMETRY_READ_TOKEN"] = environment[
                "TRADINGLAB_DASHBOARD_TOKEN"
            ]
            spawn, check = Mock(), Mock()
            with self.assertRaisesRegex(ValueError, "distintas"):
                run_v2_pilot(
                    root,
                    config,
                    environment,
                    spawn=spawn,
                    check_port=check,
                )
            spawn.assert_not_called()
            check.assert_not_called()

    def test_rejects_missing_database_and_repeated_ports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / "_storage"
            storage.mkdir()
            missing = storage / "missing.sqlite3"
            config = V2PilotRuntimeConfig("live", "activity", "account", missing, missing)
            with self.assertRaisesRegex(ValueError, "no existe"):
                run_v2_pilot(root, config, TEST_ENV, check_port=Mock(), spawn=Mock())
        with self.assertRaises(ValueError):
            V2PilotRuntimeConfig(
                "live",
                "activity",
                "account",
                Path("v1.sqlite3"),
                Path("v2.sqlite3"),
                v1_port=8776,
                v2_port=8776,
            )


if __name__ == "__main__":
    unittest.main()

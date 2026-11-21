from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.installation_runtime import supervise


class InstallationRuntimeTest(unittest.TestCase):
    def test_busy_port_never_starts_or_stops_processes(self):
        with (
            patch("tradinglab.installation_runtime.socket.socket") as socket,
            patch("tradinglab.installation_runtime.subprocess.Popen") as popen,
        ):
            socket.return_value.__enter__.return_value.bind.side_effect = OSError("busy")
            with self.assertRaises(RuntimeError):
                supervise([["python", "central_api.py"]], [8782], [8782], root=Path.cwd())
            popen.assert_not_called()

    def test_failed_second_start_stops_only_owned_first_child(self):
        first = MagicMock()
        first.poll.return_value = None
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with (
            patch("tradinglab.installation_runtime.socket.socket"),
            patch("tradinglab.installation_runtime.urllib.request.urlopen", return_value=response),
            patch(
                "tradinglab.installation_runtime.subprocess.Popen",
                side_effect=[first, OSError("spawn")],
            ),
        ):
            with self.assertRaises(OSError):
                supervise(
                    [["python", "central_api.py"], ["python", "telemetry_relay.py"]],
                    [8782, 8776],
                    [8782, 8776],
                    root=Path.cwd(),
                )
        first.terminate.assert_called_once()
        first.wait.assert_called_once_with(timeout=5)
        first.kill.assert_not_called()

    def test_readiness_timeout_cleans_up(self):
        child = MagicMock()
        child.poll.return_value = None
        with (
            patch("tradinglab.installation_runtime.socket.socket"),
            patch("tradinglab.installation_runtime.subprocess.Popen", return_value=child),
            patch("tradinglab.installation_runtime.time.monotonic", side_effect=[0, 26]),
            patch(
                "tradinglab.installation_runtime.urllib.request.urlopen",
                side_effect=OSError("offline"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                supervise([["python", "central_api.py"]], [8782], [8782], root=Path.cwd())
        child.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()

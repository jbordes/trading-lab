from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# The harness is intentionally not installed as a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.ingest import TelemetryBuffer, create_telemetry_server  # noqa: E402
from tradinglab.telemetry.runtime import (  # noqa: E402
    RuntimeConfig,
    ensure_port_available,
    receiver_ready,
    run_runtime,
    stop_child,
)
from tradinglab.telemetry.sqlite_store import create_database  # noqa: E402

TEST_ENV = {"TRADINGLAB_TELEMETRY_TOKEN": "test-runtime-credential-not-for-use"}


class RuntimeTest(unittest.TestCase):
    def test_sqlite_mode_passes_existing_database_and_source_to_receiver(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / "_storage"
            storage.mkdir()
            database = storage / "pilot.sqlite3"
            create_database(database)
            receiver, dashboard = Mock(), Mock()
            receiver.poll.return_value = None
            dashboard.poll.return_value = 1
            spawn = Mock(side_effect=[receiver, dashboard])
            with self.assertRaisesRegex(RuntimeError, "dashboard"):
                run_runtime(
                    root,
                    RuntimeConfig("demo", sqlite_db=database),
                    TEST_ENV,
                    spawn=spawn,
                    check_port=Mock(),
                    ready=Mock(return_value=True),
                    report=Mock(),
                )
            receiver_args = spawn.call_args_list[0].args[0]
            self.assertEqual(
                receiver_args[-4:],
                ["--sqlite-db", str(database.resolve()), "--source-id", "demo"],
            )
            self.assertNotIn("--sqlite-db", spawn.call_args_list[1].args[0])

    def test_sqlite_mode_rejects_missing_and_outside_paths_before_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spawn = Mock()
            for database in (root / "missing.sqlite3", root / "outside.sqlite3"):
                if database.name == "outside.sqlite3":
                    create_database(database)
                with self.subTest(database=database), self.assertRaises(ValueError):
                    run_runtime(
                        root,
                        RuntimeConfig("demo", sqlite_db=database),
                        TEST_ENV,
                        spawn=spawn,
                        check_port=Mock(),
                    )
            spawn.assert_not_called()

    def test_invalid_configuration(self) -> None:
        for args in (("",), ("bad/source",), ("demo", 0), ("demo", 8776, 8776)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                RuntimeConfig(*args)

    def test_invalid_token_does_not_open_ports_or_spawn(self) -> None:
        spawn, check = Mock(), Mock()
        with self.assertRaises(ValueError):
            run_runtime(Path("."), RuntimeConfig("demo"), {}, spawn=spawn, check_port=check)
        spawn.assert_not_called()
        check.assert_not_called()

    def test_busy_port_does_not_spawn_or_stop_existing_process(self) -> None:
        spawn = Mock()
        with self.assertRaises(RuntimeError):
            run_runtime(
                Path("."),
                RuntimeConfig("demo"),
                TEST_ENV,
                spawn=spawn,
                check_port=Mock(side_effect=RuntimeError("busy")),
            )
        spawn.assert_not_called()

    def test_child_exit_stops_both_and_token_is_not_an_argument(self) -> None:
        receiver, dashboard = Mock(), Mock()
        receiver.poll.return_value = None
        dashboard.poll.return_value = 1
        spawn, report = Mock(side_effect=[receiver, dashboard]), Mock()
        with self.assertRaisesRegex(RuntimeError, "dashboard"):
            run_runtime(
                Path("."),
                RuntimeConfig("demo"),
                TEST_ENV,
                spawn=spawn,
                check_port=Mock(),
                ready=Mock(return_value=True),
                report=report,
            )
        receiver.terminate.assert_called_once()
        dashboard.terminate.assert_not_called()
        for call in spawn.call_args_list:
            self.assertNotIn(TEST_ENV["TRADINGLAB_TELEMETRY_TOKEN"], str(call.args))
            self.assertFalse(call.kwargs["shell"])
        self.assertNotIn(TEST_ENV["TRADINGLAB_TELEMETRY_TOKEN"], str(report.call_args_list))

    def test_startup_timeout_stops_receiver_without_starting_dashboard(self) -> None:
        receiver = Mock()
        receiver.poll.return_value = None
        spawn = Mock(return_value=receiver)
        with self.assertRaisesRegex(RuntimeError, "HTTP/1.1"):
            run_runtime(
                Path("."),
                RuntimeConfig("demo"),
                TEST_ENV,
                spawn=spawn,
                check_port=Mock(),
                ready=Mock(return_value=False),
                clock=Mock(side_effect=[0, 16]),
                sleep=Mock(),
            )
        spawn.assert_called_once()
        receiver.terminate.assert_called_once()

    def test_failed_second_spawn_cleans_up_receiver(self) -> None:
        receiver = Mock()
        receiver.poll.return_value = None
        with self.assertRaises(OSError):
            run_runtime(
                Path("."),
                RuntimeConfig("demo"),
                TEST_ENV,
                spawn=Mock(side_effect=[receiver, OSError("spawn failed")]),
                check_port=Mock(),
                ready=Mock(return_value=True),
            )
        receiver.terminate.assert_called_once()

    def test_ctrl_c_cleans_up_both_children(self) -> None:
        children = [Mock(), Mock()]
        for child in children:
            child.poll.return_value = None
        with self.assertRaises(KeyboardInterrupt):
            run_runtime(
                Path("."),
                RuntimeConfig("demo"),
                TEST_ENV,
                spawn=Mock(side_effect=children),
                check_port=Mock(),
                ready=Mock(return_value=True),
                sleep=Mock(side_effect=KeyboardInterrupt),
                report=Mock(),
            )
        for child in children:
            child.terminate.assert_called_once()

    def test_stuck_child_is_killed_with_bounded_wait(self) -> None:
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired("child", 5), 0]
        stop_child(child)
        child.kill.assert_called_once()

    def test_real_receiver_health_and_occupied_port(self) -> None:
        server = create_telemetry_server(
            TelemetryBuffer(), token=TEST_ENV["TRADINGLAB_TELEMETRY_TOKEN"], port=0
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertTrue(receiver_ready(server.server_port))
            with self.assertRaises(RuntimeError):
                ensure_port_available(server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_readiness_rejects_http_10_and_wrong_health(self) -> None:
        for version, state in (
            (10, {"status": "ready", "accepted": 0, "missing_sequences": 0}),
            (11, {"status": "ready"}),
            (11, []),
        ):
            response = io.BytesIO(json.dumps(state).encode())
            response.version = version
            response.status = 200
            opener = Mock()
            opener.open.return_value = response
            with patch("urllib.request.build_opener", return_value=opener):
                self.assertFalse(receiver_ready(8776))

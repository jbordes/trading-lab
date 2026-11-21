from __future__ import annotations

import errno
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.operational_job import (  # noqa: E402
    JobAlreadyRunningError,
    exclusive_job_lock,
    rotate_log,
    run_logged,
    write_job_status,
)


class TelemetryOperationalJobTest(unittest.TestCase):
    def test_duplicate_execution_is_rejected_and_lock_is_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "job.lock"
            with exclusive_job_lock(lock):
                with self.assertRaisesRegex(JobAlreadyRunningError, "ejecución activa"):
                    with exclusive_job_lock(lock):
                        self.fail("duplicate lock acquired")
            with exclusive_job_lock(lock):
                pass

    def test_lock_io_error_is_not_mislabeled_as_another_running_job(self) -> None:
        target = "msvcrt.locking" if os.name == "nt" else "fcntl.flock"
        with tempfile.TemporaryDirectory() as temporary:
            with patch(target, side_effect=OSError(errno.EIO, "synthetic I/O")):
                with self.assertRaises(OSError):
                    with exclusive_job_lock(Path(temporary) / "job.lock"):
                        self.fail("Unexpected lock acquired")

    def test_status_is_bounded_and_replaced_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            status = Path(temporary) / "status.json"
            write_job_status(status, job="maintenance", state="failed", detail="x" * 1000)
            document = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(document["format"], "tradinglab-job-status-v1")
            self.assertEqual(document["state"], "failed")
            self.assertEqual(len(document["detail"]), 500)
            self.assertFalse(status.with_suffix(".json.tmp").exists())

    def test_log_rotation_keeps_a_bounded_number_of_copies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "receivers.log"
            log.write_bytes(b"12345")
            rotate_log(log, max_bytes=5, copies=2)
            self.assertFalse(log.exists())
            self.assertEqual(log.with_name("receivers.log.1").read_bytes(), b"12345")
            log.write_bytes(b"67890")
            rotate_log(log, max_bytes=5, copies=2)
            self.assertEqual(log.with_name("receivers.log.1").read_bytes(), b"67890")
            self.assertEqual(log.with_name("receivers.log.2").read_bytes(), b"12345")

    def test_one_noisy_process_keeps_only_bounded_tail_including_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "child.log"
            code = (
                "import sys; sys.stdout.buffer.write(b'0123456789' * 25000); "
                "sys.stdout.flush(); sys.stderr.buffer.write(b'ERR'); sys.stderr.flush(); sys.exit(7)"
            )
            result = run_logged(
                [sys.executable, "-c", code], cwd=root, log_path=log, max_bytes=128, copies=3
            )
            self.assertEqual(result, 7)
            files = sorted(root.glob("child.log*"))
            self.assertEqual(len(files), 4)
            self.assertTrue(all(path.stat().st_size <= 128 for path in files))
            tail = b"".join(
                path.read_bytes()
                for path in [log.with_name(f"child.log.{i}") for i in (3, 2, 1)] + [log]
            )
            self.assertTrue((b"0123456789" * 25000 + b"ERR").endswith(tail))
            self.assertTrue(tail.endswith(b"ERR"))
            self.assertGreater(len(tail), 3 * 128)

    def test_default_limit_rotates_within_one_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "child.log"
            result = run_logged(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.buffer.write(b'x' * (5*1024*1024+1))",
                ],
                cwd=root,
                log_path=log,
            )
            self.assertEqual(result, 0)
            self.assertEqual(log.stat().st_size, 1)
            self.assertEqual(log.with_name("child.log.1").stat().st_size, 5 * 1024 * 1024)

    def test_existing_partial_file_is_filled_before_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "child.log"
            log.write_bytes(b"old")
            run_logged(
                [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'abcde')"],
                cwd=root,
                log_path=log,
                max_bytes=5,
                copies=1,
            )
            self.assertEqual(log.with_name("child.log.1").read_bytes(), b"oldab")
            self.assertEqual(log.read_bytes(), b"cde")

    def test_quiet_process_still_creates_log_and_preserves_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "child.log"
            result = run_logged(
                [sys.executable, "-c", "raise SystemExit(4)"], cwd=root, log_path=log
            )
            self.assertEqual(result, 4)
            self.assertEqual(log.read_bytes(), b"")

    def test_rotation_happens_before_waiting_for_child_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "child.log"
            acknowledgement = root / "rotated"
            code = (
                "import sys,time; from pathlib import Path\n"
                "sys.stdout.buffer.write(b'x' * 65); sys.stdout.flush()\n"
                "deadline = time.monotonic() + 5\n"
                "while not Path(sys.argv[1]).exists() and time.monotonic() < deadline:\n"
                "    time.sleep(0.01)\n"
                "sys.exit(0 if Path(sys.argv[1]).exists() else 2)\n"
            )

            def rotate(path: Path, **limits: int) -> None:
                rotate_log(path, **limits)
                if log.with_name("child.log.1").exists():
                    acknowledgement.touch()

            with patch("tradinglab.telemetry.operational_job.rotate_log", side_effect=rotate):
                result = run_logged(
                    [sys.executable, "-c", code, str(acknowledgement)],
                    cwd=root,
                    log_path=log,
                    max_bytes=64,
                    copies=1,
                )
            self.assertEqual(result, 0)
            self.assertEqual(log.stat().st_size, 1)

    def test_sink_failure_stops_and_reaps_child_and_closes_pipe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "child.log"
            child = Mock()
            child.stdout = io.BytesIO(b"payload")
            child.poll.return_value = None
            child.wait.side_effect = (subprocess.TimeoutExpired("synthetic", 5), 0)
            original_open = Path.open
            opens = 0

            def fail_append(path: Path, *args: object, **kwargs: object):
                nonlocal opens
                if path == log:
                    opens += 1
                    if opens == 2:
                        raise OSError("synthetic sink failure")
                return original_open(path, *args, **kwargs)

            with (
                patch("tradinglab.telemetry.operational_job.subprocess.Popen", return_value=child),
                patch.object(Path, "open", fail_append),
                self.assertRaisesRegex(OSError, "synthetic sink failure"),
            ):
                run_logged(["synthetic"], cwd=root, log_path=log)
            child.terminate.assert_called_once()
            child.kill.assert_called_once()
            self.assertEqual(child.wait.call_count, 2)
            self.assertTrue(child.stdout.closed)

    def test_invalid_limits_never_start_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("tradinglab.telemetry.operational_job.subprocess.Popen") as spawn:
                for limits in (
                    {"max_bytes": 0},
                    {"max_bytes": True},
                    {"max_bytes": 1.5},
                    {"copies": 0},
                    {"copies": True},
                    {"copies": 1.5},
                ):
                    with self.subTest(limits=limits), self.assertRaises(ValueError):
                        run_logged(["synthetic"], cwd=root, log_path=root / "log", **limits)
                spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()

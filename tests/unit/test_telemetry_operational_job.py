from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.operational_job import (  # noqa: E402
    exclusive_job_lock,
    write_job_status,
)


class TelemetryOperationalJobTest(unittest.TestCase):
    def test_duplicate_execution_is_rejected_and_lock_is_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "job.lock"
            with exclusive_job_lock(lock):
                with self.assertRaisesRegex(RuntimeError, "ejecución activa"):
                    with exclusive_job_lock(lock):
                        self.fail("duplicate lock acquired")
            with exclusive_job_lock(lock):
                pass

    def test_status_is_bounded_and_replaced_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            status = Path(temporary) / "status.json"
            write_job_status(status, job="maintenance", state="failed", detail="x" * 1000)
            document = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(document["format"], "tradinglab-job-status-v1")
            self.assertEqual(document["state"], "failed")
            self.assertEqual(len(document["detail"]), 500)
            self.assertFalse(status.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()

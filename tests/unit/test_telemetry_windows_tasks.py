from __future__ import annotations

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.windows_tasks import task_plan  # noqa: E402


class TelemetryWindowsTasksTest(unittest.TestCase):
    def test_plan_separates_jobs_and_never_embeds_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / "storage"
            secrets = root / ".env.local"
            receivers, maintenance = task_plan(
                root, storage, secrets, start_date=date(2026, 10, 29)
            )
            receiver_xml = receivers.xml(user_id="demo-user")
            maintenance_xml = maintenance.xml(user_id="demo-user")
        self.assertIn("LogonTrigger", receiver_xml)
        self.assertIn("RestartOnFailure", receiver_xml)
        self.assertIn("run_telemetry_receivers_job.py", receiver_xml)
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

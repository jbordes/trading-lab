import tempfile
import unittest
from pathlib import Path

from tradinglab.mt5_setup import COLLECTORS, HELPER, stage_collectors


class MT5SetupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = self.root / "package"
        self.source.mkdir()
        for group in ("Experts", "Scripts", "Files"):
            (self.root / "MQL5" / group).mkdir(parents=True)
        for name in (*COLLECTORS, HELPER):
            (self.source / (name + ".ex5")).write_bytes(name.encode())
        for name in COLLECTORS:
            (self.source / (name + ".set")).write_bytes(b"test fixture")

    def stage(self):
        stage_collectors(self.root, self.source, self.source)

    def test_repeat_and_conflict(self):
        self.stage()
        self.stage()
        binary = self.root / "MQL5/Experts/TradingLab/TradingLabActivity.ex5"
        binary.write_bytes(b"existing version")
        with self.assertRaisesRegex(ValueError, "otra versión"):
            self.stage()
        self.assertEqual(binary.read_bytes(), b"existing version")
        self.assertTrue((self.root / f"MQL5/Scripts/TradingLab/{HELPER}.ex5").is_file())

    def test_resume_updates_activity_only_for_same_installation(self):
        self.stage()
        installed = self.root / "MQL5/Files/TradingLabSetup"
        activity = installed / "TradingLabActivity.set"
        activity.write_bytes(b"invalid previous preset")
        stage_collectors(self.root, self.source, self.source, resume=True)
        self.assertEqual(activity.read_bytes(), b"test fixture")
        (installed / "TradingLabTelemetry.set").write_bytes(b"another installation")
        activity.write_bytes(b"original")
        with self.assertRaises(ValueError):
            stage_collectors(self.root, self.source, self.source, resume=True)
        self.assertEqual(activity.read_bytes(), b"original")

    def test_missing_binary_and_default_ea_prevent_partial_deploy(self):
        template = self.root / "MQL5/Profiles/Templates/default.tpl"
        template.parent.mkdir(parents=True)
        template.write_text("<chart>\n<expert>", encoding="utf-16")
        with self.assertRaisesRegex(ValueError, "default.tpl"):
            self.stage()
        template.unlink()
        (self.source / "TradingLabActivity.ex5").unlink()
        with self.assertRaisesRegex(ValueError, "Falta"):
            self.stage()
        self.assertFalse((self.root / "MQL5/Files/TradingLabSetup").exists())

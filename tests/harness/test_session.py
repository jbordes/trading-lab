from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import session  # noqa: E402


class SessionLogTest(unittest.TestCase):
    @staticmethod
    def run_git(root: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    @staticmethod
    def complete(text: str) -> str:
        return (
            text.replace("**Estado:** Abierta", "**Estado:** Cerrada")
            .replace("[completar]", "No aplica")
            .replace("[completar o indicar “No aplica”]", "No aplica")
            .replace("[completar o indicar “Ninguna”]", "Ninguna")
            .replace("[referencia]", "No aplica")
        )

    def test_rendered_daily_log_has_v1_structure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-10-12-harness.md"
            moment = datetime(2026, 10, 12, 9, 30, tzinfo=ZoneInfo("Europe/Madrid"))
            path.write_text(self.complete(session.render_daily_log(moment, "Revisar el harness")), encoding="utf-8")
            self.assertEqual(session.validate_session(path, require_closed=True), [])

    def test_open_log_is_only_rejected_when_closure_is_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-10-12.md"
            moment = datetime(2026, 10, 12, 9, 30, tzinfo=ZoneInfo("Europe/Madrid"))
            path.write_text(session.render_daily_log(moment, "Comenzar la jornada"), encoding="utf-8")
            self.assertEqual(session.validate_session(path), [])
            errors = session.validate_session(path, require_closed=True)
            self.assertTrue(any("debe estar Cerrada" in error for error in errors))
            self.assertTrue(any("marcadores sin completar" in error for error in errors))

    def test_daily_date_must_match_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-10-12-wrong-date.md"
            moment = datetime(2026, 10, 13, 9, 30, tzinfo=ZoneInfo("Europe/Madrid"))
            path.write_text(session.render_daily_log(moment, "Probar fecha"), encoding="utf-8")
            errors = session.validate_session(path)
            self.assertTrue(any("no coincide con su nombre" in error for error in errors))

    def test_legacy_session_keeps_compatible_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-10-08-legacy.md"
            path.write_text("# Bitácora antigua\n\n**Fecha:** 8 de octubre de 2026\n\n## Objetivo\n\nConservar historia.\n", encoding="utf-8")
            self.assertEqual(session.validate_session(path, require_closed=True), [])

    def test_create_today_is_idempotent_and_accepts_topic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs" / "sessions").mkdir(parents=True)
            moment = datetime(2026, 10, 12, 9, 30, tzinfo=ZoneInfo("Europe/Madrid"))
            path, created = session.create_today(root, "Primera actividad", "harness", moment)
            same_path, created_again = session.create_today(root, "No sobrescribir", "harness", moment)
            self.assertEqual(path.name, "2026-10-12-harness.md")
            self.assertTrue(created)
            self.assertFalse(created_again)
            self.assertEqual(path, same_path)
            self.assertIn("Primera actividad", path.read_text(encoding="utf-8"))

    def test_guard_allows_only_today_logs_on_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_git(root, "init", "-b", "main")
            (root / "docs" / "sessions").mkdir(parents=True)
            (root / "README.md").write_text("# Test\n", encoding="utf-8")
            self.run_git(root, "add", "README.md")
            self.run_git(root, "-c", "user.name=Harness Test", "-c", "user.email=harness@example.invalid", "commit", "-m", "baseline")
            moment = datetime(2026, 10, 12, 9, 30, tzinfo=ZoneInfo("Europe/Madrid"))
            session.create_today(root, "Registrar trabajo", "harness", moment)
            self.assertEqual(session.guard_direct_main_publish(root, date(2026, 10, 12)), [])
            (root / "notes.txt").write_text("mezclado\n", encoding="utf-8")
            errors = session.guard_direct_main_publish(root, date(2026, 10, 12))
            self.assertTrue(any("rutas no autorizadas" in error for error in errors))

    def test_guard_rejects_old_log_and_feature_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_git(root, "init", "-b", "main")
            sessions = root / "docs" / "sessions"
            sessions.mkdir(parents=True)
            (sessions / "2026-10-11.md").write_text("# Bitácora histórica\n\n**Fecha:** 2026-10-11\n", encoding="utf-8")
            errors = session.guard_direct_main_publish(root, date(2026, 10, 12))
            self.assertTrue(any("rutas no autorizadas" in error for error in errors))
            self.run_git(root, "checkout", "-b", "feature/test")
            errors = session.guard_direct_main_publish(root, date(2026, 10, 12))
            self.assertTrue(any("solo puede ejecutarse desde main" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

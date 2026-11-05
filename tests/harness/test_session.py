from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
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
            path.write_text(
                self.complete(session.render_daily_log(moment, "Revisar el harness")),
                encoding="utf-8",
            )
            self.assertEqual(session.validate_session(path, require_closed=True), [])

    def test_open_log_is_only_rejected_when_closure_is_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-10-12.md"
            moment = datetime(2026, 10, 12, 9, 30, tzinfo=ZoneInfo("Europe/Madrid"))
            path.write_text(
                session.render_daily_log(moment, "Comenzar la jornada"), encoding="utf-8"
            )
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
            path.write_text(
                "# Bitácora antigua\n\n**Fecha:** 8 de octubre de 2026\n\n## Objetivo\n\nConservar historia.\n",
                encoding="utf-8",
            )
            self.assertEqual(session.validate_session(path, require_closed=True), [])

    def test_create_today_uses_canonical_daily_name_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs" / "sessions").mkdir(parents=True)
            moment = datetime(2026, 10, 12, 9, 30, tzinfo=ZoneInfo("Europe/Madrid"))
            path, created = session.create_today(root, "Primera actividad", moment=moment)
            same_path, created_again = session.create_today(root, "No sobrescribir", moment=moment)
            self.assertEqual(path.name, "2026-10-12.md")
            self.assertTrue(created)
            self.assertFalse(created_again)
            self.assertEqual(path, same_path)
            self.assertIn("Primera actividad", path.read_text(encoding="utf-8"))

    def test_create_today_accepts_an_exceptional_topic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs" / "sessions").mkdir(parents=True)
            moment = datetime(2026, 10, 12, 9, 30, tzinfo=ZoneInfo("Europe/Madrid"))
            path, created = session.create_today(root, "Actividad separada", "harness", moment)
            self.assertTrue(created)
            self.assertEqual(path.name, "2026-10-12-harness.md")

    def test_guard_allows_only_today_logs_on_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_git(root, "init", "-b", "main")
            (root / "docs" / "sessions").mkdir(parents=True)
            (root / "README.md").write_text("# Test\n", encoding="utf-8")
            self.run_git(root, "add", "README.md")
            self.run_git(
                root,
                "-c",
                "user.name=Harness Test",
                "-c",
                "user.email=harness@example.invalid",
                "commit",
                "-m",
                "baseline",
            )
            moment = datetime(2026, 10, 12, 9, 30, tzinfo=ZoneInfo("Europe/Madrid"))
            session.create_today(root, "Registrar trabajo", "harness", moment)
            self.assertEqual(session.guard_session_commit(root, date(2026, 10, 12)), [])
            (root / "notes.txt").write_text("mezclado\n", encoding="utf-8")
            errors = session.guard_session_commit(root, date(2026, 10, 12))
            self.assertTrue(any("rutas no autorizadas" in error for error in errors))

    def test_guard_rejects_old_log_and_feature_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_git(root, "init", "-b", "main")
            sessions = root / "docs" / "sessions"
            sessions.mkdir(parents=True)
            (sessions / "2026-10-11.md").write_text(
                "# Bitácora histórica\n\n**Fecha:** 2026-10-11\n", encoding="utf-8"
            )
            errors = session.guard_session_commit(root, date(2026, 10, 12))
            self.assertTrue(any("rutas no autorizadas" in error for error in errors))
            self.run_git(root, "checkout", "-b", "feature/test")
            errors = session.guard_session_commit(root, date(2026, 10, 12))
            self.assertTrue(any("solo puede ejecutarse desde main" in error for error in errors))

    def test_guard_uses_configured_stable_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_git(root, "init", "-b", "feature/remote-data-platform")
            (root / "docs" / "sessions").mkdir(parents=True)
            (root / "pyproject.toml").write_text(
                '[tool.tradinglab.workflow]\nstable-branch = "feature/remote-data-platform"\n',
                encoding="utf-8",
            )
            self.run_git(root, "add", "pyproject.toml")
            self.run_git(
                root,
                "-c",
                "user.name=Harness Test",
                "-c",
                "user.email=harness@example.invalid",
                "commit",
                "-m",
                "baseline",
            )
            moment = datetime(2026, 10, 30, 9, 30, tzinfo=ZoneInfo("Europe/Madrid"))
            session.create_today(root, "Registrar programa", moment=moment)

            self.assertEqual(session.guard_session_commit(root, date(2026, 10, 30)), [])

            self.run_git(root, "checkout", "-b", "feature/program-step")
            errors = session.guard_session_commit(root, date(2026, 10, 30))
            self.assertTrue(any("feature/remote-data-platform" in error for error in errors))


class SessionPublishGuardTest(unittest.TestCase):
    run_git = staticmethod(SessionLogTest.run_git)

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.today = date(2026, 11, 5)
        self.run_git(self.root, "init", "-b", "main")
        self.run_git(self.root, "config", "user.name", "Harness Test")
        self.run_git(self.root, "config", "user.email", "harness@example.invalid")
        (self.root / "docs" / "sessions").mkdir(parents=True)
        (self.root / "README.md").write_text("baseline\n", encoding="utf-8")
        self.commit()
        self.baseline = session.git_output(self.root, "rev-parse", "HEAD").strip()
        # Synthetic tracking ref only: no network, fetch or push is executed.
        self.run_git(self.root, "remote", "add", "origin", str(self.root / "unused-remote"))
        self.run_git(self.root, "update-ref", "refs/remotes/origin/main", self.baseline)
        self.run_git(self.root, "branch", "--set-upstream-to=origin/main", "main")

    def commit(self) -> None:
        self.run_git(self.root, "add", "--all")
        self.run_git(self.root, "commit", "-m", "synthetic test change")

    def log(self, day: date | None = None, suffix: str = "") -> Path:
        day = day or self.today
        target = self.root / "docs" / "sessions" / f"{day.isoformat()}{suffix}.md"
        moment = datetime(day.year, day.month, day.day, 9, tzinfo=ZoneInfo("Europe/Madrid"))
        target.write_text(session.render_daily_log(moment, "Trabajo de prueba"), encoding="utf-8")
        return target

    def errors(self) -> list[str]:
        return session.guard_direct_session_publish(self.root, self.today)

    def test_allows_multiple_today_only_commits_and_compatibility_wrapper(self) -> None:
        target = self.log()
        self.commit()
        target.write_text(
            target.read_text(encoding="utf-8") + "\nOtra actividad.\n", encoding="utf-8"
        )
        self.commit()
        self.assertEqual(self.errors(), [])
        self.assertEqual(session.guard_direct_main_publish(self.root, self.today), [])

    def test_preparation_cannot_authorize_uncommitted_push(self) -> None:
        self.log()
        self.assertEqual(session.guard_session_commit(self.root, self.today), [])
        self.assertTrue(any("árbol limpio" in error for error in self.errors()))

    def test_rejects_product_commit_hidden_by_revert(self) -> None:
        (self.root / "README.md").write_text("product change\n", encoding="utf-8")
        self.commit()
        self.run_git(self.root, "revert", "--no-edit", "HEAD")
        self.log()
        self.commit()
        self.assertTrue(any("README.md" in error for error in self.errors()))

    def test_rejects_old_day_and_day_rollover(self) -> None:
        self.log(date(2026, 11, 4))
        self.commit()
        self.log()
        self.commit()
        self.assertTrue(any("2026-11-04.md" in error for error in self.errors()))

    def test_rejects_rename_even_between_today_logs(self) -> None:
        target = self.log()
        self.commit()
        self.run_git(self.root, "mv", str(target), str(target.with_name("2026-11-05-extra.md")))
        self.commit()
        self.assertTrue(any("(D)" in error for error in self.errors()))

    def test_rejects_deletion(self) -> None:
        target = self.log()
        self.commit()
        self.run_git(self.root, "rm", str(target))
        self.commit()
        self.assertTrue(any("(D)" in error for error in self.errors()))

    def test_rejects_non_regular_file_mode(self) -> None:
        target = self.log()
        self.commit()
        self.run_git(self.root, "update-index", "--chmod=+x", str(target))
        self.run_git(self.root, "commit", "-m", "unexpected executable mode")
        self.assertTrue(any("cambio no autorizado" in error for error in self.errors()))

    def test_validates_each_committed_blob_even_if_later_repaired(self) -> None:
        target = self.log()
        target.write_text("invalid session\n", encoding="utf-8")
        self.commit()
        self.log()
        self.commit()
        self.assertTrue(any("no comienza" in error for error in self.errors()))

    def test_rejects_missing_and_inexact_tracking_references(self) -> None:
        self.log()
        self.commit()
        self.run_git(self.root, "update-ref", "refs/remotes/origin/other", self.baseline)
        self.run_git(self.root, "branch", "--set-upstream-to=origin/other", "main")
        self.assertTrue(any("exactamente" in error for error in self.errors()))
        self.run_git(self.root, "branch", "--unset-upstream")
        self.assertTrue(any("No se pudo verificar" in error for error in self.errors()))
        self.run_git(self.root, "branch", "--set-upstream-to=origin/main", "main")
        self.run_git(self.root, "update-ref", "-d", "refs/remotes/origin/main")
        self.assertTrue(self.errors())

    def test_rejects_diverged_remote_reference(self) -> None:
        self.log()
        self.commit()
        self.run_git(self.root, "checkout", "-b", "synthetic-remote", self.baseline)
        (self.root / "README.md").write_text("remote change\n", encoding="utf-8")
        self.commit()
        remote = session.git_output(self.root, "rev-parse", "HEAD").strip()
        self.run_git(self.root, "update-ref", "refs/remotes/origin/main", remote)
        self.run_git(self.root, "checkout", "main")
        self.assertTrue(any("no es ancestro" in error for error in self.errors()))

    def test_rejects_merge_commit(self) -> None:
        self.run_git(self.root, "checkout", "-b", "synthetic-feature")
        self.log()
        self.commit()
        self.run_git(self.root, "checkout", "main")
        self.run_git(self.root, "merge", "--no-ff", "synthetic-feature", "-m", "merge")
        self.assertTrue(any("no se admiten merges" in error for error in self.errors()))

    def test_rejects_empty_outgoing_range_and_feature_branch(self) -> None:
        self.assertTrue(any("No hay commits" in error for error in self.errors()))
        self.run_git(self.root, "checkout", "-b", "feature/test")
        self.assertTrue(any("solo puede ejecutarse" in error for error in self.errors()))

    def test_preparation_rejects_renames_of_today_log(self) -> None:
        target = self.log()
        self.commit()
        self.run_git(self.root, "mv", str(target), str(target.with_name("2026-11-05-extra.md")))
        errors = session.guard_session_commit(self.root, self.today)
        self.assertTrue(any("rutas no autorizadas" in error for error in errors))

    def test_publish_uses_configured_integration_branch(self) -> None:
        stable = "feature/remote-data-platform"
        self.run_git(self.root, "branch", "-m", stable)
        (self.root / "pyproject.toml").write_text(
            f'[tool.tradinglab.workflow]\nstable-branch = "{stable}"\n', encoding="utf-8"
        )
        self.commit()
        self.run_git(self.root, "update-ref", f"refs/remotes/origin/{stable}", "HEAD")
        self.run_git(self.root, "branch", f"--set-upstream-to=origin/{stable}", stable)
        self.log()
        self.commit()
        self.assertEqual(self.errors(), [])

    def test_rejects_changes_made_during_validation(self) -> None:
        self.log()
        self.commit()

        def concurrent_edit(*_: object) -> list[str]:
            (self.root / "README.md").write_text("concurrent edit\n", encoding="utf-8")
            return []

        with patch.object(session, "validate_session_text", side_effect=concurrent_edit):
            self.assertTrue(any("Git cambió" in error for error in self.errors()))

    def test_cli_defaults_to_push_and_requires_explicit_commit_phase(self) -> None:
        with patch.object(sys, "argv", ["session.py", "guard-publish"]):
            self.assertEqual(session.parse_args().phase, "push")
        with patch.object(sys, "argv", ["session.py", "guard-publish", "--phase", "commit"]):
            self.assertEqual(session.parse_args().phase, "commit")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import session  # noqa: E402


class SessionLogTest(unittest.TestCase):
    def test_rendered_session_has_v1_structure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-10-12-test-session.md"
            text = session.render_session(date(2026, 10, 12), "test-session", "Probar el formato")
            text = text.replace("**Estado:** En curso", "**Estado:** Cerrada")
            text = text.replace("[completar]", "No aplica")
            text = text.replace("[completar o indicar “No aplica”]", "No aplica")
            text = text.replace("[completar o enlazar el ADR]", "No aplica")
            text = text.replace("[comandos, comprobaciones y resultado]", "Validación correcta")
            text = text.replace("[completar o indicar “Ninguna”]", "Ninguna")
            text = text.replace("[completar o indicar “No aplica”]", "No aplica")
            path.write_text(text, encoding="utf-8")

            errors = session.validate_session(path, require_closed=True)

            self.assertEqual(errors, [])

    def test_open_session_is_rejected_when_closed_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-10-12-open-session.md"
            path.write_text(
                session.render_session(date(2026, 10, 12), "open-session", "Probar cierre"),
                encoding="utf-8",
            )

            errors = session.validate_session(path, require_closed=True)

            self.assertTrue(any("debe estar Cerrada" in error for error in errors))
            self.assertTrue(any("marcadores sin completar" in error for error in errors))

    def test_v1_date_must_match_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-10-12-wrong-date.md"
            text = session.render_session(date(2026, 10, 13), "wrong-date", "Probar fecha")
            path.write_text(text, encoding="utf-8")

            errors = session.validate_session(path)

            self.assertTrue(any("no coincide con su nombre" in error for error in errors))

    def test_legacy_session_keeps_compatible_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-10-08-legacy.md"
            path.write_text(
                "# Bitácora antigua\n\n**Fecha:** 8 de octubre de 2026\n\n## Objetivo\n\nConservar historia.\n",
                encoding="utf-8",
            )

            errors = session.validate_session(path, require_closed=True)

            self.assertEqual(errors, [])

    def test_create_session_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs" / "sessions").mkdir(parents=True)
            session.create_session(root, "same-day", "Primera", date(2026, 10, 12))

            with self.assertRaises(FileExistsError):
                session.create_session(root, "same-day", "Segunda", date(2026, 10, 12))


if __name__ == "__main__":
    unittest.main()

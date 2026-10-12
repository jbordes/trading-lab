from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("tradinglab_check", ROOT / "scripts" / "check.py")
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class HarnessChecksTest(unittest.TestCase):
    def test_repository_boundaries_reject_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            forbidden = Path("_storage/run/report.ex5")
            path = root / forbidden
            path.parent.mkdir(parents=True)
            path.write_bytes(b"binary")

            errors = CHECK.check_repository_boundaries(root, [forbidden])

            self.assertTrue(any("Storage operativo" in error for error in errors))
            self.assertTrue(any("Archivo prohibido" in error for error in errors))

    def test_repository_boundaries_allow_storage_source_module(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = Path("packages/storage/client.py")
            path = root / source
            path.parent.mkdir(parents=True)
            path.write_text("# storage adapter\n", encoding="utf-8")

            errors = CHECK.check_repository_boundaries(root, [source])

            self.assertEqual(errors, [])

    def test_text_safety_detects_private_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = Path("unsafe.txt")
            marker = "-----BEGIN " + "PRIVATE KEY-----\n"
            (root / relative).write_text(marker, encoding="utf-8")

            errors = CHECK.check_text_safety(root, [relative])

            self.assertEqual(errors, ["Posible private key en unsafe.txt"])

    def test_text_safety_detects_assigned_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = Path("config.json")
            (root / relative).write_text('{"token": "real-looking-token-123456"}\n', encoding="utf-8")

            errors = CHECK.check_text_safety(root, [relative])

            self.assertEqual(errors, ["Posible assigned secret en config.json"])

    def test_markdown_links_accept_existing_relative_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            (docs / "target.md").write_text("# Target\n", encoding="utf-8")
            (docs / "source.md").write_text("[Target](target.md)\n", encoding="utf-8")

            errors = CHECK.check_markdown_links(root, [Path("docs/source.md")])

            self.assertEqual(errors, [])

    def test_markdown_links_reject_missing_relative_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            (docs / "source.md").write_text("[Missing](missing.md)\n", encoding="utf-8")

            errors = CHECK.check_markdown_links(root, [Path("docs/source.md")])

            self.assertEqual(errors, ["Enlace Markdown roto en docs/source.md: missing.md"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("tradinglab_check", ROOT / "scripts" / "check.py")
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class HarnessChecksTest(unittest.TestCase):
    @staticmethod
    def run_git(root: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

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
            payload = '{"to' + 'ken": "real-looking-token-123456"}\n'
            (root / relative).write_text(payload, encoding="utf-8")

            errors = CHECK.check_text_safety(root, [relative])

            self.assertEqual(errors, ["Posible assigned secret en config.json"])

    def test_text_safety_detects_prefixed_environment_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = Path(".env.example")
            payload = "BROKER_API_" + "TOKEN=real-looking-token-123456\n"
            (root / relative).write_text(payload, encoding="utf-8")

            errors = CHECK.check_text_safety(root, [relative])

            self.assertEqual(errors, ["Posible assigned secret en .env.example"])

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

    def test_adr_validation_accepts_required_structure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adr = root / "docs" / "adr" / "0001-test-decision.md"
            adr.parent.mkdir(parents=True)
            adr.write_text(
                "# ADR-0001: Test\n\n**Estado:** accepted\n\n**Fecha:** 2026-10-12\n\n"
                "## Contexto\n\nContexto.\n\n## Alternativas consideradas\n\nUna.\n\n"
                "## Decisión\n\nDecisión.\n\n## Consecuencias\n\nConsecuencia.\n",
                encoding="utf-8",
            )

            errors = CHECK.check_adrs(root)

            self.assertEqual(errors, [])

    def test_code_quality_reports_the_failing_tool(self) -> None:
        completed = (
            subprocess.CompletedProcess(args=[], returncode=0),
            subprocess.CompletedProcess(args=[], returncode=1),
        )
        with patch.object(CHECK.subprocess, "run", side_effect=completed) as run:
            errors = CHECK.run_code_quality(Path("."))

        self.assertEqual(errors, ["Falló lint de Ruff"])
        self.assertEqual(run.call_count, 2)

    def test_full_test_runner_includes_harness_and_product_suites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests" / "harness").mkdir(parents=True)
            (root / "tests" / "unit").mkdir(parents=True)
            completed = (
                subprocess.CompletedProcess(args=[], returncode=0),
                subprocess.CompletedProcess(args=[], returncode=1),
            )
            with patch.object(CHECK.subprocess, "run", side_effect=completed) as run:
                errors = CHECK.run_unit_tests(root)

        self.assertEqual(errors, ["Fallaron los tests en tests/unit"])
        self.assertEqual(run.call_count, 2)
        self.assertIn("tests/harness", run.call_args_list[0].args[0])
        self.assertIn("tests/unit", run.call_args_list[1].args[0])

    def test_feature_branch_rejects_daily_log_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_git(root, "init", "-b", "main")
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
            self.run_git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
            self.run_git(root, "checkout", "-b", "feature/test")
            session_path = root / "docs" / "sessions" / "2026-10-12-ci-check.md"
            session_path.parent.mkdir(parents=True)
            session_path.write_text("# Session\n", encoding="utf-8")
            self.run_git(root, "add", session_path.relative_to(root).as_posix())

            with patch.dict(os.environ, {"GITHUB_BASE_REF": "main"}, clear=False):
                errors = CHECK.check_session_change_policy(root)

            self.assertTrue(
                any("no pueden modificar bitácoras diarias" in error for error in errors)
            )

    def test_feature_branch_does_not_require_a_daily_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_git(root, "init", "-b", "main")
            (root / "README.md").write_text("# Base\n", encoding="utf-8")
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
            self.run_git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
            self.run_git(root, "checkout", "-b", "feature/test")
            (root / "README.md").write_text("# Cambio\n", encoding="utf-8")
            self.run_git(root, "add", "README.md")

            with patch.dict(os.environ, {"GITHUB_BASE_REF": "main"}, clear=False):
                errors = CHECK.check_session_change_policy(root)

            self.assertEqual(errors, [])

    def test_local_feature_ignores_daily_logs_added_later_to_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_git(root, "init", "-b", "main")
            (root / "README.md").write_text("# Base\n", encoding="utf-8")
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
            self.run_git(root, "checkout", "-b", "feature/test")
            self.run_git(root, "checkout", "main")
            session_path = root / "docs" / "sessions" / "2026-10-12.md"
            session_path.parent.mkdir(parents=True)
            session_path.write_text("# Bitácora en main\n", encoding="utf-8")
            self.run_git(root, "add", session_path.relative_to(root).as_posix())
            self.run_git(
                root,
                "-c",
                "user.name=Harness Test",
                "-c",
                "user.email=harness@example.invalid",
                "commit",
                "-m",
                "daily log",
            )
            self.run_git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
            self.run_git(root, "checkout", "feature/test")
            (root / "README.md").write_text("# Feature\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {"GITHUB_BASE_REF": "", "TRADINGLAB_BASE_SHA": ""},
                clear=False,
            ):
                errors = CHECK.check_session_change_policy(root)

            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()

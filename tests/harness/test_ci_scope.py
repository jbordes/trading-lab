from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ci_scope


class CIScopeTest(unittest.TestCase):
    def test_only_documentation_selects_docs(self) -> None:
        for paths, expected in (
            ("docs/a.md\0README.md\0", "docs"),
            ("docs/a.md\0src/app.py\0", "full"),
            ("docs/tool.py\0", "full"),
            ("uv.lock\0", "full"),
            (".github/workflows/quality.yml\0", "full"),
            ("", "full"),
            ("src/old.py\0docs/new.md\0", "full"),
        ):
            with self.subTest(paths=paths), patch.object(ci_scope, "git", return_value=paths):
                self.assertEqual(
                    ci_scope.validation_mode(Path("."), "push", "a" * 40, "b" * 40), expected
                )

    def test_uncertain_or_manual_runs_stay_full(self) -> None:
        for event, base in (("workflow_dispatch", "a" * 40), ("push", ""), ("push", "0" * 40)):
            with patch.object(ci_scope, "git") as git:
                self.assertEqual(ci_scope.validation_mode(Path("."), event, base, "b" * 40), "full")
                git.assert_not_called()
        with patch.object(ci_scope, "git", side_effect=ValueError("missing base")):
            self.assertEqual(
                ci_scope.validation_mode(Path("."), "push", "a" * 40, "b" * 40), "full"
            )

    def test_pr_uses_merge_base_and_disables_rename_detection(self) -> None:
        with patch.object(ci_scope, "git", side_effect=["c" * 40, "docs/a.md\0"]) as git:
            self.assertEqual(
                ci_scope.validation_mode(Path("."), "pull_request", "a" * 40, "b" * 40), "docs"
            )
            self.assertEqual(
                git.call_args.args[1:],
                ("diff", "--name-only", "--no-renames", "-z", "c" * 40, "b" * 40, "--"),
            )

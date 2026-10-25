from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import change


class ChangeInspectionTest(unittest.TestCase):
    def test_recommendations_are_conservative(self) -> None:
        for paths, expected in (
            ([], "sin cambios"),
            (["docs/guide.md"], "documentación"),
            (["docs/tool.py"], "sin clasificar"),
            (["pyproject.toml"], "sin clasificar"),
            (["scripts/check.py"], "harness"),
            (["src/tradinglab/app.py"], "producto"),
            (["README.md", "src/tradinglab/app.py"], "mixto"),
        ):
            with self.subTest(paths=paths):
                self.assertEqual(change.recommend(paths)["tipo"], expected)

    def test_git_includes_staged_unstaged_deleted_and_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args: str) -> None:
                subprocess.run(
                    ["git", *args], cwd=root, check=True, capture_output=True, timeout=15
                )

            git("init")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            for name in ("README.md", "delete.md", "staged.md"):
                (root / name).write_text("original", encoding="utf-8")
            (root / ".gitignore").write_text("ignored.md\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "initial")
            self.assertEqual(change.inspect(root, "HEAD")["cantidad_archivos"], 0)
            (root / "README.md").write_text("updated", encoding="utf-8")
            (root / "delete.md").unlink()
            (root / "staged.md").write_text("staged", encoding="utf-8")
            git("add", "staged.md")
            (root / "new file.md").write_text("new", encoding="utf-8")
            (root / "ignored.md").write_text("ignored", encoding="utf-8")
            before = change.git(root, "status", "--porcelain=v1", "-z")
            self.assertEqual(
                change.inspect(root, "HEAD")["archivos"],
                ["README.md", "delete.md", "new file.md", "staged.md"],
            )
            self.assertEqual(change.git(root, "status", "--porcelain=v1", "-z"), before)
            with self.assertRaises(ValueError):
                change.inspect(root, "missing-reference")
            git("add", ".")
            git("commit", "-m", "changes")
            git("update-ref", "refs/remotes/origin/main", "HEAD^")
            git("checkout", "-b", "feature/example")
            self.assertEqual(change.inspect(root)["cantidad_archivos"], 4)
            self.assertEqual(change.inspect(root, "HEAD")["cantidad_archivos"], 0)


if __name__ == "__main__":
    unittest.main()

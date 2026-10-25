"""Choose CI scope conservatively; never execute validations."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from change import category, git


def validation_mode(root: Path, event: str, base: str, head: str) -> str:
    if event not in {"push", "pull_request"}:
        return "full"
    if any(not re.fullmatch(r"[0-9a-f]{40}", sha) or set(sha) == {"0"} for sha in (base, head)):
        return "full"
    try:
        if event == "pull_request":
            base = git(root, "merge-base", base, head).strip()
        paths = git(root, "diff", "--name-only", "--no-renames", "-z", base, head, "--")
    except ValueError, OSError, subprocess.TimeoutExpired:
        return "full"
    changed = [path for path in paths.split("\0") if path]
    return (
        "docs" if changed and all(category(path) == "documentación" for path in changed) else "full"
    )


def main() -> None:
    mode = validation_mode(
        Path(__file__).resolve().parents[1],
        os.environ.get("GITHUB_EVENT_NAME", ""),
        os.environ.get("TRADINGLAB_BASE_SHA", ""),
        os.environ.get("TRADINGLAB_HEAD_SHA", ""),
    )
    systems = (
        ["ubuntu-latest"]
        if mode == "docs"
        else ["ubuntu-latest", "windows-latest", "macos-15-intel"]
    )
    print(f"mode={mode}")
    print(f"matrix={json.dumps({'os': systems}, separators=(',', ':'))}")


if __name__ == "__main__":
    main()

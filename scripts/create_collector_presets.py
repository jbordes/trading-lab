#!/usr/bin/env python3
"""Generate collector presets; account identity is read from standard input, never logged."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tradinglab.collector_presets import create_presets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        data = json.loads(sys.stdin.read(4096))
        path = create_presets(
            args.data_dir, data["login"], data["history_start"], resume=args.resume
        )
        print(f"Presets privados creados en: {path}")
    except OSError, ValueError, KeyError, TypeError:
        print(
            "No se pudieron crear los presets: revise cuenta, fecha y destino; no se sobrescriben archivos.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

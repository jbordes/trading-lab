#!/usr/bin/env python3
"""Generate collector presets; account identity is read from standard input, never logged."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tradinglab.collector_presets import PresetConflict, create_presets
from tradinglab.mt5_setup import stage_collectors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--mt5-data-dir", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(sys.stdin.read(4096))
        path = create_presets(
            args.data_dir, data["login"], data["history_start"], resume=args.resume
        )
    except PresetConflict as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except PermissionError:
        print(
            "Acceso denegado a los archivos privados. Use el usuario de la instalación.",
            file=sys.stderr,
        )
        return 1
    except OSError, KeyError, TypeError, ValueError:
        print(
            "No se pudieron crear los presets: revise cuenta, fecha y destino; no se sobrescriben archivos.",
            file=sys.stderr,
        )
        return 1
    if args.mt5_data_dir:
        try:
            stage_collectors(
                args.mt5_data_dir,
                Path(__file__).resolve().parents[1] / "collectors",
                path,
                resume=args.resume,
            )
        except (ValueError, OSError) as exc:
            print(f"No se pudo preparar MT5: {exc}", file=sys.stderr)
            return 1
    print(f"Presets privados creados en: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

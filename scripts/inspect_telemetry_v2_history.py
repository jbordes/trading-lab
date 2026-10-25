#!/usr/bin/env python3
"""Inspect one bounded page of durable telemetry v2 activity."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.sqlite_store_v2 import V2StorageError, open_v2_registry

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-db", type=Path, required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--entity", choices=("deal", "order"), required=True)
    parser.add_argument("--from-msc", type=int, required=True)
    parser.add_argument("--to-msc", type=int, required=True)
    parser.add_argument("--magic-number")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--cursor")
    args = parser.parse_args(argv)
    try:
        with open_v2_registry(args.sqlite_db, read_only=True) as registry:
            page = registry.activity_page(
                args.account_id,
                args.entity,
                from_msc=args.from_msc,
                to_msc=args.to_msc,
                magic_number=args.magic_number,
                limit=args.limit,
                cursor=args.cursor,
            )
            coverage = registry.coverage_report(
                args.account_id,
                args.entity,
                from_msc=args.from_msc,
                to_msc=args.to_msc,
            )
        print(
            json.dumps(
                {"page": asdict(page), "coverage": asdict(coverage)},
                ensure_ascii=False,
                indent=2,
            )
        )
    except (OSError, ValueError, V2StorageError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

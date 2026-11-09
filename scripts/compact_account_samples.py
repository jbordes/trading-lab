#!/usr/bin/env python3
"""Preview one old broker day's account samples; compaction requires --apply."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.account_sample_retention import compact_account_samples
    from tradinglab.telemetry.sqlite_store import TelemetryStorageError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--broker-day", type=date.fromisoformat, required=True)
    parser.add_argument("--current-broker-day", type=date.fromisoformat, required=True)
    parser.add_argument("--max-messages", type=int, default=1000)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = compact_account_samples(
            args.db,
            account_id=args.account_id,
            broker_day=args.broker_day,
            current_broker_day=args.current_broker_day,
            apply=args.apply,
            max_messages=args.max_messages,
        )
    except OSError, ValueError, TelemetryStorageError:
        print("Compactación rechazada: revise cuenta, días del broker, esquema e integridad.")
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

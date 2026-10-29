#!/usr/bin/env python3
"""Start durable telemetry receivers or the dashboard as independent components."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

RECEIVER_PROMPTS = {
    "TRADINGLAB_TELEMETRY_TOKEN": "Token del collector v1",
    "TRADINGLAB_TELEMETRY_LIVE_TOKEN": "Token live v2",
    "TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN": "Token de TradingLabActivity v2",
    "TRADINGLAB_TELEMETRY_READ_TOKEN": "Token de lectura v2",
}
DASHBOARD_PROMPTS = {
    "TRADINGLAB_TELEMETRY_TOKEN": "Token del collector v1",
    "TRADINGLAB_DASHBOARD_TOKEN": "Token de acceso al dashboard",
    "TRADINGLAB_TELEMETRY_READ_TOKEN": "Token de lectura v2",
}


def port(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("El puerto debe estar entre 1 y 65535")
    return parsed


def utc_offset_minutes(value: str) -> int:
    parsed = int(value)
    if not -14 * 60 <= parsed <= 14 * 60:
        raise argparse.ArgumentTypeError("El offset debe estar entre -840 y 840 minutos")
    return parsed


def filename(value: str) -> str:
    candidate = Path(value)
    if candidate.name != value or candidate.suffix != ".sqlite3":
        raise argparse.ArgumentTypeError("Indique solo un nombre de archivo .sqlite3")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=("receivers", "dashboard"))
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(os.environ.get("TRADINGLAB_STORAGE_ROOT", ROOT / "_storage")),
        help="Directorio local persistente que contiene las bases.",
    )
    parser.add_argument("--v1-database", type=filename, default="piloto.sqlite3")
    parser.add_argument("--v2-database", type=filename, default="piloto-v2.sqlite3")
    parser.add_argument("--live-source-id", default="juampi-demo-01")
    parser.add_argument("--activity-source-id", default="juampi-demo-activity-v2")
    parser.add_argument("--account-id", default="cuenta-demo-juampi")
    parser.add_argument("--v1-port", type=port, default=8776)
    parser.add_argument("--v2-port", type=port, default=8777)
    parser.add_argument("--dashboard-port", type=port, default=8775)
    parser.add_argument("--broker-utc-offset-minutes", type=utc_offset_minutes, default=120)
    return parser.parse_args(argv)


def _read_environment(component: str) -> dict[str, str]:
    environment = dict(os.environ)
    prompts = RECEIVER_PROMPTS if component == "receivers" else DASHBOARD_PROMPTS
    for name, label in prompts.items():
        if environment.get(name):
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            environment[name] = getpass.getpass(f"{label} (oculto): ")
    return environment


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.runtime_v2 import (
        V2PilotRuntimeConfig,
        run_v2_dashboard,
        run_v2_receivers,
    )

    args = parse_args(argv)
    try:
        storage_root = args.storage_root.resolve(strict=True)
        config = V2PilotRuntimeConfig(
            live_source_id=args.live_source_id,
            activity_source_id=args.activity_source_id,
            account_id=args.account_id,
            v1_database=storage_root / args.v1_database,
            v2_database=storage_root / args.v2_database,
            storage_root=storage_root,
            v1_port=args.v1_port,
            v2_port=args.v2_port,
            dashboard_port=args.dashboard_port,
            broker_utc_offset_minutes=args.broker_utc_offset_minutes,
        )
        environment = _read_environment(args.component)
        if args.component == "receivers":
            run_v2_receivers(ROOT, config, environment)
        else:
            run_v2_dashboard(ROOT, config, environment)
    except KeyboardInterrupt:
        label = "Receptores" if args.component == "receivers" else "Dashboard"
        print(f"\n{label} detenido; MT5 no fue modificado.")
        return 0
    except (ValueError, RuntimeError, OSError, EOFError, getpass.GetPassWarning) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

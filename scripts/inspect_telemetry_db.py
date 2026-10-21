#!/usr/bin/env python3
"""Summarize one local telemetry database without exposing raw trading records."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.inspection import InspectionPlan, TelemetryInspectionError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filename", required=True, help="Base .sqlite3 bajo _storage/.")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Ejecutar además las comprobaciones completas de integridad y relaciones.",
    )
    args = parser.parse_args(argv)
    try:
        summary = InspectionPlan(ROOT, args.filename).inspect(verify=args.verify)
    except (ValueError, FileNotFoundError, OSError, TelemetryInspectionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Base: {summary.database}")
    print(f"Tamaño: {summary.size_bytes} bytes; esquema: {summary.schema_version}")
    print(f"Fuentes: {', '.join(summary.source_ids) or 'ninguna'}")
    print(
        "Mensajes: "
        f"{summary.message_count} ({summary.snapshot_count} snapshots, "
        f"{summary.heartbeat_count} heartbeats); sesiones: {summary.session_count}"
    )
    print(
        f"Cobertura: {summary.first_captured_at or 'sin datos'} -> "
        f"{summary.last_captured_at or 'sin datos'}"
    )
    print(
        "Últimos snapshots por fuente: "
        f"{summary.latest_positions} posiciones, {summary.latest_orders} órdenes, "
        f"historial={summary.latest_history_status or 'no informado'}"
    )
    print(f"Deals históricos únicos: {summary.unique_historical_deals}")
    print(f"Magic Numbers observados: {', '.join(summary.magic_numbers) or 'ninguno'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

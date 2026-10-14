#!/usr/bin/env python3
"""Capture a read-only MT5 diagnostic into local immutable evidence."""

from __future__ import annotations

import argparse
import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path


def parse_datetime(value: str) -> datetime:
    """Parse an ISO 8601 instant and require an explicit timezone."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Fecha ISO 8601 inválida") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("La fecha debe incluir zona horaria")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-from", required=True, type=parse_datetime)
    parser.add_argument("--date-to", required=True, type=parse_datetime)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida parámetros y muestra el destino sin conectarse a MT5.",
    )
    return parser.parse_args(argv)


def resolve_output_path(
    root: Path,
    requested: Path | None,
    captured_at: datetime,
) -> Path:
    """Resolve evidence below the repository's ignored storage boundary."""

    storage_root = (root / "_storage").resolve()
    candidate = requested or (
        storage_root / "mt5-diagnostics" / f"mt5-capture-{captured_at:%Y%m%dT%H%M%SZ}.json"
    )
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(storage_root):
        raise ValueError("La evidencia MT5 debe guardarse dentro de _storage/")
    return resolved


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from tradinglab.incubation.diagnostic import (
        CaptureWindow,
        DiagnosticError,
        collect_mt5_diagnostic,
        write_capture_evidence,
    )

    args = parse_args(argv)
    try:
        window = CaptureWindow(args.date_from, args.date_to)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    captured_at = datetime.now(UTC)
    try:
        output = resolve_output_path(root, args.output, captured_at)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(
            f"Diagnóstico MT5 de solo lectura: {window.date_from.isoformat()} -> "
            f"{window.date_to.isoformat()}"
        )
        print(f"Destino local: {output}")
        return 0

    try:
        mt5 = importlib.import_module("MetaTrader5")
    except ModuleNotFoundError:
        print(
            "Error: MetaTrader5 no está instalado en este entorno Windows.",
            file=sys.stderr,
        )
        return 3

    try:
        payload = collect_mt5_diagnostic(mt5, window, captured_at=captured_at)
        result = write_capture_evidence(payload, output)
    except (DiagnosticError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    state = "ya existía" if result.already_existed else "creada"
    print(f"Evidencia {state}: {result.capture_path}")
    print(f"Manifest: {result.manifest_path}")
    print(f"SHA-256: {result.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

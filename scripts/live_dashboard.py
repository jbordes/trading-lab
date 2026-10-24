#!/usr/bin/env python3
"""Run the TradingLab read-only MT5 dashboard on localhost."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import warnings
from datetime import timedelta
from pathlib import Path


def interval(value: str) -> float:
    parsed = float(value)
    if not 2.0 <= parsed <= 3600.0:
        raise argparse.ArgumentTypeError("El intervalo debe estar entre 2 y 3600 segundos")
    return parsed


def port(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("El puerto debe estar entre 1 y 65535")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--demo", action="store_true", help="Usa datos sintéticos sin conectar MT5."
    )
    source.add_argument(
        "--telemetry",
        action="store_true",
        help="Lee el receptor push local del collector MQL5.",
    )
    parser.add_argument("--interval", type=interval, default=5.0, help="Segundos entre lecturas.")
    parser.add_argument("--port", type=port, default=8765, help="Puerto local.")
    parser.add_argument(
        "--telemetry-port", type=port, default=8766, help="Puerto local del receptor push."
    )
    parser.add_argument(
        "--telemetry-source",
        help="SourceId no sensible configurado en el colector MQL5.",
    )
    parser.add_argument(
        "--telemetry-max-age",
        type=interval,
        default=30.0,
        help="Segundos máximos sin una nueva muestra antes de degradar la vista.",
    )
    args = parser.parse_args(argv)
    if args.telemetry and not args.telemetry_source:
        parser.error("--telemetry requiere --telemetry-source")
    if args.demo and args.telemetry_source:
        parser.error("--telemetry-source solo se admite con --telemetry")
    return args


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from tradinglab.dashboard.auth import DASHBOARD_TOKEN_ENV, validate_dashboard_token
    from tradinglab.dashboard.service import LiveDashboardService
    from tradinglab.dashboard.snapshot import DemoSnapshotSource
    from tradinglab.dashboard.telemetry import (
        TELEMETRY_TOKEN_ENV,
        LoopbackTelemetryClient,
        TelemetrySnapshotSource,
    )
    from tradinglab.dashboard.web import create_server

    args = parse_args(argv)
    access = os.environ.get(DASHBOARD_TOKEN_ENV, "")
    if not access:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                access = getpass.getpass("Token de acceso al dashboard (oculto): ")
        except EOFError, KeyboardInterrupt, getpass.GetPassWarning:
            print("Error: no se pudo leer el token del dashboard de forma oculta.", file=sys.stderr)
            return 2
    try:
        validate_dashboard_token(access)
    except ValueError as exc:
        print(f"Error: configure {DASHBOARD_TOKEN_ENV}: {exc}", file=sys.stderr)
        return 2
    if args.demo:
        source = DemoSnapshotSource()
    elif args.telemetry:
        assert args.telemetry_source is not None
        ingest = os.environ.get(TELEMETRY_TOKEN_ENV, "")
        if len(ingest) < 24:
            print(
                f"Error: configure {TELEMETRY_TOKEN_ENV} con el mismo token del receptor.",
                file=sys.stderr,
            )
            return 2
        if ingest == access:
            print(
                "Error: los tokens de telemetría y dashboard deben ser distintos.", file=sys.stderr
            )
            return 2
        if args.port == args.telemetry_port:
            print("Error: dashboard y receptor deben usar puertos diferentes.", file=sys.stderr)
            return 2
        try:
            source = TelemetrySnapshotSource(
                LoopbackTelemetryClient(
                    token=ingest,
                    source_id=args.telemetry_source,
                    port=args.telemetry_port,
                ),
                source_id=args.telemetry_source,
                max_age=timedelta(seconds=args.telemetry_max_age),
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
    else:  # pragma: no cover - argparse requires one of the two modes
        raise AssertionError("modo de dashboard no resuelto")

    service = LiveDashboardService(
        source,
        interval_seconds=args.interval,
        health_provider=source if isinstance(source, TelemetrySnapshotSource) else None,
    )
    server = create_server(
        service,
        port=args.port,
        dashboard_token=access,
        history_provider=source if isinstance(source, TelemetrySnapshotSource) else None,
    )
    service.start()
    print(f"TradingLab Live (solo lectura): http://127.0.0.1:{server.server_port}")
    print("Presione Ctrl+C para detener.")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nDeteniendo dashboard.")
    finally:
        server.server_close()
        service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

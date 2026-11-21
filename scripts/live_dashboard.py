#!/usr/bin/env python3
"""Run the TradingLab read-only MT5 dashboard on localhost."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import warnings
from collections.abc import Mapping
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


def utc_offset_minutes(value: str) -> int:
    parsed = int(value)
    if not -14 * 60 <= parsed <= 14 * 60:
        raise argparse.ArgumentTypeError("El offset UTC del broker debe estar entre -840 y 840")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true", help="Datos sintéticos sin conectar MT5.")
    mode.add_argument("--central-api-port", type=port, help="Puerto de la API central loopback.")
    parser.add_argument("--snapshot-source", help="SourceId del collector de estado.")
    parser.add_argument("--activity-source", help="SourceId del collector de actividad.")
    parser.add_argument(
        "--secrets-file", type=Path, help="Credenciales privadas de lectura central."
    )
    parser.add_argument(
        "--dashboard-secrets-file", type=Path, help="Credencial privada del dashboard."
    )
    parser.add_argument("--interval", type=interval, default=5.0)
    parser.add_argument("--port", type=port, default=8765)
    parser.add_argument("--broker-utc-offset-minutes", type=utc_offset_minutes)
    parser.add_argument("--snapshot-max-age", type=interval, default=30.0)
    parser.add_argument("--capture-interval", type=interval, default=20.0)
    args = parser.parse_args(argv)
    args.telemetry = args.central_api_port is not None
    if args.telemetry:
        if not args.snapshot_source or not args.activity_source:
            parser.error("La API central requiere --snapshot-source y --activity-source")
        if args.port == args.central_api_port:
            parser.error("Dashboard y API requieren puertos distintos")
    elif args.snapshot_source or args.activity_source or args.secrets_file:
        parser.error("Las fuentes y credenciales centrales requieren --central-api-port")
    return args


def main(argv: list[str] | None = None, *, environment: Mapping[str, str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from tradinglab.dashboard.auth import DASHBOARD_TOKEN_ENV, validate_dashboard_token
    from tradinglab.dashboard.service import LiveDashboardService
    from tradinglab.dashboard.snapshot import DemoSnapshotSource
    from tradinglab.dashboard.telemetry import (
        LoopbackTelemetryClient,
        TelemetrySnapshotSource,
    )
    from tradinglab.dashboard.telemetry_v2 import (
        LoopbackV2HistoryClient,
        V2HistoryProvider,
    )
    from tradinglab.dashboard.web import create_server
    from tradinglab.telemetry.local_secrets import load_local_secrets

    args = parse_args(argv)
    values = dict(os.environ if environment is None else environment)
    try:
        if args.secrets_file is not None:
            values = load_local_secrets(
                args.secrets_file,
                allowed_names=(
                    "CENTRAL_SNAPSHOT_INGEST",
                    "CENTRAL_ACCOUNT_READ",
                    "CENTRAL_LIVE_INGEST",
                    "CENTRAL_ACTIVITY_INGEST",
                    "CENTRAL_TRADING_READ",
                ),
                environment=values,
            )
        if args.dashboard_secrets_file is not None:
            values = load_local_secrets(
                args.dashboard_secrets_file,
                allowed_names=(DASHBOARD_TOKEN_ENV,),
                environment=values,
            )
    except ValueError, OSError:
        print(
            "Error: revise los archivos privados de configuración del dashboard.", file=sys.stderr
        )
        return 2
    history_provider = None
    position_cycle_provider = None
    historical_order_provider = None
    access = values.get(DASHBOARD_TOKEN_ENV, "")
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
        assert args.snapshot_source is not None
        read1_name = "CENTRAL_ACCOUNT_READ"
        ingest = values.get(read1_name, "")
        if len(ingest) < 24:
            print(
                f"Error: configure {read1_name} con la credencial de lectura del backend.",
                file=sys.stderr,
            )
            return 2
        if ingest == access:
            print(
                "Error: los tokens de telemetría y dashboard deben ser distintos.", file=sys.stderr
            )
            return 2
        if args.port == args.central_api_port:
            print("Error: dashboard y receptor deben usar puertos diferentes.", file=sys.stderr)
            return 2
        try:
            source = TelemetrySnapshotSource(
                LoopbackTelemetryClient(
                    token=ingest,
                    source_id=args.snapshot_source,
                    port=args.central_api_port,
                    central_api=True,
                ),
                source_id=args.snapshot_source,
                max_age=timedelta(seconds=args.snapshot_max_age),
            )
            history_provider = source
            if args.telemetry:
                read2_name = "CENTRAL_TRADING_READ"
                read_authorization = values.get(read2_name, "")
                if read_authorization in {access, ingest}:
                    raise ValueError(
                        "La credencial de lectura de trading debe ser distinta de dashboard y lectura de cuenta"
                    )
                assert args.activity_source is not None
                history_provider = V2HistoryProvider(
                    LoopbackV2HistoryClient(
                        read_authorization=read_authorization,
                        activity_source_id=args.activity_source,
                        port=args.central_api_port,
                    )
                )
                position_cycle_provider = history_provider
                historical_order_provider = history_provider
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
    else:  # pragma: no cover - argparse requires one of the two modes
        raise AssertionError("modo de dashboard no resuelto")

    service = LiveDashboardService(
        source,
        interval_seconds=args.interval,
        capture_interval_seconds=args.capture_interval if args.telemetry else args.interval,
        health_provider=source if isinstance(source, TelemetrySnapshotSource) else None,
    )
    server = create_server(
        service,
        port=args.port,
        dashboard_token=access,
        history_provider=history_provider,
        position_cycle_provider=position_cycle_provider,
        historical_order_provider=historical_order_provider,
        account_history_provider=source if isinstance(source, TelemetrySnapshotSource) else None,
        broker_utc_offset_minutes=args.broker_utc_offset_minutes,
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

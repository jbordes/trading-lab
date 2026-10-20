#!/usr/bin/env python3
"""Start and supervise the local MT5 receiver and dashboard together."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.runtime import RuntimeConfig, run_runtime

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True, help="SourceId configurado en el EA")
    parser.add_argument("--receiver-port", type=int, default=8776)
    parser.add_argument("--dashboard-port", type=int, default=8775)
    parser.add_argument("--dry-run", action="store_true", help="Mostrar plan sin abrir servicios")
    args = parser.parse_args(argv)
    try:
        config = RuntimeConfig(args.source_id, args.receiver_port, args.dashboard_port)
        print(f"EA -> http://127.0.0.1:{config.receiver_port}/v1/telemetry")
        print(f"Fuente: {config.source_id}; dashboard: {config.dashboard_port}")
        if args.dry_run:
            return 0
        environment = dict(os.environ)
        if not environment.get("TRADINGLAB_TELEMETRY_TOKEN"):
            # Never fall back to visible stdin (e.g. redirected consoles).
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                environment["TRADINGLAB_TELEMETRY_TOKEN"] = getpass.getpass(
                    "Token del EA (oculto, solo en memoria): "
                )
        run_runtime(ROOT, config, environment)
    except KeyboardInterrupt:
        print("\nReceptor y dashboard detenidos. El EA puede seguir capturando en MT5.")
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError, EOFError, getpass.GetPassWarning:
        # Avoid exception text from external process creation or terminal handling.
        print(
            "No se pudo mantener el arranque. Compruebe token, puertos libres y mensajes "
            "de los servicios. No se ha modificado MT5.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Reject collector requests temporarily; never replace a production relay."""

from __future__ import annotations

import argparse
import sys
import threading
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.access_probe import create_access_probe

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=int, choices=(401, 403), required=True)
    parser.add_argument("--seconds", type=int, default=180)
    args = parser.parse_args(argv)
    if not 70 <= args.seconds <= 900:
        parser.error("--seconds debe estar entre 70 y 900")

    def report(path: str, status: int) -> None:
        print(f"{datetime.now(UTC).isoformat()} {path} -> HTTP {status}", flush=True)

    try:
        with ExitStack() as stack:
            # Acquire both ports before starting either listener. Never kill owners.
            servers = [
                stack.enter_context(create_access_probe(port, args.status, report=report))
                for port in (8776, 8777)
            ]
            threads = []
            try:
                for server in servers:
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    threads.append((server, thread))
                print(
                    f"PROBE HTTP {args.status}: 127.0.0.1:8776/8777; "
                    f"max {args.seconds}s. No guarda datos. Ctrl+C para terminar.",
                    flush=True,
                )
                threading.Event().wait(args.seconds)
            except KeyboardInterrupt:
                pass
            finally:
                for server, thread in threads:
                    server.shutdown()
                    thread.join()
    except OSError:
        print("No se pudo abrir la prueba; revise puertos y permisos. No se detuvo otro proceso.")
        return 1
    print("Prueba detenida. Reinicie el relay original con su misma cola y configuración.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Start the Juampi v1-live plus v2-history pilot as one supervised runtime."""

from __future__ import annotations

import getpass
import os
import secrets
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PROMPTS = {
    "TRADINGLAB_TELEMETRY_TOKEN": "Token del collector v1",
    "TRADINGLAB_DASHBOARD_TOKEN": "Token de acceso al dashboard",
    "TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN": "Token de TradingLabActivity v2",
}


def main() -> int:
    from tradinglab.telemetry.runtime_v2 import V2PilotRuntimeConfig, run_v2_pilot

    environment = dict(os.environ)
    try:
        for name, label in PROMPTS.items():
            if not environment.get(name):
                with warnings.catch_warnings():
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    environment[name] = getpass.getpass(f"{label} (oculto): ")
        environment.setdefault("TRADINGLAB_TELEMETRY_LIVE_TOKEN", secrets.token_urlsafe(32))
        environment.setdefault("TRADINGLAB_TELEMETRY_READ_TOKEN", secrets.token_urlsafe(32))
        config = V2PilotRuntimeConfig(
            live_source_id="juampi-demo-01",
            activity_source_id="juampi-demo-activity-v2",
            account_id="cuenta-demo-juampi",
            v1_database=ROOT / "_storage" / "piloto.sqlite3",
            v2_database=ROOT / "_storage" / "piloto-v2.sqlite3",
        )
        run_v2_pilot(ROOT, config, environment)
    except KeyboardInterrupt:
        print("\nPiloto detenido. Los EAs de MT5 no fueron modificados.")
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError, EOFError, getpass.GetPassWarning:
        print(
            "No se pudo mantener el piloto. Revise credenciales, bases y puertos.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

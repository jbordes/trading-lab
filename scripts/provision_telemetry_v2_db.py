#!/usr/bin/env python3
"""Preview or create an isolated SQLite database for telemetry v2 pilot sources."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.admission_v2 import ProducerIdentity
    from tradinglab.telemetry.provisioning_v2 import V2ProvisionPlan
    from tradinglab.telemetry.sqlite_store_v2 import V2StorageError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filename", required=True, help="Archivo nuevo bajo _storage/.")
    parser.add_argument("--account-id", required=True, help="Identidad interna sin login real.")
    parser.add_argument("--label", required=True, help="Alias descriptivo no sensible.")
    parser.add_argument("--login-masked", required=True, help="Login en formato ****1234.")
    parser.add_argument("--server", required=True, help="Servidor demo verificado en MT5.")
    parser.add_argument("--currency", required=True, help="Moneda de la cuenta.")
    parser.add_argument("--live-source-id", required=True, help="Fuente de estado vivo.")
    parser.add_argument("--activity-source-id", required=True, help="Fuente de actividad.")
    parser.add_argument("--apply", action="store_true", help="Crear la base y registrar fuentes.")
    args = parser.parse_args(argv)
    try:
        plan = V2ProvisionPlan(
            ROOT,
            args.filename,
            args.account_id,
            args.label,
            ProducerIdentity(args.login_masked, args.server, args.currency),
            args.live_source_id,
            args.activity_source_id,
        )
        if not args.apply:
            print("Vista previa: no se creará ningún archivo.")
            print(f"Base: {plan.database}")
            print(f"Cuenta interna: {plan.account_id}; login: {plan.identity.login_masked}")
            print(f"Estado vivo: {plan.live_source_id}; actividad: {plan.activity_source_id}")
            print(f"Servidor: {plan.identity.server}; moneda: {plan.identity.currency}")
            return 0
        database = plan.apply()
        print(f"Base v2 creada y verificada: {database}")
        print(f"Fuentes: live={plan.live_source_id}; activity={plan.activity_source_id}")
    except (ValueError, FileExistsError, RuntimeError, V2StorageError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

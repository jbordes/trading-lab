#!/usr/bin/env python3
"""Preview or create one local SQLite database for an operator-verified demo account."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.provisioning import ProvisionPlan

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filename", required=True, help="Archivo nuevo bajo _storage/.")
    parser.add_argument("--account-id", required=True, help="Identidad interna sin login real.")
    parser.add_argument("--label", required=True, help="Alias descriptivo no sensible.")
    parser.add_argument("--server", required=True, help="Servidor demo verificado en MT5.")
    parser.add_argument("--currency", required=True, help="Moneda de la cuenta.")
    parser.add_argument("--source-id", required=True, help="SourceId del collector de pruebas.")
    parser.add_argument("--apply", action="store_true", help="Crear la base y registrar la fuente.")
    args = parser.parse_args(argv)
    try:
        plan = ProvisionPlan(
            ROOT,
            args.filename,
            args.account_id,
            args.label,
            args.server,
            args.currency,
            args.source_id,
        )
        database = plan.database
        if not args.apply:
            print("Vista previa: no se creará ningún archivo.")
            print(f"Base: {database}")
            print(f"Cuenta interna: {plan.account_id}; fuente: {plan.source_id}")
            print(f"Servidor: {plan.server}; moneda: {plan.currency}")
            return 0
        plan.apply()
        print(f"Base creada: {database}")
        print(f"Fuente registrada: {plan.source_id}")
    except (ValueError, FileExistsError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

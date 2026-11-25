"""Explicit and atomic multicuenta v9 to v10 upgrade from the stored activity ledger."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from tradinglab.telemetry.central_schema import REMOTE_ACTIVITY_DDL, validate_central_schema
from tradinglab.telemetry.remote_positions import rebuild_positions


def upgrade(path: Path, *, apply: bool = False) -> tuple[int, int]:
    mode = "rw" if apply else "ro"
    uri = path.resolve(strict=True).as_uri() + "?mode=" + mode
    with closing(sqlite3.connect(uri, uri=True)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (9, 10):
            raise ValueError("Se requiere una base multicuenta")
        validate_central_schema(db, check_integrity=True)
        if apply and version == 9:
            for statement in REMOTE_ACTIVITY_DDL:
                db.execute(statement)
            for (account,) in db.execute("SELECT account_id FROM mt5_accounts"):
                positions = db.execute(
                    """SELECT DISTINCT json_extract(row_json,'$.position_id') AS position
                       FROM activity_observations WHERE account_id=? AND entity_type='deal'
                       AND position!='0'""",
                    (account,),
                )
                rebuild_positions(db, account, (p for (p,) in positions))
            db.execute("PRAGMA user_version=10")
            validate_central_schema(db, check_integrity=True)
        return version, 10


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    before, target = upgrade(args.database, apply=args.apply)
    print(f"Esquema {before} -> {target}. " + ("Aplicado." if args.apply else "Vista previa."))

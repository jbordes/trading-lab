"""Incremental central projection of closed positions from acknowledged activity windows."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from decimal import Decimal

from tradinglab.metrics.trade_details import trade_details
from tradinglab.telemetry.cycle_evidence import cycle_document, position_cycle


def refresh_remote_positions(db: sqlite3.Connection, account: str, payload: dict) -> None:
    positions = set()
    for entity in ("deal", "order"):
        items = payload[entity + "s"]["items"]
        if items:
            # Include former assignments if the broker corrects a ticket.
            positions.update(
                position
                for pair in db.execute(
                    """SELECT DISTINCT json_extract(row_json,'$.position_id'),
                                      json_extract(row_json,'$.position_by_id')
                       FROM activity_observations
                       WHERE account_id=? AND entity_type=?
                         AND ticket IN (SELECT value FROM json_each(?))""",
                    (account, entity, json.dumps([row["ticket"] for row in items])),
                )
                for position in pair
                if position and position != "0"
            )
    window = payload["window"]
    positions.update(
        row[0]
        for row in db.execute(
            """SELECT position_id FROM pending_position_coverage
               WHERE account_id=? AND from_msc<=? AND to_msc>=?""",
            (account, int(window["to_server_msc"]), int(window["from_server_msc"])),
        )
    )
    rebuild_positions(db, account, positions)


def _covered(db: sqlite3.Connection, account: str, entity: str, start: int, end: int) -> bool:
    next_time = start
    for left, right in db.execute(
        """SELECT from_server_msc, to_server_msc FROM activity_coverage
           WHERE account_id=? AND entity_type=? AND status='complete'
             AND from_server_msc<=? AND to_server_msc>=?
           ORDER BY from_server_msc, to_server_msc DESC""",
        (account, entity, end, start),
    ):
        if left > next_time:
            break
        next_time = max(next_time, right + 1)
        if next_time > end:
            return True
    return False


def rebuild_positions(db: sqlite3.Connection, account: str, positions: Iterable[str]) -> None:
    cutoff = db.execute(
        "SELECT history_from * 1000 FROM mt5_accounts WHERE account_id=?", (account,)
    ).fetchone()[0]
    for position in positions:
        db.execute(
            "DELETE FROM remote_position_cycles WHERE account_id=? AND position_id=?",
            (account, position),
        )
        db.execute(
            "DELETE FROM pending_position_coverage WHERE account_id=? AND position_id=?",
            (account, position),
        )
        _rebuild(db, account, position, cutoff)


def _rebuild(db: sqlite3.Connection, account: str, position: str, cutoff: int) -> None:
    # Resolve latest evidence across sessions before applying the position filter.
    observations = db.execute(
        """WITH tickets AS (
               SELECT entity_type, ticket FROM activity_observations
               WHERE account_id=? AND json_extract(row_json,'$.position_id')=?
               UNION
               SELECT entity_type, ticket FROM activity_observations
               WHERE account_id=? AND json_extract(row_json,'$.position_by_id')=?
           ), ranked AS (
               SELECT o.*, ROW_NUMBER() OVER (
                   PARTITION BY o.entity_type,o.ticket,o.session_id,o.captured_at_utc
                   ORDER BY length(o.sequence) DESC,o.sequence DESC,o.message_id DESC
               ) AS session_rank, DENSE_RANK() OVER (
                   PARTITION BY o.entity_type,o.ticket ORDER BY o.captured_at_utc DESC
               ) AS capture_rank
               FROM tickets t CROSS JOIN activity_observations o USING(entity_type,ticket)
               WHERE o.account_id=?
           )
           SELECT entity_type,ticket,row_json,message_id,source_id,captured_at_utc
           FROM ranked WHERE session_rank=1 AND capture_rank=1 ORDER BY captured_at_utc, message_id""",
        (account, position, account, position, account),
    )
    latest = {}
    witness = None
    for entity, ticket, encoded, message, source, captured in observations:
        key = (entity, ticket)
        if key in latest and latest[key] != encoded:
            return
        latest[key] = encoded
        witness = (message, source, captured)
    deals, orders = [], []
    for (entity, _), encoded in latest.items():
        row = json.loads(encoded)
        if position not in (row["position_id"], row.get("position_by_id")):
            continue
        (deals if entity == "deal" else orders).append(row)
    opening = next((row for row in orders if row["ticket"] == position), None)
    if (
        not opening
        or not deals
        or any(d["deal_type"] not in (0, 1) or d["volume"] <= 0 for d in deals)
    ):
        return
    deals.sort(key=lambda row: (int(row["time_msc"]), int(row["ticket"])))
    first = deals[0]
    start, end = int(first["time_msc"]), int(deals[-1]["time_msc"])
    if start < cutoff or first["order_id"] != position or first["entry"] != 0:
        return
    # A pending order can predate the cutoff. Prove all fills of its opening order
    # are present before classifying its first observed fill as the first actual fill.
    filled = Decimal(str(opening["volume_initial"])) - Decimal(str(opening["volume_current"]))
    observed = sum(Decimal(str(d["volume"])) for d in deals if d["order_id"] == position)
    if filled != observed:
        return
    cycle = position_cycle(account, deals)
    if cycle.lifecycle.value != "closed":
        return
    cover_start = max(cutoff, min(start, int(opening["setup_time_msc"])))
    cover_end = max(end, *(int(o["done_time_msc"]) for o in orders))
    if not all(
        _covered(db, account, entity, cover_start, cover_end) for entity in ("deal", "order")
    ):
        db.execute(
            "INSERT INTO pending_position_coverage VALUES (?,?,?,?)",
            (account, position, cover_start, cover_end),
        )
        return
    details = trade_details(cycle, {"deals": {"items": deals}, "orders": {"items": orders}})
    db.execute(
        "INSERT INTO remote_position_cycles VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            account,
            position,
            *witness,
            cycle.owner_magic,
            start,
            end,
            json.dumps(cycle_document(cycle)),
            json.dumps(details),
        ),
    )

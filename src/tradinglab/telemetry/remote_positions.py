"""Incremental central projection of closed positions from acknowledged activity windows."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from tradinglab.metrics.trade_details import trade_details
from tradinglab.telemetry.activity_coverage import resolved_coverage
from tradinglab.telemetry.cycle_evidence import cycle_document, position_cycle


def refresh_remote_positions(
    db: sqlite3.Connection,
    account: str,
    payload: dict,
    changes: list[tuple[int, int]],
    message_id: int,
    source_id: str,
    captured: str,
) -> None:
    positions = set()
    repeated = set()
    for entity in ("deal", "order"):
        items = payload[entity + "s"]["items"]
        if not items:
            continue
        # Inspect prior evidence in bulk. Any earlier reassignment or conflicting
        # version takes the full path, even if the incoming content matches one row.
        stable_tickets = {
            row[0]
            for row in db.execute(
                """SELECT n.ticket FROM activity_observations n
                   JOIN activity_observations old ON old.account_id=n.account_id
                     AND old.entity_type=n.entity_type AND old.ticket=n.ticket
                     AND old.message_id!=n.message_id
                   WHERE n.message_id=? AND n.entity_type=?
                   GROUP BY n.ticket
                   HAVING max(old.captured_at_utc)<min(n.captured_at_utc)
                      AND min(old.row_json=n.row_json)=1""",
                (message_id, entity),
            )
        }
        dirty_tickets = []
        for item in items:
            if item["ticket"] in stable_tickets:
                repeated.update(
                    p for p in (item["position_id"], item.get("position_by_id")) if p and p != "0"
                )
            else:
                dirty_tickets.append(item["ticket"])
        if dirty_tickets:
            # Include former assignments if the broker corrects a ticket.
            positions.update(
                position
                for pair in db.execute(
                    """SELECT DISTINCT json_extract(row_json,'$.position_id'),
                                      json_extract(row_json,'$.position_by_id')
                       FROM activity_observations
                       WHERE account_id=? AND entity_type=?
                         AND ticket IN (SELECT value FROM json_each(?))""",
                    (account, entity, json.dumps(dirty_tickets)),
                )
                for position in pair
                if position and position != "0"
            )
    if changes:
        positions.update(
            row[0]
            for row in db.execute(
                """SELECT position_id FROM pending_position_coverage p
                   WHERE account_id=? AND EXISTS (
                       SELECT 1 FROM json_each(?) r
                       WHERE p.from_msc<=json_extract(r.value,'$[1]')
                         AND p.to_msc>=json_extract(r.value,'$[0]'))""",
                (account, json.dumps(changes)),
            )
        )
    for position in repeated - positions:
        # Preserve the same latest witness selected by the full rebuild.
        existing = db.execute(
            """SELECT c.captured_at_utc,c.message_id FROM remote_position_cycles c
               JOIN pending_position_coverage d USING(account_id,position_id)
               WHERE c.account_id=? AND c.position_id=?""",
            (account, position),
        ).fetchone()
        if existing is None:
            positions.add(position)
        elif (captured, message_id) > existing:
            db.execute(
                """UPDATE remote_position_cycles SET captured_at_utc=?,message_id=?,source_id=?
                   WHERE account_id=? AND position_id=?""",
                (captured, message_id, source_id, account, position),
            )
    if positions:
        rebuild_positions(db, account, positions)


def _covered(db: sqlite3.Connection, account: str, entity: str, start: int, end: int) -> bool:
    ranges, _ = resolved_coverage(db, account, entity, start, end)
    return ranges == [[start, end]]


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
    # Retain dependencies for completed cycles too: a later revision can revoke coverage.
    db.execute(
        "INSERT INTO pending_position_coverage VALUES (?,?,?,?)",
        (account, position, cover_start, cover_end),
    )
    if not all(
        _covered(db, account, entity, cover_start, cover_end) for entity in ("deal", "order")
    ):
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


def previously_ambiguous_windows(database: Path, account: str) -> str:
    """Snapshot historical page ties once per account; new messages are handled at admission."""
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        rows = db.execute(
            """SELECT from_server_msc,to_server_msc FROM activity_coverage WHERE account_id=?
               GROUP BY entity_type,from_server_msc,to_server_msc,captured_at_utc
               HAVING count(*)>1 AND (count(DISTINCT session_id)>1 OR count(DISTINCT source_id)>1)
                 AND max(json_extract(collection_json,'$.status')='paged_complete')=1
               ORDER BY from_server_msc,to_server_msc""",
            (account,),
        )
        ranges: list[list[int]] = []
        for lo, hi in rows:
            if ranges and lo <= ranges[-1][1] + 1:
                ranges[-1][1] = max(hi, ranges[-1][1])
            else:
                ranges.append([lo, hi])
        return json.dumps(ranges)


def reconciliation_candidates(
    db: sqlite3.Connection, account: str, after: str, ambiguous: str
) -> list[str]:
    rows = db.execute(
        """SELECT c.position_id FROM remote_position_cycles c
           WHERE c.account_id=? AND c.position_id>? AND NOT EXISTS (
               SELECT 1 FROM pending_position_coverage p
               WHERE p.account_id=c.account_id AND p.position_id=c.position_id)
           UNION ALL
           SELECT p.position_id FROM pending_position_coverage p
           LEFT JOIN remote_position_cycles c USING(account_id,position_id)
           WHERE p.account_id=? AND p.position_id>? AND (c.position_id IS NULL OR EXISTS (
               SELECT 1 FROM json_each(?) WHERE json_extract(value,'$[0]')<=p.to_msc
                 AND json_extract(value,'$[1]')>=p.from_msc))
           ORDER BY 1 LIMIT 100""",
        (account, after, account, after, ambiguous),
    )
    return [row[0] for row in rows]


def reconcile_cycle_batch(database: Path, account: str, after: str, ambiguous: str) -> str | None:
    with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=1)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        positions = reconciliation_candidates(db, account, after, ambiguous)
        if not positions:
            return None
        db.execute("BEGIN IMMEDIATE")
        rebuild_positions(db, account, positions)
        return positions[-1]

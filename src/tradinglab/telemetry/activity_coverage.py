"""Resolve inclusive MT5 history windows for reports and position projections."""

import json
import sqlite3
from itertools import groupby


def _window_rows(db: sqlite3.Connection, message: int, entity: str) -> set[tuple[str, str]] | None:
    """Compare complete observations only when competing sessions report the same window."""
    source, session, encoded = db.execute(
        "SELECT source_id,session_id,payload_json FROM telemetry_v2_messages WHERE message_id=?",
        (message,),
    ).fetchone()
    payload = json.loads(encoded)["payload"]
    ids = [message]
    page = payload.get("pagination")
    if page:
        # Trace an admitted chain ending at this specific final page. Different page
        # sizes can have different boundaries while representing identical tickets.
        window = payload["window"]
        rows = db.execute(
            """SELECT message_id,session_id,json_extract(payload_json,'$.payload.pagination')
               FROM telemetry_v2_messages WHERE source_id=? AND message_id<?
               AND kind='activity_batch'
               AND json_extract(payload_json,'$.payload.window.from_server_msc')=?
               AND json_extract(payload_json,'$.payload.window.to_server_msc')=?
               AND json_extract(payload_json,'$.payload.pagination.snapshot_id')=?
               AND json_extract(payload_json,'$.payload.deals.total')=?
               AND json_extract(payload_json,'$.payload.orders.total')=? ORDER BY message_id DESC""",
            (
                source,
                message,
                window["from_server_msc"],
                window["to_server_msc"],
                page["snapshot_id"],
                payload["deals"]["total"],
                payload["orders"]["total"],
            ),
        )

        def key(bound: dict) -> tuple:
            return bound["time_msc"], bound["entity_type"], bound["ticket"]

        target = key(page["after"])
        origin = ("0", "deal", "0")
        edges = {}
        for page_id, owner, raw in rows:
            link = json.loads(raw)
            if link["has_more"]:
                edges.setdefault(key(link["after"]), []).append(
                    (key(link["through"]), page_id, owner)
                )

        # A resumed page can refer to a durable prefix from a previous session.
        # Prefer the producer session's own chain when comparing two terminals.
        for same_session_only in (True, False):
            parents = {origin: None}
            frontier = [origin]
            while frontier and target not in parents:
                current = frontier.pop()
                for end, page_id, owner in edges.get(current, ()):
                    if same_session_only and owner != session:
                        continue
                    if end not in parents:
                        parents[end] = (current, page_id)
                        frontier.append(end)
            if target in parents:
                break
        else:
            return None
        while target != origin:
            target, page_id = parents[target]
            ids.append(page_id)

    records = set(
        db.execute(
            """SELECT ticket,row_json FROM activity_observations WHERE entity_type=?
           AND message_id IN (SELECT value FROM json_each(?))""",
            (entity, json.dumps(ids)),
        )
    )
    total = payload[entity + "s"]["total"]
    if len(records) != total or len({ticket for ticket, _ in records}) != total:
        return None
    return records


def resolved_coverage(
    db: sqlite3.Connection,
    account: str,
    entity: str,
    start: int,
    end: int,
    *,
    exclude_start_at_end: bool = False,
) -> tuple[list[list[int]], int]:
    rows = db.execute(
        """WITH ranked AS (
            SELECT from_server_msc AS lo, to_server_msc AS hi, status, reported_total, message_id,
                dense_rank() OVER (PARTITION BY from_server_msc,to_server_msc
                    ORDER BY captured_at_utc DESC) AS revision,
                row_number() OVER (PARTITION BY from_server_msc,to_server_msc,
                    captured_at_utc,source_id,session_id
                    ORDER BY length(sequence) DESC, sequence DESC,message_id DESC) AS priority
            FROM activity_coverage WHERE account_id=? AND entity_type=?
              AND to_server_msc>=? AND from_server_msc<=?
        )
        SELECT lo,hi,status,reported_total,message_id
        FROM ranked WHERE revision=1 AND priority=1 ORDER BY lo,hi""",
        (account, entity, start, end - int(exclude_start_at_end)),
    )
    ranges: list[list[int]] = []
    incomplete = 0
    for (lo, hi), group in groupby(rows, key=lambda row: (row[0], row[1])):
        observations = list(group)
        witnesses = [row for row in observations if row[2] == "complete"]
        if len(witnesses) < len(observations):
            incomplete += 1
        if not witnesses:
            continue
        if len(witnesses) > 1:
            first = witnesses[0]
            reference = _window_rows(db, first[4], entity)
            if reference is None or any(
                row[3] != first[3] or _window_rows(db, row[4], entity) != reference
                for row in witnesses[1:]
            ):
                incomplete += 1
                continue
        lo, hi = max(start, lo), min(end, hi)
        if ranges and lo <= ranges[-1][1] + 1:
            ranges[-1][1] = max(ranges[-1][1], hi)
        else:
            ranges.append([lo, hi])
    return ranges, incomplete


def changed_intervals(before: list[list[int]], after: list[list[int]]) -> list[tuple[int, int]]:
    """Inclusive intervals where exactly one union supplies coverage."""
    boundaries: set[int] = set()
    for ranges in (before, after):
        for lo, hi in ranges:
            boundaries.symmetric_difference_update((lo, hi + 1))
    edges = iter(sorted(boundaries))
    return [(lo, stop - 1) for lo, stop in zip(edges, edges, strict=True)]

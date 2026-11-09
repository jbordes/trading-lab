"""Bounded read-only adapter for account ledger and observed balance anchors."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from tradinglab.telemetry.account_progression import (
    BalanceAnchor,
    LedgerMovement,
    progression_bucket_msc,
    project_account_progression,
)
from tradinglab.telemetry.contract import IDENTIFIER, parse_envelope
from tradinglab.telemetry.sqlite_store_v2 import V2StorageError, open_v2_history_reader


def _anchor(
    database: Path, source_id: str, account_id: str, earliest: int, deadline: float
) -> BalanceAnchor | None:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.1)) as db:
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        if (
            db.execute(
                "SELECT 1 FROM sources WHERE source_id=? AND account_id=? AND role='snapshot'",
                (source_id, account_id),
            ).fetchone()
            is None
        ):
            raise V2StorageError("La fuente no corresponde a la cuenta solicitada")
        frontier = db.execute(
            "SELECT MAX(to_server_msc) FROM activity_coverage "
            "WHERE account_id=? AND entity_type='deal' AND status='complete'",
            (account_id,),
        ).fetchone()[0]
        if frontier is None:
            return None
        rows = db.execute(
            "SELECT m.payload_json, m.content_sha256 FROM telemetry_messages m "
            "JOIN sources s ON s.source_id=m.source_id "
            "WHERE m.source_id=? AND s.account_id=? AND s.role='snapshot' "
            "AND m.compacted_broker_day IS NULL "
            "ORDER BY m.captured_at_utc DESC, m.message_id DESC LIMIT 64",
            (source_id, account_id),
        )
        for body, digest in rows:
            if time.monotonic() >= deadline:
                raise V2StorageError("La consulta superó el plazo seguro")
            raw = body.encode("utf-8")
            if hashlib.sha256(raw).hexdigest() != digest:
                raise V2StorageError("La referencia no coincide con su hash")
            message = parse_envelope(raw)
            if message.source_id != source_id:
                raise V2StorageError("Referencia de cuenta inválida")
            if message.kind != "account_snapshot" or "server_time_msc" not in message.payload:
                continue
            server_msc = int(message.payload["server_time_msc"])
            if earliest <= server_msc and server_msc + 1000 <= frontier:
                return BalanceAnchor(
                    server_msc, Decimal(str(message.payload["account"]["balance"]))
                )
    return None


def read_account_progression(
    database: Path, source_id: str, account_id: str, *, from_msc: int, to_msc: int
) -> dict[str, object]:
    """Resolve one account's tickets once; no cache, migration or durable writes."""
    if any(not isinstance(x, str) or not IDENTIFIER.fullmatch(x) for x in (source_id, account_id)):
        raise ValueError("Identidad de cuenta inválida")
    # Validate range before opening storage or allocating buckets.
    progression_bucket_msc(from_msc, to_msc)
    deadline = time.monotonic() + 3.0
    try:
        anchor = _anchor(database, source_id, account_id, from_msc, deadline)
        if anchor is not None and anchor.server_msc + 1000 - from_msc > 366 * 86_400_000:
            anchor = None
        scan_end = max(to_msc, anchor.server_msc + 1000 if anchor is not None else to_msc)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise V2StorageError("La consulta superó el plazo seguro")
        with open_v2_history_reader(database, timeout_seconds=remaining) as registry:
            coverage = registry.coverage_report(
                account_id, "deal", from_msc=from_msc, to_msc=scan_end
            )
            conflicts = False

            def movements() -> Iterator[LedgerMovement]:
                nonlocal conflicts
                cursor = None
                for _ in range(1000):
                    if time.monotonic() >= deadline:
                        raise V2StorageError("La consulta superó el plazo seguro")
                    page = registry.activity_page(
                        account_id,
                        "deal",
                        from_msc=from_msc,
                        to_msc=scan_end,
                        limit=100,
                        cursor=cursor,
                    )
                    for item in page.items:
                        conflicts |= item.conflict_at is not None
                        row = item.values
                        yield LedgerMovement(
                            int(row["time_msc"]),
                            int(row["deal_type"]),
                            *(
                                Decimal(str(row[key]))
                                for key in ("profit", "commission", "swap", "fee")
                            ),
                        )
                    cursor = page.next_cursor
                    if cursor is None:
                        return
                raise V2StorageError("El historial excede el límite seguro de esta consulta")

            # Consume conflicts alongside bounded aggregation, then suppress uncertain results.
            result = project_account_progression(
                movements(),
                from_msc=from_msc,
                to_msc=to_msc,
                complete_ranges=tuple((int(a), int(b)) for a, b in coverage.complete_ranges),
                anchor=anchor,
            )
            if conflicts:
                result["status"] = "partial"
                result["balance_status"] = "incomplete_ledger"
                result["anchor_server_msc"] = None
                for point in result["points"]:
                    for field in ("balance", "realized_pnl", "net_cash_flow", "adjustments"):
                        point[field] = None
        return {"account_id": account_id, "source_id": source_id, **result}
    except (sqlite3.Error, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        raise V2StorageError("No se pudo consultar la progresión de cuenta") from exc

"""Opt-in v2 wire validation; deliberately not wired into the v1 receiver.

Reuse v1's scalar and live-row rules without widening its accepted schemas.
Authorization, replay handling and projections belong to later boundaries.
"""

from __future__ import annotations

import json
import math
from typing import Any

from tradinglab.telemetry import contract as v1
from tradinglab.telemetry.contract import TelemetryEnvelope, TelemetryValidationError

SCHEMA_VERSION = "mt5-telemetry-v2"
IDENTITY_FIELDS = {"login_masked", "server", "currency"}
HISTORY_ORDER_FIELDS = {
    "ticket",
    "magic_number",
    "symbol",
    "order_type",
    "state",
    "volume_initial",
    "volume_current",
    "price_open",
    "stop_loss",
    "take_profit",
    "setup_time_msc",
    "done_time_msc",
    "position_id",
    "position_by_id",
    "comment",
}


def parse_envelope_v2(body: bytes) -> TelemetryEnvelope:
    """Validate one v2 message without I/O, authorization or state changes."""
    if not body or len(body) > v1.MAX_BODY_BYTES:
        raise TelemetryValidationError("Cuerpo vacío o demasiado grande")
    try:
        document = json.loads(body.decode("utf-8"), object_pairs_hook=v1._unique_object)
    except (ValueError, RecursionError) as exc:
        raise TelemetryValidationError("El cuerpo no es JSON UTF-8 válido") from exc
    document = _object(document, "mensaje")
    v1._validate_json_value(document, "mensaje", depth=-1)
    v1._require_exact_fields(
        document,
        {
            "schema_version",
            "collector_version",
            "source_id",
            "session_id",
            "sequence",
            "event_id",
            "captured_at",
            "kind",
            "payload",
        },
        "mensaje",
    )
    if document["schema_version"] != SCHEMA_VERSION:
        raise TelemetryValidationError("Schema v2 no admitido")
    for field in ("collector_version", "source_id", "session_id", "event_id"):
        v1._identifier(document, field)
    v1._integer_range(document["sequence"], "sequence", minimum=1, maximum=v1.MAX_INT64)
    if document["event_id"] != f"{document['session_id']}:{document['sequence']}":
        raise TelemetryValidationError("event_id no corresponde a sesión y secuencia")
    captured_at = v1._utc_timestamp(document["captured_at"])
    kind = v1._required_string(document, "kind")
    payload = _object(document["payload"], "payload")
    validators = {
        "live_snapshot": _live,
        "activity_batch": _activity,
        "heartbeat": _heartbeat,
    }
    if kind not in validators:
        raise TelemetryValidationError("Tipo de mensaje v2 no admitido")
    validators[kind](payload)
    return TelemetryEnvelope(**(document | {"captured_at": captured_at}))


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TelemetryValidationError(f"{label} debe ser un objeto")
    return value


def _identity(value: Any) -> dict[str, Any]:
    identity = _object(value, "identity")
    v1._require_exact_fields(identity, IDENTITY_FIELDS, "identity")
    if not v1.MASKED_ACCOUNT.fullmatch(v1._required_string(identity, "login_masked")):
        raise TelemetryValidationError("login_masked no está enmascarado")
    v1._bounded_string(identity, "server", maximum=128)
    v1._bounded_string(identity, "currency", maximum=16)
    return identity


def _live(payload: dict[str, Any]) -> None:
    v1._require_exact_fields(
        payload,
        {
            "reason",
            "identity",
            "account",
            "positions_total",
            "orders_total",
            "positions",
            "orders",
        },
        "live_snapshot",
    )
    identity = _identity(payload["identity"])
    account = _object(payload["account"], "account")
    v1._require_exact_fields(account, v1.ACCOUNT_FIELDS - IDENTITY_FIELDS, "account")
    # Reuse exactly the existing account/row/count semantics, without history.
    normalized = {key: value for key, value in payload.items() if key != "identity"}
    normalized["account"] = account | identity
    v1._validate_account_snapshot(normalized)


def _heartbeat(payload: dict[str, Any]) -> None:
    base_fields = {
        "identity",
        "status",
        "queued_messages",
        "dropped_messages",
    }
    expected_fields = base_fields | (
        {"activity_progress"} if "activity_progress" in payload else set()
    )
    v1._require_exact_fields(
        payload,
        expected_fields,
        "heartbeat",
    )
    _identity(payload["identity"])
    if v1._required_string(payload, "status") not in {"ok", "degraded"}:
        raise TelemetryValidationError("Estado de heartbeat inválido")
    for field in ("queued_messages", "dropped_messages"):
        v1._integer_range(payload[field], field, minimum=0, maximum=v1.MAX_INT64)
    if "activity_progress" in payload:
        _activity_progress(payload["activity_progress"])


def _activity_progress(value: Any) -> None:
    progress = _object(value, "activity_progress")
    expected_fields = {
        "recent_cursor_msc",
        "deep_cursor_msc",
        "backlog_msc",
        "recent_blocked",
        "deep_blocked",
        "queued_hints",
        "dropped_hints",
        "last_transaction_age_ms",
        "latest_deal_ticket",
        "latest_order_ticket",
        "latest_position_id",
    }
    if "deep_paused" in progress:
        expected_fields.add("deep_paused")
    v1._require_exact_fields(
        progress,
        expected_fields,
        "activity_progress",
    )
    for field in (
        "recent_cursor_msc",
        "deep_cursor_msc",
        "backlog_msc",
        "last_transaction_age_ms",
        "latest_deal_ticket",
        "latest_order_ticket",
        "latest_position_id",
    ):
        v1._decimal_text(progress, field, minimum=0, maximum=v1.MAX_INT64)
    for field in ("recent_blocked", "deep_blocked", "deep_paused"):
        if field not in progress:
            continue
        if not isinstance(progress[field], bool):
            raise TelemetryValidationError(f"{field} debe ser booleano")
    for field in ("queued_hints", "dropped_hints"):
        v1._integer_range(progress[field], field, minimum=0, maximum=v1.MAX_INT64)


def _activity(payload: dict[str, Any]) -> None:
    expected_fields = {
        "reason",
        "identity",
        "window",
        "deals",
        "orders",
    }
    paginated = "pagination" in payload
    if paginated:
        expected_fields.add("pagination")
    v1._require_exact_fields(
        payload,
        expected_fields,
        "activity_batch",
    )
    _identity(payload["identity"])
    reason = v1._required_string(payload, "reason")
    if reason not in {
        "startup",
        "trade_activity",
        "reconcile",
        "recovery",
        "position_reconcile",
    }:
        raise TelemetryValidationError("Motivo de actividad inválido")
    window = _object(payload["window"], "window")
    v1._require_exact_fields(window, {"from_server_msc", "to_server_msc"}, "window")
    for field in ("from_server_msc", "to_server_msc"):
        v1._decimal_text(window, field, minimum=0, maximum=v1.MAX_INT64)
    start, end = int(window["from_server_msc"]), int(window["to_server_msc"])
    duration = end - start
    if duration < 0 or (reason != "position_reconcile" and duration > 86_400_000):
        raise TelemetryValidationError("Ventana de actividad inválida")
    collections: dict[str, list[dict[str, Any]]] = {}
    for name in ("deals", "orders"):
        rows = _collection(payload[name], paginated=paginated)
        collections[name] = rows
        seen: set[str] = set()
        for item in rows:
            row = _object(item, name)
            if name == "deals":
                _deal(row)
                timestamp = int(row["time_msc"])
            else:
                _order(row)
                timestamp = int(row["done_time_msc"])
            if not start <= timestamp <= end:
                raise TelemetryValidationError("Registro fuera de la ventana")
            if row["ticket"] in seen:
                raise TelemetryValidationError("Ticket duplicado dentro de la colección")
            seen.add(row["ticket"])
    if paginated:
        _pagination(payload["pagination"], payload, collections)
    if reason == "position_reconcile":
        if paginated:
            raise TelemetryValidationError("Reconciliación de posición no admite paginación")
        _position_reconcile(payload, collections)


def _position_reconcile(
    payload: dict[str, Any], collections: dict[str, list[dict[str, Any]]]
) -> None:
    for name in ("deals", "orders"):
        collection = payload[name]
        if collection["status"] != "complete" or collection["total"] != len(collections[name]):
            raise TelemetryValidationError("Reconciliación de posición incompleta")
    deals = collections["deals"]
    if not deals:
        raise TelemetryValidationError("Reconciliación de posición sin deals")
    position_id = deals[0]["position_id"]
    if position_id == "0" or any(row["position_id"] != position_id for row in deals):
        raise TelemetryValidationError("Deals de reconciliación pertenecen a otra posición")
    if any(row["deal_type"] not in {0, 1} for row in deals):
        raise TelemetryValidationError("Reconciliación de posición contiene deals no comerciales")
    signed_volume = math.fsum(
        row["volume"] if row["deal_type"] == 0 else -row["volume"] for row in deals
    )
    if not math.isclose(signed_volume, 0.0, rel_tol=0.0, abs_tol=1e-8):
        raise TelemetryValidationError("Reconciliación de posición todavía abierta")
    orders = collections["orders"]
    if not orders or not any(row["ticket"] == position_id for row in orders):
        raise TelemetryValidationError("Falta la orden de apertura de la posición")
    if any(
        row["position_id"] != position_id and row["position_by_id"] != position_id for row in orders
    ):
        raise TelemetryValidationError("Órdenes de reconciliación pertenecen a otra posición")


def _collection(value: Any, *, paginated: bool = False) -> list[Any]:
    collection = _object(value, "colección")
    v1._require_exact_fields(collection, {"status", "total", "items"}, "colección")
    status = v1._required_string(collection, "status")
    rows = collection["items"]
    if not isinstance(rows, list) or len(rows) > 200:
        raise TelemetryValidationError("Colección limitada a 200 registros")
    total = collection["total"]
    if status == "error":
        if total is not None or rows:
            raise TelemetryValidationError("Error de colección debe tener total null y lista vacía")
    elif paginated and status in {"partial", "paged_complete"}:
        v1._integer_range(total, "total", minimum=0, maximum=2**31 - 1)
        if len(rows) > total:
            raise TelemetryValidationError("Página excede el total declarado")
    else:
        v1._integer_range(total, "total", minimum=0, maximum=2**31 - 1)
        if not (
            status == "complete"
            and total == len(rows)
            or status == "truncated"
            and 0 < len(rows) < total
        ):
            raise TelemetryValidationError("Estado y conteos inconsistentes")
    return rows


def _pagination(
    value: Any,
    payload: dict[str, Any],
    collections: dict[str, list[dict[str, Any]]],
) -> None:
    pagination = _object(value, "pagination")
    v1._require_exact_fields(
        pagination,
        {"snapshot_id", "after", "through", "has_more"},
        "pagination",
    )
    v1._identifier(pagination, "snapshot_id")
    after = _page_key(pagination["after"], "after")
    through = _page_key(pagination["through"], "through")
    if not isinstance(pagination["has_more"], bool):
        raise TelemetryValidationError("has_more debe ser booleano")
    expected_status = "partial" if pagination["has_more"] else "paged_complete"
    if any(payload[name]["status"] != expected_status for name in ("deals", "orders")):
        raise TelemetryValidationError("Estado de página inconsistente")
    keys = sorted(
        [(int(row["time_msc"]), 0, int(row["ticket"])) for row in collections["deals"]]
        + [(int(row["done_time_msc"]), 1, int(row["ticket"])) for row in collections["orders"]]
    )
    if not keys or len(keys) > 200:
        raise TelemetryValidationError("Página de actividad vacía o demasiado grande")
    if keys[0] <= after or keys[-1] != through:
        raise TelemetryValidationError("Cursores de página inconsistentes")


def _page_key(value: Any, label: str) -> tuple[int, int, int]:
    key = _object(value, label)
    v1._require_exact_fields(key, {"time_msc", "entity_type", "ticket"}, label)
    v1._decimal_text(key, "time_msc", minimum=0, maximum=v1.MAX_INT64)
    v1._decimal_text(key, "ticket", minimum=0, maximum=v1.MAX_UINT64)
    entity = v1._required_string(key, "entity_type")
    if entity not in {"deal", "order"}:
        raise TelemetryValidationError("Tipo de entidad de página inválido")
    return int(key["time_msc"]), 0 if entity == "deal" else 1, int(key["ticket"])


def _deal(row: dict[str, Any]) -> None:
    v1._require_exact_fields(row, v1.DEAL_FIELDS, "deal")
    v1._decimal_text(row, "ticket", minimum=1, maximum=v1.MAX_UINT64)
    for field in ("order_id", "position_id", "time_msc"):
        v1._decimal_text(row, field, minimum=0, maximum=v1.MAX_INT64)
    v1._decimal_text(row, "magic_number", minimum=-(2**63), maximum=v1.MAX_INT64)
    v1._integer_range(row["deal_type"], "deal_type", minimum=0, maximum=17)
    v1._integer_range(row["entry"], "entry", minimum=0, maximum=3)
    if not isinstance(row["symbol"], str) or len(row["symbol"]) > 128:
        raise TelemetryValidationError("Símbolo inválido")
    for field in v1.DEAL_NUMBERS:
        v1._finite_number(row[field], field)
    if row["volume"] < 0:
        raise TelemetryValidationError("Volumen negativo")


def _order(row: dict[str, Any]) -> None:
    v1._require_exact_fields(row, HISTORY_ORDER_FIELDS, "orden histórica")
    v1._decimal_text(row, "ticket", minimum=1, maximum=v1.MAX_UINT64)
    v1._decimal_text(row, "magic_number", minimum=-(2**63), maximum=v1.MAX_INT64)
    for field in ("position_id", "position_by_id", "setup_time_msc", "done_time_msc"):
        v1._decimal_text(row, field, minimum=0, maximum=v1.MAX_INT64)
    v1._integer_range(row["order_type"], "order_type", minimum=0, maximum=8)
    v1._integer_range(row["state"], "state", minimum=0, maximum=9)
    v1._bounded_string(row, "symbol", maximum=128)
    if not isinstance(row["comment"], str) or len(row["comment"]) > 256:
        raise TelemetryValidationError("Comentario inválido")
    for field in ("volume_initial", "volume_current", "price_open", "stop_loss", "take_profit"):
        v1._finite_number(row[field], field)
    if not 0 <= row["volume_current"] <= row["volume_initial"]:
        raise TelemetryValidationError("Volúmenes de orden inconsistentes")
    if int(row["setup_time_msc"]) > int(row["done_time_msc"]):
        raise TelemetryValidationError("Orden completada antes de su creación")

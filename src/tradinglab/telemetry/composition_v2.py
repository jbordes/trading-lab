"""Pure account composition from verified telemetry v2 evidence."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from tradinglab.telemetry.admission_v2 import ProducerIdentity, ProducerRole
from tradinglab.telemetry.contract import DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS
from tradinglab.telemetry.sqlite_store_v2 import (
    RegisteredV2Source,
    RestoredV2Message,
    V2AccountEvidence,
)


@dataclass(frozen=True, slots=True)
class V2FlowState:
    source_id: str | None
    latest_kind: str | None
    latest_captured_at: str | None
    latest_received_at: datetime | None
    heartbeat_captured_at: str | None
    heartbeat_received_at: datetime | None
    heartbeat_status: str | None


@dataclass(frozen=True, slots=True)
class V2LiveState:
    payload: dict[str, Any]
    captured_at: str
    received_at: datetime
    source_id: str
    session_id: str
    sequence: int


@dataclass(frozen=True, slots=True)
class V2HistoricalEntity:
    ticket: str
    values: dict[str, Any] | None
    observed_at: str | None
    received_at: datetime | None
    source_id: str | None
    session_id: str | None
    sequence: int | None
    conflict_at: str | None


@dataclass(frozen=True, slots=True)
class V2CoverageRange:
    from_server_msc: str
    to_server_msc: str


@dataclass(frozen=True, slots=True)
class V2AccountComposition:
    account_id: str
    label: str
    identity: ProducerIdentity
    live_flow: V2FlowState
    activity_flow: V2FlowState
    live: V2LiveState | None
    live_conflict_at: str | None
    activity_conflict_at: str | None
    deals: tuple[V2HistoricalEntity, ...]
    orders: tuple[V2HistoricalEntity, ...]
    deals_coverage: tuple[V2CoverageRange, ...]
    orders_coverage: tuple[V2CoverageRange, ...]
    latest_deals_status: str | None
    latest_orders_status: str | None


def compose_account(evidence: V2AccountEvidence) -> V2AccountComposition:
    """Compose independent live and activity flows without claiming atomicity."""

    if not isinstance(evidence, V2AccountEvidence):
        raise ValueError("Evidencia v2 inválida")
    source_roles = {(source.source_id, source.role) for source in evidence.sources}
    if (
        len(source_roles) != len(evidence.sources)
        or len({source.role for source in evidence.sources}) != len(evidence.sources)
        or any(
            message.account_id != evidence.account_id
            or (message.envelope.source_id, message.role) not in source_roles
            or message.envelope.payload.get("identity")
            != {
                "login_masked": evidence.identity.login_masked,
                "server": evidence.identity.server,
                "currency": evidence.identity.currency,
            }
            for message in evidence.messages
        )
    ):
        raise ValueError("La evidencia no pertenece a la cuenta y fuentes registradas")
    live_messages = tuple(
        message for message in evidence.messages if message.role is ProducerRole.LIVE
    )
    activity_messages = tuple(
        message for message in evidence.messages if message.role is ProducerRole.ACTIVITY
    )
    activity_batches = tuple(
        message
        for message in activity_messages
        if message.envelope.kind == "activity_batch" and _capture_is_plausible(message)
    )
    live, live_conflict_at = _select_live(live_messages)
    resolved_activity, activity_conflict_at = _resolve_activity(activity_batches)
    latest_activity = _latest(resolved_activity)
    statuses = (
        (
            latest_activity.envelope.payload["deals"]["status"],
            latest_activity.envelope.payload["orders"]["status"],
        )
        if latest_activity is not None
        else (None, None)
    )
    return V2AccountComposition(
        account_id=evidence.account_id,
        label=evidence.label,
        identity=evidence.identity,
        live_flow=_flow_state(evidence.sources, live_messages, ProducerRole.LIVE),
        activity_flow=_flow_state(evidence.sources, activity_messages, ProducerRole.ACTIVITY),
        live=live,
        live_conflict_at=live_conflict_at,
        activity_conflict_at=activity_conflict_at,
        deals=_project_entities(activity_batches, "deals"),
        orders=_project_entities(activity_batches, "orders"),
        deals_coverage=_coverage(resolved_activity, "deals"),
        orders_coverage=_coverage(resolved_activity, "orders"),
        latest_deals_status=statuses[0],
        latest_orders_status=statuses[1],
    )


def _flow_state(
    sources: tuple[RegisteredV2Source, ...],
    messages: tuple[RestoredV2Message, ...],
    role: ProducerRole,
) -> V2FlowState:
    source = next((item.source_id for item in sources if item.role is role), None)
    latest = _latest(iter(messages))
    heartbeat = _latest(message for message in messages if message.envelope.kind == "heartbeat")
    return V2FlowState(
        source_id=source,
        latest_kind=latest.envelope.kind if latest else None,
        latest_captured_at=latest.envelope.captured_at if latest else None,
        latest_received_at=latest.received_at if latest else None,
        heartbeat_captured_at=heartbeat.envelope.captured_at if heartbeat else None,
        heartbeat_received_at=heartbeat.received_at if heartbeat else None,
        heartbeat_status=heartbeat.envelope.payload["status"] if heartbeat else None,
    )


def _select_live(
    messages: tuple[RestoredV2Message, ...],
) -> tuple[V2LiveState | None, str | None]:
    eligible = [
        message
        for message in messages
        if message.envelope.kind == "live_snapshot" and _capture_is_plausible(message)
    ]
    selected, conflict_at = _select_observation(eligible, lambda message: message.envelope.payload)
    if selected is None:
        return None, conflict_at
    return (
        V2LiveState(
            payload=deepcopy(selected.envelope.payload),
            captured_at=selected.envelope.captured_at,
            received_at=selected.received_at,
            source_id=selected.envelope.source_id,
            session_id=selected.envelope.session_id,
            sequence=selected.envelope.sequence,
        ),
        conflict_at,
    )


def _project_entities(
    messages: tuple[RestoredV2Message, ...], collection: str
) -> tuple[V2HistoricalEntity, ...]:
    observations: dict[str, list[tuple[RestoredV2Message, dict[str, Any]]]] = {}
    for message in messages:
        if message.envelope.kind != "activity_batch":
            continue
        for row in message.envelope.payload[collection]["items"]:
            observations.setdefault(row["ticket"], []).append((message, row))

    projected: list[V2HistoricalEntity] = []
    for ticket, candidates in observations.items():
        values_by_id = {candidate.message_id: row for candidate, row in candidates}
        selected, conflict_at = _select_observation(
            [message for message, _ in candidates],
            partial(_entity_value, values_by_id),
        )
        if selected is None:
            projected.append(
                V2HistoricalEntity(ticket, None, None, None, None, None, None, conflict_at)
            )
            continue
        values = next(
            row for message, row in candidates if message.message_id == selected.message_id
        )
        projected.append(
            V2HistoricalEntity(
                ticket=ticket,
                values=deepcopy(values),
                observed_at=selected.envelope.captured_at,
                received_at=selected.received_at,
                source_id=selected.envelope.source_id,
                session_id=selected.envelope.session_id,
                sequence=selected.envelope.sequence,
                conflict_at=conflict_at,
            )
        )
    return tuple(sorted(projected, key=lambda item: (len(item.ticket), item.ticket)))


def _select_observation(
    messages: list[RestoredV2Message],
    value: Callable[[RestoredV2Message], object],
) -> tuple[RestoredV2Message | None, str | None]:
    by_capture: dict[datetime, list[RestoredV2Message]] = {}
    for message in messages:
        by_capture.setdefault(_captured(message), []).append(message)
    conflict_at: str | None = None
    for capture in sorted(by_capture, reverse=True):
        session_winners: dict[str, RestoredV2Message] = {}
        for message in by_capture[capture]:
            current = session_winners.get(message.envelope.session_id)
            if current is None or (
                message.envelope.sequence,
                message.message_id,
            ) > (current.envelope.sequence, current.message_id):
                session_winners[message.envelope.session_id] = message
        winners = tuple(session_winners.values())
        fingerprints = {_fingerprint(value(message)) for message in winners}
        if len(fingerprints) > 1:
            if conflict_at is None:
                conflict_at = _format_instant(capture)
            continue
        return max(winners, key=lambda message: message.message_id), conflict_at
    return None, conflict_at


def _entity_value(values: dict[int, dict[str, Any]], message: RestoredV2Message) -> dict[str, Any]:
    return values[message.message_id]


def _resolve_activity(
    messages: tuple[RestoredV2Message, ...],
) -> tuple[tuple[RestoredV2Message, ...], str | None]:
    by_capture: dict[datetime, list[RestoredV2Message]] = {}
    for message in messages:
        by_capture.setdefault(_captured(message), []).append(message)
    resolved: list[RestoredV2Message] = []
    conflict_at: str | None = None
    for capture in sorted(by_capture):
        session_winners: dict[str, RestoredV2Message] = {}
        for message in by_capture[capture]:
            current = session_winners.get(message.envelope.session_id)
            if current is None or (
                message.envelope.sequence,
                message.message_id,
            ) > (current.envelope.sequence, current.message_id):
                session_winners[message.envelope.session_id] = message
        winners = tuple(session_winners.values())
        if len({_fingerprint(item.envelope.payload) for item in winners}) > 1:
            conflict_at = _format_instant(capture)
            continue
        resolved.append(max(winners, key=lambda item: item.message_id))
    return tuple(resolved), conflict_at


def _coverage(
    messages: tuple[RestoredV2Message, ...], collection: str
) -> tuple[V2CoverageRange, ...]:
    ranges: list[tuple[int, int]] = []
    for message in messages:
        if (
            message.envelope.kind == "activity_batch"
            and message.envelope.payload["reason"] != "position_reconcile"
            and message.envelope.payload[collection]["status"] == "complete"
        ):
            window = message.envelope.payload["window"]
            ranges.append((int(window["from_server_msc"]), int(window["to_server_msc"])))
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return tuple(V2CoverageRange(str(start), str(end)) for start, end in merged)


def _latest(messages: Iterable[RestoredV2Message]) -> RestoredV2Message | None:
    return max(messages, key=lambda item: (_captured(item), item.message_id), default=None)


def _captured(message: RestoredV2Message) -> datetime:
    return datetime.fromisoformat(message.envelope.captured_at)


def _capture_is_plausible(message: RestoredV2Message) -> bool:
    tolerance = timedelta(seconds=DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS)
    return _captured(message) <= message.received_at + tolerance


def _format_instant(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _fingerprint(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

"""Incremental in-memory projection for verified telemetry v2 evidence."""

from __future__ import annotations

import json
from bisect import insort
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from threading import RLock
from typing import Any

from tradinglab.telemetry.admission_v2 import ProducerIdentity, ProducerRole
from tradinglab.telemetry.composition_v2 import (
    V2AccountComposition,
    V2CoverageRange,
    V2FlowState,
    V2HistoricalEntity,
    V2LiveState,
)
from tradinglab.telemetry.contract import DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS
from tradinglab.telemetry.sqlite_store_v2 import (
    RestoredV2Message,
    V2AccountEvidence,
)


class V2ProjectionCursorError(ValueError):
    """A projection update did not advance its durable message cursor."""


class V2IncrementalAccountProjection:
    """Maintain one account view without recomposing its full message history."""

    def __init__(self, evidence: V2AccountEvidence) -> None:
        _validate_evidence(evidence)
        self._account_id = evidence.account_id
        self._label = evidence.label
        self._identity = evidence.identity
        self._sources = evidence.sources
        self._source_roles = {source.source_id: source.role for source in evidence.sources}
        self._latest_by_role: dict[ProducerRole, RestoredV2Message] = {}
        self._heartbeat_by_role: dict[ProducerRole, RestoredV2Message] = {}
        self._live_observations: dict[datetime, dict[str, RestoredV2Message]] = {}
        self._live_captures: list[datetime] = []
        self._activity_observations: dict[datetime, dict[str, RestoredV2Message]] = {}
        self._activity_captures: list[datetime] = []
        self._resolved_activity: dict[datetime, RestoredV2Message] = {}
        self._activity_conflicts: set[datetime] = set()
        self._entity_observations: dict[
            str,
            dict[
                str,
                dict[datetime, dict[str, tuple[RestoredV2Message, dict[str, Any]]]],
            ],
        ] = {"deals": {}, "orders": {}}
        self._entity_captures: dict[str, dict[str, list[datetime]]] = {
            "deals": {},
            "orders": {},
        }
        self._entities: dict[str, dict[str, V2HistoricalEntity]] = {
            "deals": {},
            "orders": {},
        }
        self._live: V2LiveState | None = None
        self._live_conflict_at: str | None = None
        self._activity_conflict_at: str | None = None
        self._coverage: dict[str, tuple[V2CoverageRange, ...]] = {
            "deals": (),
            "orders": (),
        }
        self._latest_status: dict[str, str | None] = {
            "deals": None,
            "orders": None,
        }
        self._last_message_id = 0
        self._lock = RLock()

        for message in sorted(evidence.messages, key=lambda item: item.message_id):
            self._advance(message)

    @property
    def last_message_id(self) -> int:
        """Return the last durable row incorporated into this projection."""

        with self._lock:
            return self._last_message_id

    def apply(self, message: RestoredV2Message) -> None:
        """Incorporate one newly committed and verified message exactly once."""

        with self._lock:
            self._advance(message)

    def snapshot(self) -> V2AccountComposition:
        """Return an isolated account view whose cost is independent of message count."""

        with self._lock:
            return V2AccountComposition(
                account_id=self._account_id,
                label=self._label,
                identity=self._identity,
                live_flow=self._flow_state(ProducerRole.LIVE),
                activity_flow=self._flow_state(ProducerRole.ACTIVITY),
                live=_copy_live(self._live),
                live_conflict_at=self._live_conflict_at,
                activity_conflict_at=self._activity_conflict_at,
                deals=self._entity_snapshot("deals"),
                orders=self._entity_snapshot("orders"),
                deals_coverage=self._coverage["deals"],
                orders_coverage=self._coverage["orders"],
                latest_deals_status=self._latest_status["deals"],
                latest_orders_status=self._latest_status["orders"],
            )

    def _advance(self, message: RestoredV2Message) -> None:
        _validate_message(
            message,
            self._account_id,
            self._identity,
            self._source_roles,
        )
        if message.message_id <= self._last_message_id:
            raise V2ProjectionCursorError(
                "El mensaje no avanza el cursor durable de la proyecci\u00f3n v2"
            )

        self._update_flow(message)
        if _capture_is_plausible(message):
            if message.envelope.kind == "live_snapshot":
                self._update_live(message)
            elif message.envelope.kind == "activity_batch":
                self._update_activity(message)
        self._last_message_id = message.message_id

    def _update_flow(self, message: RestoredV2Message) -> None:
        current = self._latest_by_role.get(message.role)
        if current is None or _message_order(message) > _message_order(current):
            self._latest_by_role[message.role] = message
        if message.envelope.kind == "heartbeat":
            heartbeat = self._heartbeat_by_role.get(message.role)
            if heartbeat is None or _message_order(message) > _message_order(heartbeat):
                self._heartbeat_by_role[message.role] = message

    def _update_live(self, message: RestoredV2Message) -> None:
        capture = _captured(message)
        if capture not in self._live_observations:
            self._live_observations[capture] = {}
            insort(self._live_captures, capture)
        winners = self._live_observations[capture]
        current = winners.get(message.envelope.session_id)
        if current is None or _session_order(message) > _session_order(current):
            winners[message.envelope.session_id] = message
        self._refresh_live()

    def _refresh_live(self) -> None:
        conflict_at: str | None = None
        for capture in reversed(self._live_captures):
            winners = tuple(self._live_observations[capture].values())
            if len({_fingerprint(item.envelope.payload) for item in winners}) > 1:
                if conflict_at is None:
                    conflict_at = _format_instant(capture)
                continue
            selected = max(winners, key=lambda item: item.message_id)
            self._live = V2LiveState(
                payload=deepcopy(selected.envelope.payload),
                captured_at=selected.envelope.captured_at,
                received_at=selected.received_at,
                source_id=selected.envelope.source_id,
                session_id=selected.envelope.session_id,
                sequence=selected.envelope.sequence,
            )
            self._live_conflict_at = conflict_at
            return
        self._live = None
        self._live_conflict_at = conflict_at

    def _update_activity(self, message: RestoredV2Message) -> None:
        capture = _captured(message)
        if capture not in self._activity_observations:
            self._activity_observations[capture] = {}
            insort(self._activity_captures, capture)
        winners = self._activity_observations[capture]
        current = winners.get(message.envelope.session_id)
        if current is None or _session_order(message) > _session_order(current):
            winners[message.envelope.session_id] = message
            self._resolve_activity_capture(capture)

        for collection in ("deals", "orders"):
            for row in message.envelope.payload[collection]["items"]:
                ticket = row["ticket"]
                captures = self._entity_observations[collection].setdefault(ticket, {})
                if capture not in captures:
                    captures[capture] = {}
                    capture_order = self._entity_captures[collection].setdefault(ticket, [])
                    insort(capture_order, capture)
                sessions = captures[capture]
                previous = sessions.get(message.envelope.session_id)
                if previous is None or _session_order(message) > _session_order(previous[0]):
                    sessions[message.envelope.session_id] = (message, deepcopy(row))
                    self._refresh_entity(collection, ticket)

        self._refresh_activity_summary()

    def _resolve_activity_capture(self, capture: datetime) -> None:
        winners = tuple(self._activity_observations[capture].values())
        if len({_fingerprint(item.envelope.payload) for item in winners}) > 1:
            self._resolved_activity.pop(capture, None)
            self._activity_conflicts.add(capture)
            return
        self._resolved_activity[capture] = max(winners, key=lambda item: item.message_id)
        self._activity_conflicts.discard(capture)

    def _refresh_activity_summary(self) -> None:
        resolved = tuple(self._resolved_activity.values())
        latest = max(resolved, key=_message_order, default=None)
        for collection in ("deals", "orders"):
            self._latest_status[collection] = (
                latest.envelope.payload[collection]["status"] if latest else None
            )
            self._coverage[collection] = _coverage(resolved, collection)
        self._activity_conflict_at = next(
            (
                _format_instant(capture)
                for capture in reversed(self._activity_captures)
                if capture in self._activity_conflicts
            ),
            None,
        )

    def _refresh_entity(self, collection: str, ticket: str) -> None:
        captures = self._entity_observations[collection][ticket]
        conflict_at: str | None = None
        for capture in reversed(self._entity_captures[collection][ticket]):
            winners = tuple(captures[capture].values())
            if len({_fingerprint(row) for _, row in winners}) > 1:
                if conflict_at is None:
                    conflict_at = _format_instant(capture)
                continue
            message, row = max(winners, key=lambda item: item[0].message_id)
            self._entities[collection][ticket] = V2HistoricalEntity(
                ticket=ticket,
                values=deepcopy(row),
                observed_at=message.envelope.captured_at,
                received_at=message.received_at,
                source_id=message.envelope.source_id,
                session_id=message.envelope.session_id,
                sequence=message.envelope.sequence,
                conflict_at=conflict_at,
            )
            return
        self._entities[collection][ticket] = V2HistoricalEntity(
            ticket, None, None, None, None, None, None, conflict_at
        )

    def _flow_state(self, role: ProducerRole) -> V2FlowState:
        source = next(
            (item.source_id for item in self._sources if item.role is role),
            None,
        )
        latest = self._latest_by_role.get(role)
        heartbeat = self._heartbeat_by_role.get(role)
        return V2FlowState(
            source_id=source,
            latest_kind=latest.envelope.kind if latest else None,
            latest_captured_at=latest.envelope.captured_at if latest else None,
            latest_received_at=latest.received_at if latest else None,
            heartbeat_captured_at=(heartbeat.envelope.captured_at if heartbeat else None),
            heartbeat_received_at=heartbeat.received_at if heartbeat else None,
            heartbeat_status=heartbeat.envelope.payload["status"] if heartbeat else None,
        )

    def _entity_snapshot(self, collection: str) -> tuple[V2HistoricalEntity, ...]:
        return tuple(
            replace(entity, values=deepcopy(entity.values))
            for entity in sorted(
                self._entities[collection].values(),
                key=lambda item: (len(item.ticket), item.ticket),
            )
        )


def _validate_evidence(evidence: V2AccountEvidence) -> None:
    if not isinstance(evidence, V2AccountEvidence):
        raise ValueError("Evidencia v2 inv\u00e1lida")
    roles = {(source.source_id, source.role) for source in evidence.sources}
    if len(roles) != len(evidence.sources) or len(
        {source.role for source in evidence.sources}
    ) != len(evidence.sources):
        raise ValueError("Fuentes v2 duplicadas")
    source_roles = {source.source_id: source.role for source in evidence.sources}
    for message in evidence.messages:
        _validate_message(message, evidence.account_id, evidence.identity, source_roles)
    message_ids = [message.message_id for message in evidence.messages]
    if any(message_id < 1 for message_id in message_ids) or len(message_ids) != len(
        set(message_ids)
    ):
        raise ValueError("Cursores durables v2 inv\u00e1lidos")


def _validate_message(
    message: RestoredV2Message,
    account_id: str,
    identity: ProducerIdentity,
    source_roles: dict[str, ProducerRole],
) -> None:
    if (
        not isinstance(message, RestoredV2Message)
        or message.account_id != account_id
        or source_roles.get(message.envelope.source_id) is not message.role
        or not identity.matches(message.envelope.payload.get("identity"))
    ):
        raise ValueError("El mensaje no pertenece a la cuenta y fuente proyectadas")


def _coverage(
    messages: tuple[RestoredV2Message, ...], collection: str
) -> tuple[V2CoverageRange, ...]:
    ranges = [
        (
            int(message.envelope.payload["window"]["from_server_msc"]),
            int(message.envelope.payload["window"]["to_server_msc"]),
        )
        for message in messages
        if message.envelope.payload[collection]["status"] == "complete"
    ]
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return tuple(V2CoverageRange(str(start), str(end)) for start, end in merged)


def _copy_live(live: V2LiveState | None) -> V2LiveState | None:
    return replace(live, payload=deepcopy(live.payload)) if live else None


def _captured(message: RestoredV2Message) -> datetime:
    return datetime.fromisoformat(message.envelope.captured_at)


def _capture_is_plausible(message: RestoredV2Message) -> bool:
    tolerance = timedelta(seconds=DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS)
    return _captured(message) <= message.received_at + tolerance


def _message_order(message: RestoredV2Message) -> tuple[datetime, int]:
    return _captured(message), message.message_id


def _session_order(message: RestoredV2Message) -> tuple[int, int]:
    return message.envelope.sequence, message.message_id


def _format_instant(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _fingerprint(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

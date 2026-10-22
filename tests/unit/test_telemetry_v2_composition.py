from __future__ import annotations

import json
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradinglab.telemetry.admission_v2 import (
    ProducerIdentity,
    ProducerRegistration,
    ProducerRole,
    V2ProducerDirectory,
)
from tradinglab.telemetry.composition_v2 import compose_account
from tradinglab.telemetry.projection_v2 import (
    V2IncrementalAccountProjection,
    V2ProjectionCursorError,
)
from tradinglab.telemetry.sqlite_store_v2 import (
    RegisteredV2Source,
    RestoredV2Message,
    V2AccountEvidence,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "telemetry_v2"
IDENTITY = ProducerIdentity("****1234", "DEMO-SERVER", "USD")
LIVE_CREDENTIAL = "synthetic-live-credential-safe-length"
ACTIVITY_CREDENTIAL = "synthetic-activity-credential-safe-length"
SOURCES = (
    RegisteredV2Source("synthetic-activity", ProducerRole.ACTIVITY),
    RegisteredV2Source("synthetic-live", ProducerRole.LIVE),
)


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def directory() -> V2ProducerDirectory:
    return V2ProducerDirectory(
        (
            ProducerRegistration(
                "account-demo",
                "synthetic-live",
                ProducerRole.LIVE,
                IDENTITY,
                LIVE_CREDENTIAL,
            ),
            ProducerRegistration(
                "account-demo",
                "synthetic-activity",
                ProducerRole.ACTIVITY,
                IDENTITY,
                ACTIVITY_CREDENTIAL,
            ),
        )
    )


def restored(
    value: dict[str, Any],
    message_id: int,
    *,
    received_at: datetime | None = None,
) -> RestoredV2Message:
    credential = (
        ACTIVITY_CREDENTIAL if value["source_id"] == "synthetic-activity" else LIVE_CREDENTIAL
    )
    authorized = directory().authorize(json.dumps(value).encode(), f"Bearer {credential}")
    return RestoredV2Message(
        account_id="account-demo",
        role=authorized.role,
        envelope=authorized.envelope,
        received_at=received_at or datetime(2026, 10, 22, 8, 30, tzinfo=UTC),
        message_id=message_id,
        sequence_gap=0,
        out_of_order=False,
    )


def resequence(
    value: dict[str, Any],
    sequence: int,
    captured_at: str,
    *,
    session_id: str = "synthetic-session-1",
) -> dict[str, Any]:
    value["session_id"] = session_id
    value["sequence"] = sequence
    value["event_id"] = f"{session_id}:{sequence}"
    value["captured_at"] = captured_at
    return value


def evidence(*messages: RestoredV2Message) -> V2AccountEvidence:
    return V2AccountEvidence("account-demo", "Demo", IDENTITY, SOURCES, messages)


class V2CompositionTest(unittest.TestCase):
    def test_empty_account_preserves_registered_flows_without_inventing_data(self) -> None:
        result = compose_account(evidence())

        self.assertEqual(result.live_flow.source_id, "synthetic-live")
        self.assertEqual(result.activity_flow.source_id, "synthetic-activity")
        self.assertIsNone(result.live)
        self.assertEqual(result.deals, ())
        self.assertEqual(result.orders, ())
        self.assertIsNone(result.latest_deals_status)

    def test_composes_live_health_activity_entities_and_coverage_independently(self) -> None:
        live = restored(fixture("live-empty"), 1)
        heartbeat = fixture("heartbeat")
        heartbeat["captured_at"] = "2026-10-22T08:05:00Z"
        health = restored(heartbeat, 2)
        order = restored(fixture("activity-canceled-order"), 3)
        deal = restored(fixture("activity-truncated"), 4)

        result = compose_account(evidence(live, health, order, deal))

        self.assertEqual(result.live.payload["account"]["balance"], 10000)
        self.assertEqual(result.live.sequence, 1)
        self.assertEqual(result.live_flow.latest_kind, "heartbeat")
        self.assertEqual(result.live_flow.heartbeat_status, "ok")
        self.assertEqual(result.orders[0].ticket, "900000000000000001")
        self.assertEqual(result.deals[0].ticket, "900000000000000002")
        self.assertEqual(result.latest_deals_status, "truncated")
        self.assertEqual(result.latest_orders_status, "complete")
        self.assertEqual(len(result.deals_coverage), 1)
        self.assertEqual(len(result.orders_coverage), 1)

    def test_late_old_batch_does_not_revert_newer_entity_correction(self) -> None:
        original = resequence(fixture("activity-canceled-order"), 1, "2026-10-22T08:10:00Z")
        delayed = resequence(fixture("activity-canceled-order"), 2, "2026-10-22T08:15:00Z")
        corrected = resequence(fixture("activity-canceled-order"), 3, "2026-10-22T08:20:00Z")
        delayed["payload"]["orders"]["items"][0]["price_open"] = 4250
        corrected["payload"]["orders"]["items"][0]["price_open"] = 4300

        result = compose_account(
            evidence(
                restored(original, 1),
                restored(corrected, 2),
                restored(delayed, 3),
            )
        )

        self.assertEqual(result.orders[0].values["price_open"], 4300)
        self.assertEqual(result.orders[0].sequence, 3)
        self.assertIsNone(result.orders[0].conflict_at)

    def test_cross_session_entity_conflict_preserves_previous_observation(self) -> None:
        stable = resequence(
            fixture("activity-canceled-order"),
            1,
            "2026-10-22T08:10:00Z",
            session_id="stable-session",
        )
        left = resequence(
            fixture("activity-canceled-order"),
            1,
            "2026-10-22T08:20:00Z",
            session_id="left-session",
        )
        right = resequence(
            fixture("activity-canceled-order"),
            1,
            "2026-10-22T08:20:00Z",
            session_id="right-session",
        )
        left["payload"]["orders"]["items"][0]["price_open"] = 4300
        right["payload"]["orders"]["items"][0]["price_open"] = 4400

        result = compose_account(
            evidence(restored(stable, 1), restored(left, 2), restored(right, 3))
        )

        self.assertEqual(result.orders[0].values["price_open"], 4200)
        self.assertEqual(result.orders[0].conflict_at, "2026-10-22T08:20:00Z")

        resolved = resequence(
            fixture("activity-canceled-order"),
            1,
            "2026-10-22T08:30:00Z",
            session_id="resolved-session",
        )
        resolved["payload"]["orders"]["items"][0]["price_open"] = 4500
        later = compose_account(
            evidence(
                restored(stable, 1),
                restored(left, 2),
                restored(right, 3),
                restored(resolved, 4),
            )
        )
        self.assertEqual(later.orders[0].values["price_open"], 4500)
        self.assertIsNone(later.orders[0].conflict_at)

    def test_live_conflict_preserves_previous_state_until_later_observation(self) -> None:
        stable = resequence(
            fixture("live-empty"),
            1,
            "2026-10-22T08:10:00Z",
            session_id="stable-session",
        )
        left = resequence(
            fixture("live-empty"),
            1,
            "2026-10-22T08:20:00Z",
            session_id="left-session",
        )
        right = resequence(
            fixture("live-empty"),
            1,
            "2026-10-22T08:20:00Z",
            session_id="right-session",
        )
        left["payload"]["account"]["equity"] = 9900
        right["payload"]["account"]["equity"] = 9800

        result = compose_account(
            evidence(restored(stable, 1), restored(left, 2), restored(right, 3))
        )

        self.assertEqual(result.live.payload["account"]["equity"], 10000)
        self.assertEqual(result.live_conflict_at, "2026-10-22T08:20:00Z")

    def test_activity_conflict_does_not_extend_coverage_or_replace_status(self) -> None:
        stable = resequence(
            fixture("activity-canceled-order"),
            1,
            "2026-10-22T08:10:00Z",
            session_id="stable-session",
        )
        left = resequence(
            fixture("activity-deals-error"),
            1,
            "2026-10-22T08:20:00Z",
            session_id="left-session",
        )
        right = resequence(
            fixture("activity-truncated"),
            1,
            "2026-10-22T08:20:00Z",
            session_id="right-session",
        )

        result = compose_account(
            evidence(restored(stable, 1), restored(left, 2), restored(right, 3))
        )

        self.assertEqual(result.activity_conflict_at, "2026-10-22T08:20:00Z")
        self.assertEqual(result.latest_deals_status, "complete")
        self.assertEqual(result.latest_orders_status, "complete")
        self.assertEqual(len(result.deals_coverage), 1)
        self.assertEqual(len(result.orders_coverage), 1)

    def test_future_capture_does_not_displace_live_or_extend_coverage(self) -> None:
        current = restored(fixture("live-empty"), 1)
        future = resequence(fixture("live-empty"), 2, "2026-10-23T08:00:00Z")
        future["payload"]["account"]["balance"] = 1
        future_activity = resequence(fixture("activity-canceled-order"), 2, "2026-10-23T08:00:00Z")

        result = compose_account(
            evidence(current, restored(future, 2), restored(future_activity, 3))
        )

        self.assertEqual(result.live.payload["account"]["balance"], 10000)
        self.assertEqual(result.orders, ())
        self.assertEqual(result.orders_coverage, ())

    def test_complete_adjacent_windows_merge_but_truncated_does_not_cover(self) -> None:
        first = resequence(fixture("activity-canceled-order"), 1, "2026-10-22T08:00:01Z")
        first["payload"]["orders"] = {"status": "complete", "total": 0, "items": []}
        second = resequence(fixture("activity-canceled-order"), 2, "2026-10-22T08:00:02Z")
        second["payload"]["window"] = {
            "from_server_msc": "1792656060001",
            "to_server_msc": "1792656120000",
        }
        second["payload"]["orders"] = {
            "status": "complete",
            "total": 0,
            "items": [],
        }
        partial = resequence(fixture("activity-truncated"), 3, "2026-10-22T08:00:03Z")

        result = compose_account(
            evidence(restored(first, 1), restored(second, 2), restored(partial, 3))
        )

        self.assertEqual(len(result.orders_coverage), 1)
        self.assertEqual(result.orders_coverage[0].from_server_msc, "1792656000000")
        self.assertEqual(result.orders_coverage[0].to_server_msc, "1792656120000")
        self.assertEqual(len(result.deals_coverage), 1)


class V2IncrementalProjectionTest(unittest.TestCase):
    def test_replay_and_each_increment_match_reference_composition(self) -> None:
        stable_live = resequence(
            fixture("live-empty"), 1, "2026-10-22T08:10:00Z", session_id="live-stable"
        )
        conflicting_live = resequence(
            fixture("live-empty"), 1, "2026-10-22T08:20:00Z", session_id="live-left"
        )
        other_live = resequence(
            fixture("live-empty"), 1, "2026-10-22T08:20:00Z", session_id="live-right"
        )
        conflicting_live["payload"]["account"]["equity"] = 9900
        other_live["payload"]["account"]["equity"] = 9800
        resolved_live = resequence(
            fixture("live-empty"), 1, "2026-10-22T08:30:00Z", session_id="live-resolved"
        )
        old_order = resequence(
            fixture("activity-canceled-order"),
            1,
            "2026-10-22T08:05:00Z",
            session_id="activity-old",
        )
        corrected_order = resequence(
            fixture("activity-canceled-order"),
            1,
            "2026-10-22T08:25:00Z",
            session_id="activity-corrected",
        )
        corrected_order["payload"]["orders"]["items"][0]["price_open"] = 4300
        heartbeat = resequence(
            fixture("heartbeat"), 2, "2026-10-22T08:35:00Z", session_id="live-resolved"
        )
        messages = (
            restored(stable_live, 1),
            restored(old_order, 2),
            restored(conflicting_live, 3),
            restored(other_live, 4),
            restored(corrected_order, 5),
            restored(resolved_live, 6),
            restored(heartbeat, 7),
        )
        projection = V2IncrementalAccountProjection(evidence())

        prefix: list[RestoredV2Message] = []
        for message in messages:
            prefix.append(message)
            projection.apply(message)
            self.assertEqual(projection.snapshot(), compose_account(evidence(*prefix)))
            self.assertEqual(projection.last_message_id, message.message_id)

        replay = V2IncrementalAccountProjection(evidence(*reversed(messages)))
        self.assertEqual(replay.snapshot(), compose_account(evidence(*messages)))

    def test_activity_conflicts_and_late_corrections_match_reference(self) -> None:
        stable = resequence(
            fixture("activity-canceled-order"),
            1,
            "2026-10-22T08:10:00Z",
            session_id="stable-session",
        )
        left = resequence(
            fixture("activity-canceled-order"),
            1,
            "2026-10-22T08:20:00Z",
            session_id="left-session",
        )
        right = resequence(
            fixture("activity-truncated"),
            1,
            "2026-10-22T08:20:00Z",
            session_id="right-session",
        )
        right["payload"]["orders"]["items"] = deepcopy(left["payload"]["orders"]["items"])
        right["payload"]["orders"]["total"] = 1
        right["payload"]["orders"]["items"][0]["price_open"] = 4400
        late = resequence(
            fixture("activity-canceled-order"),
            2,
            "2026-10-22T08:15:00Z",
            session_id="late-session",
        )
        late["payload"]["orders"]["items"][0]["price_open"] = 4250
        messages = (
            restored(stable, 1),
            restored(left, 2),
            restored(right, 3),
            restored(late, 4),
        )

        projection = V2IncrementalAccountProjection(evidence(*messages))

        self.assertEqual(projection.snapshot(), compose_account(evidence(*messages)))

    def test_rejects_wrong_account_and_non_advancing_cursor_without_mutation(self) -> None:
        message = restored(fixture("live-empty"), 1)
        projection = V2IncrementalAccountProjection(evidence(message))
        before = projection.snapshot()

        with self.assertRaises(V2ProjectionCursorError):
            projection.apply(message)
        wrong_account = replace(message, account_id="another-account", message_id=2)
        with self.assertRaises(ValueError):
            projection.apply(wrong_account)

        self.assertEqual(projection.snapshot(), before)
        self.assertEqual(projection.last_message_id, 1)

    def test_snapshots_do_not_expose_mutable_projection_state(self) -> None:
        live = restored(fixture("live-empty"), 1)
        order = restored(fixture("activity-canceled-order"), 2)
        projection = V2IncrementalAccountProjection(evidence(live, order))

        first = projection.snapshot()
        first.live.payload["account"]["balance"] = 1
        first.orders[0].values["price_open"] = 1

        second = projection.snapshot()
        self.assertEqual(second.live.payload["account"]["balance"], 10000)
        self.assertEqual(second.orders[0].values["price_open"], 4200)


if __name__ == "__main__":
    unittest.main()

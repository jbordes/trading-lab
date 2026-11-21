from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from tradinglab.dashboard.telemetry_v2 import (
    LoopbackV2HistoryClient,
    TelemetryCyclePerformance,
    TelemetryPositionCycle,
    TelemetryPositionCyclePage,
    V2HistoryProvider,
)
from tradinglab.metrics.position_cycles import CycleExclusion
from tradinglab.telemetry.admission_v2 import (
    AdmissionDisposition,
    AuthorizedEnvelope,
    ProducerIdentity,
    ProducerRegistration,
    ProducerRole,
    TradingEventsProducerDirectory,
    V2AuthorizationError,
    V2ConflictError,
    V2StaleSequenceError,
)
from tradinglab.telemetry.central_schema import CENTRAL_SCHEMA_VERSION, create_central_database
from tradinglab.telemetry.composition_v2 import compose_account
from tradinglab.telemetry.http_contracts_v2 import position_cycle_item
from tradinglab.telemetry.persistent_receiver_v2 import PersistentV2TelemetryReceiver
from tradinglab.telemetry.sqlite_store_v2 import (
    V2RegistrationConflictError,
    V2StorageError,
    V2TelemetryRegistry,
    open_v2_registry,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "telemetry_v2"
IDENTITY = ProducerIdentity("****1234", "DEMO-SERVER", "USD")
LIVE_CREDENTIAL = "synthetic-live-credential-safe-length"
ACTIVITY_CREDENTIAL = "synthetic-activity-credential-safe-length"


class FailingCommitConnection(sqlite3.Connection):
    after_commit = False

    def __exit__(self, *args: object) -> None:
        if self.after_commit:
            super().__exit__(*args)
        else:
            self.rollback()
        raise sqlite3.OperationalError("injected commit failure")


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def body(
    name: str,
    sequence: int | None = None,
    *,
    session_id: str = "synthetic-session-1",
) -> bytes:
    value = fixture(name)
    if sequence is not None:
        value["session_id"] = session_id
        value["sequence"] = sequence
        value["event_id"] = f"{session_id}:{sequence}"
    return json.dumps(value).encode()


def directory() -> TradingEventsProducerDirectory:
    return TradingEventsProducerDirectory(
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


def authorized(name: str, sequence: int | None = None) -> AuthorizedEnvelope:
    credential = ACTIVITY_CREDENTIAL if name.startswith("activity-") else LIVE_CREDENTIAL
    return directory().authorize(body(name, sequence), f"Bearer {credential}")


def authorized_cycle_observation(
    session: str,
    captured_at: str,
    *,
    profit: float = 10,
    magic: str = "11122",
) -> AuthorizedEnvelope:
    value = fixture("activity-position-reconcile")
    value.update(session_id=session, sequence=1, event_id=f"{session}:1", captured_at=captured_at)
    value["payload"]["deals"]["items"][-1]["profit"] = profit
    for collection in ("deals", "orders"):
        for item in value["payload"][collection]["items"]:
            item["magic_number"] = magic
    return directory().authorize(json.dumps(value).encode(), f"Bearer {ACTIVITY_CREDENTIAL}")


def authorized_page(
    sequence: int,
    *,
    ticket: str,
    time_msc: str,
    after_time: str,
    after_ticket: str,
    has_more: bool,
    deal_total: int = 2,
    order_total: int = 0,
    snapshot_id: str = "p:1792656000000:1792656060000:2:0",
) -> AuthorizedEnvelope:
    value = fixture("activity-truncated")
    value["sequence"] = sequence
    value["event_id"] = f"synthetic-session-1:{sequence}"
    deal = value["payload"]["deals"]["items"][0]
    deal["ticket"] = ticket
    deal["time_msc"] = time_msc
    status = "partial" if has_more else "paged_complete"
    value["payload"]["deals"] = {"status": status, "total": deal_total, "items": [deal]}
    value["payload"]["orders"] = {"status": status, "total": order_total, "items": []}
    value["payload"]["pagination"] = {
        "snapshot_id": snapshot_id,
        "after": {
            "time_msc": after_time,
            "entity_type": "deal",
            "ticket": after_ticket,
        },
        "through": {"time_msc": time_msc, "entity_type": "deal", "ticket": ticket},
        "has_more": has_more,
    }
    encoded = json.dumps(value).encode()
    return directory().authorize(encoded, f"Bearer {ACTIVITY_CREDENTIAL}")


def authorized_order_observation(
    sequence: int,
    *,
    ticket: str,
    done_at: datetime,
) -> AuthorizedEnvelope:
    value = fixture("activity-canceled-order")
    session_id = "synthetic-long-history"
    done_msc = int(done_at.timestamp() * 1000)
    value.update(
        session_id=session_id,
        sequence=sequence,
        event_id=f"{session_id}:{sequence}",
        captured_at=done_at.isoformat().replace("+00:00", "Z"),
    )
    value["payload"]["window"] = {
        "from_server_msc": str(done_msc - 30_000),
        "to_server_msc": str(done_msc + 30_000),
    }
    order = value["payload"]["orders"]["items"][0]
    order.update(
        ticket=ticket,
        setup_time_msc=str(done_msc - 90_000),
        done_time_msc=str(done_msc),
    )
    return directory().authorize(json.dumps(value).encode(), f"Bearer {ACTIVITY_CREDENTIAL}")


class V2SqliteTest(unittest.TestCase):
    def test_newer_cycle_conflict_excludes_old_result_until_resolved(self) -> None:
        with open_v2_registry(self.path) as registry:
            for session, captured, profit in (
                ("old", "2026-10-22T08:02:00Z", 10),
                ("conflict-a", "2026-10-22T08:03:00Z", 20),
                ("conflict-b", "2026-10-22T08:03:00Z", 30),
            ):
                registry.store_authorized(
                    authorized_cycle_observation(session, captured, profit=profit),
                    received_at=self.now,
                )
        # The qualification survives reopening and applies to lightweight metric reads too.
        with open_v2_registry(self.path) as registry:
            for include_details in (True, False):
                page = registry.position_cycles("account-demo", include_details=include_details)
                item = page.items[0]
                self.assertEqual(item.cycle.observed_net_result, Decimal("9.8"))
                self.assertEqual(item.cycle.exclusions, (CycleExclusion.CONFLICTING_EVIDENCE,))
                self.assertFalse(item.cycle.eligible_for_autonomous_metrics)
                self.assertIsNone(item.cycle.definitive_net_result)
                metrics = TelemetryCyclePerformance(
                    "account-demo",
                    "synthetic-activity",
                    0,
                    2**62,
                    None,
                    (TelemetryPositionCycle(item.message_id, item.captured_at, item.cycle),),
                    {},
                ).as_dict()
                self.assertEqual(metrics["trade_count"], 0)
                self.assertEqual(metrics["net_profit"], 0)
                client = LoopbackV2HistoryClient(
                    read_authorization="synthetic-read-credential-safe-length",
                    activity_source_id="synthetic-activity",
                )
                parsed = client._position_cycle(
                    json.loads(json.dumps(position_cycle_item(item))), "account-demo"
                )
                self.assertEqual(parsed.cycle.exclusions, item.cycle.exclusions)
                transport = Mock(spec=LoopbackV2HistoryClient)
                transport.deal_history.return_value.coverage = {"status": "complete"}
                transport.position_cycles.return_value = TelemetryPositionCyclePage(
                    "account-demo", "synthetic-activity", None, (parsed,), None
                )
                streamed = (
                    V2HistoryProvider(transport)
                    .cycle_performance_metrics(from_msc=0, to_msc=2**62)
                    .as_dict()
                )
                self.assertEqual(streamed["trade_count"], 0)
                self.assertEqual(streamed["net_profit"], 0)
                self.assertEqual(streamed["by_ea"], [])
            registry.store_authorized(
                authorized_cycle_observation("resolved", "2026-10-22T08:04:00Z", profit=40),
                received_at=self.now,
            )
            cycle = registry.position_cycles("account-demo").items[0].cycle
            self.assertTrue(cycle.eligible_for_autonomous_metrics)
            self.assertEqual(cycle.exclusions, ())
            self.assertEqual(cycle.definitive_net_result, Decimal("39.8"))
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT eligible, exclusions_json FROM position_cycle_observations"
                ).fetchall(),
                [(1, "[]")] * 4,
            )

    def test_cycle_without_unambiguous_capture_waits_for_consistent_evidence(self) -> None:
        with open_v2_registry(self.path) as registry:
            for session, profit in (("variant-a", 20), ("variant-b", 30)):
                registry.store_authorized(
                    authorized_cycle_observation(session, "2026-10-22T08:03:00Z", profit=profit),
                    received_at=self.now,
                )
            self.assertEqual(registry.position_cycles("account-demo").items, ())
            registry.store_authorized(
                authorized_cycle_observation("resolved", "2026-10-22T08:04:00Z"),
                received_at=self.now,
            )
            self.assertTrue(
                registry.position_cycles("account-demo")
                .items[0]
                .cycle.eligible_for_autonomous_metrics
            )

    def test_identical_cycle_captures_are_not_a_conflict(self) -> None:
        with open_v2_registry(self.path) as registry:
            for session in ("copy-a", "copy-b"):
                registry.store_authorized(
                    authorized_cycle_observation(session, "2026-10-22T08:03:00Z"),
                    received_at=self.now,
                )
            page = registry.position_cycles("account-demo")
            self.assertEqual(len(page.items), 1)
            self.assertTrue(page.items[0].cycle.eligible_for_autonomous_metrics)

    def test_magic_filter_cannot_resurrect_old_revision_or_hide_other_owner_conflict(self) -> None:
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(
                authorized_cycle_observation("old", "2026-10-22T08:02:00Z"),
                received_at=self.now,
            )
            registry.store_authorized(
                authorized_cycle_observation("new-owner", "2026-10-22T08:03:00Z", magic="22222"),
                received_at=self.now,
            )
            for filters in ({"owner_magic": "11122"}, {"owner_magics": ("11122",)}):
                self.assertEqual(registry.position_cycles("account-demo", **filters).items, ())
            self.assertEqual(
                registry.position_cycles("account-demo", owner_magic="22222")
                .items[0]
                .cycle.owner_magic,
                "22222",
            )
            registry.store_authorized(
                authorized_cycle_observation("conflicting-owner", "2026-10-22T08:03:00Z"),
                received_at=self.now,
            )
            for filters in ({"owner_magic": "11122"}, {"owner_magics": ("11122", "22222")}):
                page = registry.position_cycles("account-demo", **filters)
                self.assertEqual(len(page.items), 1)
                self.assertIn(CycleExclusion.CONFLICTING_EVIDENCE, page.items[0].cycle.exclusions)

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "telemetry-v2.sqlite3"
        self.now = datetime(2026, 10, 22, 8, 30, tzinfo=UTC)
        create_central_database(self.path)
        with open_v2_registry(self.path) as registry:
            registry.register_account("account-demo", "Demo", IDENTITY, created_at=self.now)
            registry.register_source(
                "synthetic-live",
                "account-demo",
                ProducerRole.LIVE,
                created_at=self.now,
            )
            registry.register_source(
                "synthetic-activity",
                "account-demo",
                ProducerRole.ACTIVITY,
                created_at=self.now,
            )

    def test_account_registration_is_scoped_and_does_not_read_messages(self) -> None:
        with open_v2_registry(self.path) as registry:
            other_identity = ProducerIdentity("****9999", "OTHER-SERVER", "EUR")
            registry.register_account("other-account", "Other", other_identity, created_at=self.now)
            registry.register_source(
                "other-live", "other-account", ProducerRole.LIVE, created_at=self.now
            )
            registry.store_authorized(authorized("live-empty"), received_at=self.now)
        with closing(sqlite3.connect(self.path)) as connection:
            denied_reads: list[str] = []

            def metadata_only(action: int, table: str, *_: object) -> int:
                if action == sqlite3.SQLITE_READ and table in {
                    "telemetry_v2_messages",
                    "telemetry_messages",
                }:
                    denied_reads.append(table)
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            connection.set_authorizer(metadata_only)
            registry = V2TelemetryRegistry(connection)
            registration = registry.account_registration("account-demo")
            self.assertEqual(registration.account_id, "account-demo")
            self.assertEqual(registration.label, "Demo")
            self.assertEqual(registration.identity, IDENTITY)
            self.assertEqual(
                [(source.source_id, source.role) for source in registration.sources],
                [
                    ("synthetic-activity", ProducerRole.ACTIVITY),
                    ("synthetic-live", ProducerRole.LIVE),
                ],
            )
            self.assertEqual(
                registry.account_registration("other-account").identity, other_identity
            )
            self.assertEqual(denied_reads, [])

    def test_account_registration_rejects_missing_or_invalid_account(self) -> None:
        with open_v2_registry(self.path) as registry:
            with self.assertRaises(V2AuthorizationError):
                registry.account_registration("unknown-account")
            with self.assertRaises(ValueError):
                registry.account_registration("../invalid-account")
            self.assertEqual(registry.account_registration("account-demo").identity, IDENTITY)

    def test_receiver_startup_does_not_read_empty_or_populated_message_tables(self) -> None:
        connect = sqlite3.connect
        denied_reads: list[str] = []

        def metadata_only(action: int, table: str, *_: object) -> int:
            if action == sqlite3.SQLITE_READ and table in {
                "telemetry_v2_messages",
                "telemetry_messages",
            }:
                denied_reads.append(table)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        def connect_without_history(*args: object, **kwargs: object) -> sqlite3.Connection:
            connection = connect(*args, **kwargs)
            # Schema validation builds an empty reference schema in memory;
            # forbid historical reads only on the actual database under test.
            if args[0] != ":memory:":
                connection.set_authorizer(metadata_only)
            return connection

        for count in (0, 128):
            if count:
                with open_v2_registry(self.path) as registry:
                    for sequence in range(1, count + 1):
                        message = directory().authorize(
                            body("live-empty", sequence), f"Bearer {LIVE_CREDENTIAL}"
                        )
                        registry.store_authorized(message, received_at=self.now)
            with (
                self.subTest(messages=count),
                patch(
                    "tradinglab.telemetry.sqlite_store_v2.sqlite3.connect",
                    side_effect=connect_without_history,
                ),
            ):
                receiver = PersistentV2TelemetryReceiver(
                    self.path,
                    account_id="account-demo",
                    live_authorization=LIVE_CREDENTIAL,
                    activity_authorization=ACTIVITY_CREDENTIAL,
                )
                try:
                    self.assertEqual(receiver.state()["status"], "ready")
                finally:
                    receiver.close()
        self.assertEqual(denied_reads, [])

    def test_receiver_startup_rejects_missing_roles_even_with_other_account_sources(self) -> None:
        with open_v2_registry(self.path) as registry:
            registry.register_account(
                "incomplete-account", "Incomplete", IDENTITY, created_at=self.now
            )
            registry.register_source(
                "incomplete-live", "incomplete-account", ProducerRole.LIVE, created_at=self.now
            )
        with self.assertRaises(ValueError):
            PersistentV2TelemetryReceiver(
                self.path,
                account_id="incomplete-account",
                live_authorization=LIVE_CREDENTIAL,
                activity_authorization=ACTIVITY_CREDENTIAL,
            )
        with self.assertRaises(V2AuthorizationError):
            PersistentV2TelemetryReceiver(
                self.path,
                account_id="unknown-account",
                live_authorization=LIVE_CREDENTIAL,
                activity_authorization=ACTIVITY_CREDENTIAL,
            )

    def rows(self) -> list[tuple[object, ...]]:
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(
                """SELECT source_id, sequence, payload_json, content_sha256,
                out_of_order, gap_count FROM telemetry_v2_messages
                ORDER BY message_id"""
            ).fetchall()

    def insert_synthetic_cycles(self, count: int) -> tuple[int, int]:
        start_msc = 1704067200000
        step_msc = 8 * 60 * 60 * 1000
        captured = "2026-10-29T12:00:00.000000Z"
        messages: list[tuple[object, ...]] = []
        cycles: list[tuple[object, ...]] = []
        for index in range(count):
            message_id = index + 1
            position_id = str(1_000_000 + index)
            ticket = str(2_000_000 + index)
            magic = ("11122", "22222", "33333")[index % 3]
            last_event = start_msc + index * step_msc
            result = str(index % 11 - 5)
            document = {
                "account_id": "account-demo",
                "position_id": position_id,
                "owner_magic": magic,
                "observed_magics": [magic],
                "started_at_msc": last_event - 60_000,
                "last_event_at_msc": last_event,
                "lifecycle": "closed",
                "remaining_signed_volume": "0",
                "observed_net_result": result,
                "deal_tickets": [ticket],
                "exclusions": [],
            }
            canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
            messages.append(
                (
                    message_id,
                    "synthetic-activity",
                    "multi-year-fixture",
                    str(message_id),
                    f"multi-year-fixture:{message_id}",
                    "activity_batch",
                    captured,
                    captured,
                    "mt5-trading-events-v1",
                    "synthetic-fixture",
                    "{}",
                    "0" * 64,
                    0,
                    0,
                )
            )
            cycles.append(
                (
                    message_id,
                    "account-demo",
                    position_id,
                    magic,
                    last_event - 60_000,
                    last_event,
                    "closed",
                    "0",
                    result,
                    1,
                    json.dumps([magic]),
                    json.dumps([ticket]),
                    "[]",
                    canonical,
                    "synthetic-activity",
                    captured,
                )
            )
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executemany(
                """INSERT INTO telemetry_v2_messages VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                messages,
            )
            connection.executemany(
                "INSERT INTO position_cycle_observations VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                cycles,
            )
            connection.commit()
        return start_msc, start_msc + count * step_msc

    def test_schema_is_shared_exact_and_never_replaces_files(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                CENTRAL_SCHEMA_VERSION,
            )
        with self.assertRaises(FileExistsError):
            create_central_database(self.path)

        other = self.path.with_name("v1.sqlite3")
        create_central_database(other)
        with open_v2_registry(other):
            pass

    def test_multi_year_cycles_are_complete_paginated_and_indexed(self) -> None:
        start_msc, to_msc = self.insert_synthetic_cycles(2500)
        observed: list[str] = []
        cursor = None
        with open_v2_registry(self.path) as registry:
            while True:
                page = registry.position_cycles(
                    "account-demo",
                    from_msc=start_msc,
                    to_msc=to_msc,
                    closed_only=True,
                    ascending=True,
                    include_details=False,
                    limit=500,
                    cursor=cursor,
                )
                observed.extend(item.cycle.position_id for item in page.items)
                cursor = page.next_cursor
                if cursor is None:
                    break

        self.assertEqual(len(observed), 2500)
        self.assertEqual(observed[0], "1000000")
        self.assertEqual(observed[-1], "1002499")
        self.assertGreater((to_msc - start_msc) / 86_400_000, 365 * 2)

        with closing(sqlite3.connect(self.path)) as connection:
            magic_plan = connection.execute(
                """EXPLAIN QUERY PLAN SELECT message_id
                FROM position_cycle_observations
                WHERE account_id = ? AND owner_magic = ? AND last_event_at_msc >= ?
                ORDER BY last_event_at_msc, position_id LIMIT 500""",
                ("account-demo", "11122", start_msc),
            ).fetchall()
            revision_plan = connection.execute(
                """EXPLAIN QUERY PLAN SELECT message_id
                FROM position_cycle_observations
                WHERE account_id = ? AND position_id = ?
                ORDER BY captured_at_utc DESC, message_id DESC LIMIT 1""",
                ("account-demo", "1000000"),
            ).fetchall()
        self.assertIn("position_cycle_observations_magic_query", str(magic_plan))
        self.assertIn("position_cycle_observations_revision", str(revision_plan))

    def test_registration_is_idempotent_but_identity_and_roles_are_immutable(self) -> None:
        with open_v2_registry(self.path) as registry:
            self.assertFalse(
                registry.register_account("account-demo", "Demo", IDENTITY, created_at=self.now)
            )
            self.assertFalse(
                registry.register_source(
                    "synthetic-live",
                    "account-demo",
                    ProducerRole.LIVE,
                    created_at=self.now,
                )
            )
            with self.assertRaises(V2RegistrationConflictError):
                registry.register_account(
                    "account-demo",
                    "Changed",
                    IDENTITY,
                    created_at=self.now,
                )
            with self.assertRaises(V2RegistrationConflictError):
                registry.register_source(
                    "other-live",
                    "account-demo",
                    ProducerRole.LIVE,
                    created_at=self.now,
                )

    def test_retry_survives_reopen_and_preserves_original_reception(self) -> None:
        first_message = authorized("live-empty")
        with open_v2_registry(self.path) as registry:
            first = registry.store_authorized(first_message, received_at=self.now)
        with open_v2_registry(self.path) as registry:
            retry = registry.store_authorized(first_message, received_at=self.now.replace(hour=9))

        self.assertEqual(first.disposition, AdmissionDisposition.ACCEPTED)
        self.assertEqual(retry.disposition, AdmissionDisposition.DUPLICATE)
        self.assertEqual(first.message_id, retry.message_id)
        with closing(sqlite3.connect(self.path)) as connection:
            received = connection.execute(
                "SELECT received_at_utc FROM telemetry_v2_messages"
            ).fetchone()[0]
        self.assertEqual(received, "2026-10-22T08:30:00.000000Z")

    def test_conflict_rolls_back_and_next_sequence_remains_usable(self) -> None:
        original = authorized("live-empty")
        changed = fixture("live-empty")
        changed["captured_at"] = "2026-10-22T08:00:02Z"
        conflict = directory().authorize(json.dumps(changed).encode(), f"Bearer {LIVE_CREDENTIAL}")
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(original, received_at=self.now)
            with self.assertRaises(V2ConflictError):
                registry.store_authorized(conflict, received_at=self.now)
            registry.store_authorized(authorized("live-empty", 2), received_at=self.now)
        self.assertEqual(len(self.rows()), 2)

    def test_strict_live_and_durable_out_of_order_activity(self) -> None:
        with open_v2_registry(self.path) as registry:
            live = registry.store_authorized(authorized("live-empty", 3), received_at=self.now)
            activity = registry.store_authorized(
                authorized("activity-canceled-order", 3), received_at=self.now
            )
        self.assertEqual(live.sequence_gap, 2)
        self.assertEqual(activity.sequence_gap, 2)

        with open_v2_registry(self.path) as registry:
            with self.assertRaises(V2StaleSequenceError):
                registry.store_authorized(authorized("live-empty", 1), received_at=self.now)
            recovered = registry.store_authorized(
                authorized("activity-canceled-order", 1), received_at=self.now
            )
        self.assertTrue(recovered.out_of_order)
        self.assertEqual(recovered.sequence_gap, 0)
        self.assertEqual(len(self.rows()), 3)

    def test_storage_rechecks_authorized_account_role_and_mutable_payload(self) -> None:
        valid = authorized("live-empty")
        forged_account = AuthorizedEnvelope("other-account", valid.role, valid.envelope)
        with open_v2_registry(self.path) as registry:
            with self.assertRaises(V2AuthorizationError):
                registry.store_authorized(forged_account, received_at=self.now)

        valid.envelope.payload["identity"]["server"] = "OTHER"
        with open_v2_registry(self.path) as registry:
            with self.assertRaises(V2AuthorizationError):
                registry.store_authorized(valid, received_at=self.now)
        self.assertEqual(self.rows(), [])

    def test_concurrent_retry_commits_once(self) -> None:
        barrier = threading.Barrier(2, timeout=5)
        message = authorized("activity-canceled-order")

        def store() -> AdmissionDisposition:
            with open_v2_registry(self.path) as registry:
                barrier.wait()
                return registry.store_authorized(message, received_at=self.now).disposition

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [executor.submit(store) for _ in range(2)]
            dispositions = [result.result(timeout=10) for result in results]
        self.assertCountEqual(
            dispositions,
            [AdmissionDisposition.ACCEPTED, AdmissionDisposition.DUPLICATE],
        )
        self.assertEqual(len(self.rows()), 1)

    def test_retry_resolves_failures_before_and_after_commit(self) -> None:
        for after_commit in (False, True):
            with self.subTest(after_commit=after_commit):
                path = self.path.with_name(f"commit-{after_commit}.sqlite3")
                create_central_database(path)
                with open_v2_registry(path) as registry:
                    registry.register_account("account-demo", "Demo", IDENTITY, created_at=self.now)
                    registry.register_source(
                        "synthetic-live",
                        "account-demo",
                        ProducerRole.LIVE,
                        created_at=self.now,
                    )
                with closing(sqlite3.connect(path, factory=FailingCommitConnection)) as connection:
                    connection.after_commit = after_commit
                    connection.execute("PRAGMA foreign_keys = ON")
                    registry = V2TelemetryRegistry(connection)
                    with self.assertRaises(V2StorageError):
                        registry.store_authorized(authorized("live-empty"), received_at=self.now)
                with open_v2_registry(path) as registry:
                    retry = registry.store_authorized(
                        authorized("live-empty"), received_at=self.now
                    )
                self.assertEqual(
                    retry.disposition,
                    AdmissionDisposition.DUPLICATE
                    if after_commit
                    else AdmissionDisposition.ACCEPTED,
                )

    def test_tampered_schema_is_rejected_before_use(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TABLE unexpected(value TEXT) STRICT")
            connection.commit()
        with self.assertRaises(V2StorageError):
            with open_v2_registry(self.path):
                pass

    def test_account_messages_restore_verified_consistent_evidence(self) -> None:
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(authorized("live-empty"), received_at=self.now)
            registry.store_authorized(authorized("activity-canceled-order"), received_at=self.now)
            with self.assertRaises(V2AuthorizationError):
                registry.account_messages("unknown-account")
            restored = registry.account_messages("account-demo")

        self.assertEqual(len(restored), 2)
        self.assertEqual(
            [message.role for message in restored],
            [ProducerRole.LIVE, ProducerRole.ACTIVITY],
        )
        self.assertEqual(restored[0].account_id, "account-demo")
        self.assertEqual(restored[0].received_at, self.now)

    def test_account_messages_detect_tampered_durable_content(self) -> None:
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(authorized("live-empty"), received_at=self.now)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("UPDATE telemetry_v2_messages SET content_sha256 = ?", ("0" * 64,))
            connection.commit()

        with open_v2_registry(self.path) as registry:
            self.assertEqual(registry.account_registration("account-demo").identity, IDENTITY)
            with self.assertRaises(V2StorageError):
                registry.account_messages("account-demo")

    def test_registered_account_composes_after_durable_round_trip(self) -> None:
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(authorized("live-empty"), received_at=self.now)
            registry.store_authorized(authorized("activity-canceled-order"), received_at=self.now)
        with open_v2_registry(self.path) as registry:
            result = compose_account(registry.account_evidence("account-demo"))

        self.assertEqual(result.live.payload["account"]["balance"], 10000)
        self.assertEqual(result.orders[0].ticket, "900000000000000001")
        self.assertEqual(result.activity_flow.source_id, "synthetic-activity")

    def test_activity_projection_is_atomic_idempotent_and_queryable(self) -> None:
        message = authorized("activity-canceled-order")
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(message, received_at=self.now)
            registry.store_authorized(message, received_at=self.now.replace(hour=9))
        with open_v2_registry(self.path, read_only=True) as registry:
            page = registry.activity_page(
                "account-demo",
                "order",
                from_msc=1792656000000,
                to_msc=1792656060001,
                magic_number="11122",
            )
            coverage = registry.coverage_report(
                "account-demo",
                "order",
                from_msc=1792656000000,
                to_msc=1792656060001,
            )

        self.assertEqual([item.ticket for item in page.items], ["900000000000000001"])
        self.assertEqual(page.items[0].values["state"], 2)
        self.assertIsNone(page.next_cursor)
        self.assertEqual(
            coverage.complete_ranges,
            (("1792656000000", "1792656060000"),),
        )
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM activity_observations").fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM activity_coverage").fetchone()[0],
                2,
            )

    def test_activity_query_paginates_uint64_tickets_without_loading_account(self) -> None:
        document = fixture("activity-truncated")
        first = document["payload"]["deals"]["items"][0]
        second = dict(first)
        second["ticket"] = "99"
        second["time_msc"] = "1792656020000"
        document["payload"]["deals"] = {
            "status": "complete",
            "total": 2,
            "items": [first, second],
        }
        message = directory().authorize(
            json.dumps(document).encode(), f"Bearer {ACTIVITY_CREDENTIAL}"
        )
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(message, received_at=self.now)
            first_page = registry.activity_page(
                "account-demo",
                "deal",
                from_msc=1792656000000,
                to_msc=1792656060001,
                limit=1,
            )
            second_page = registry.activity_page(
                "account-demo",
                "deal",
                from_msc=1792656000000,
                to_msc=1792656060001,
                limit=1,
                cursor=first_page.next_cursor,
            )

        self.assertEqual(first_page.items[0].ticket, "900000000000000002")
        self.assertIsNotNone(first_page.next_cursor)
        self.assertEqual(second_page.items[0].ticket, "99")
        self.assertIsNone(second_page.next_cursor)

    def test_truncated_batch_does_not_claim_complete_coverage(self) -> None:
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(authorized("activity-truncated"), received_at=self.now)
            deals = registry.coverage_report(
                "account-demo",
                "deal",
                from_msc=1792656000000,
                to_msc=1792656060001,
            )
            orders = registry.coverage_report(
                "account-demo",
                "order",
                from_msc=1792656000000,
                to_msc=1792656060001,
            )

        self.assertEqual(deals.complete_ranges, ())
        self.assertEqual(deals.incomplete_batches, 1)
        self.assertEqual(orders.incomplete_batches, 0)

    def test_paged_activity_claims_coverage_only_after_durable_chain(self) -> None:
        first = authorized_page(
            10,
            ticket="900000000000000002",
            time_msc="1792656030000",
            after_time="0",
            after_ticket="0",
            has_more=True,
        )
        final = authorized_page(
            11,
            ticket="900000000000000003",
            time_msc="1792656030000",
            after_time="1792656030000",
            after_ticket="900000000000000002",
            has_more=False,
        )
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(first, received_at=self.now)
            before = registry.coverage_report(
                "account-demo", "deal", from_msc=1792656000000, to_msc=1792656060001
            )
        with open_v2_registry(self.path) as registry:
            duplicate = registry.store_authorized(first, received_at=self.now)
            self.assertEqual(duplicate.disposition, AdmissionDisposition.DUPLICATE)
            registry.store_authorized(final, received_at=self.now)
            after = registry.coverage_report(
                "account-demo", "deal", from_msc=1792656000000, to_msc=1792656060001
            )
            deals = registry.activity_page(
                "account-demo", "deal", from_msc=1792656000000, to_msc=1792656060001
            )

        self.assertEqual(before.complete_ranges, ())
        self.assertEqual(before.incomplete_batches, 0)
        self.assertEqual(after.complete_ranges, (("1792656000000", "1792656060000"),))
        self.assertEqual(
            {item.ticket for item in deals.items},
            {
                "900000000000000002",
                "900000000000000003",
            },
        )

    def test_final_page_without_durable_prefix_rolls_back(self) -> None:
        final = authorized_page(
            12,
            ticket="900000000000000003",
            time_msc="1792656030000",
            after_time="1792656030000",
            after_ticket="900000000000000002",
            has_more=False,
        )
        with open_v2_registry(self.path) as registry:
            with self.assertRaises(V2StorageError):
                registry.store_authorized(final, received_at=self.now)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM telemetry_v2_messages").fetchone()[0],
                0,
            )

    def _store_two_page_chain(self) -> None:
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(
                authorized_page(
                    10,
                    ticket="18446744073709551614",
                    time_msc="1792656030000",
                    after_time="0",
                    after_ticket="0",
                    has_more=True,
                ),
                received_at=self.now,
            )
            registry.store_authorized(
                authorized_page(
                    11,
                    ticket="18446744073709551615",
                    time_msc="1792656030000",
                    after_time="1792656030000",
                    after_ticket="18446744073709551614",
                    has_more=False,
                ),
                received_at=self.now,
            )

    def test_chain_query_decodes_only_page_links_and_preserves_uint64_tickets(self) -> None:
        self._store_two_page_chain()
        original_loads = json.loads

        def compact_page(encoded: str) -> dict[str, object]:
            page = original_loads(encoded)
            self.assertEqual(set(page), {"snapshot_id", "after", "through", "has_more"})
            return page

        with (
            closing(sqlite3.connect(self.path)) as connection,
            patch(
                "tradinglab.telemetry.sqlite_store_v2.json.loads", side_effect=compact_page
            ) as decode,
        ):
            self.assertTrue(
                V2TelemetryRegistry._has_complete_pagination_chain(
                    connection,
                    "account-demo",
                    "synthetic-activity",
                    1792656000000,
                    1792656060000,
                    "p:1792656000000:1792656060000:2:0",
                    2,
                    0,
                )
            )
            self.assertEqual(decode.call_count, 2)

    def test_chain_query_scopes_identity_window_snapshot_and_totals(self) -> None:
        self._store_two_page_chain()
        selection = {
            "account_id": "account-demo",
            "source_id": "synthetic-activity",
            "from_msc": 1792656000000,
            "to_msc": 1792656060000,
            "snapshot_id": "p:1792656000000:1792656060000:2:0",
            "deal_total": 2,
            "order_total": 0,
        }
        with closing(sqlite3.connect(self.path)) as connection:
            for changes in (
                {"account_id": "other-account"},
                {"source_id": "synthetic-live"},
                {"from_msc": 1792656000001},
                {"to_msc": 1792656060001},
                {"snapshot_id": "other-snapshot"},
                {"deal_total": 3},
                {"order_total": 1},
            ):
                with self.subTest(changes=changes):
                    self.assertFalse(
                        V2TelemetryRegistry._has_complete_pagination_chain(
                            connection, **(selection | changes)
                        )
                    )

    def test_final_page_with_incompatible_prefix_totals_rolls_back(self) -> None:
        for index, totals in enumerate(({"deal_total": 3}, {"order_total": 1})):
            with self.subTest(totals=totals), open_v2_registry(self.path) as registry:
                snapshot = f"incompatible-{index}"
                registry.store_authorized(
                    authorized_page(
                        20 + index * 2,
                        ticket="1",
                        time_msc="1792656030000",
                        after_time="0",
                        after_ticket="0",
                        has_more=True,
                        snapshot_id=snapshot,
                        **totals,
                    ),
                    received_at=self.now,
                )
                with self.assertRaises(V2StorageError):
                    registry.store_authorized(
                        authorized_page(
                            21 + index * 2,
                            ticket="2",
                            time_msc="1792656030000",
                            after_time="1792656030000",
                            after_ticket="1",
                            has_more=False,
                            snapshot_id=snapshot,
                        ),
                        received_at=self.now,
                    )
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM telemetry_v2_messages").fetchone()[0], 2
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM activity_coverage").fetchone()[0], 0
            )

    def test_final_page_cannot_bridge_a_gap_in_durable_chain(self) -> None:
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(
                authorized_page(
                    10,
                    ticket="1",
                    time_msc="1792656030000",
                    after_time="0",
                    after_ticket="0",
                    has_more=True,
                ),
                received_at=self.now,
            )
            with self.assertRaises(V2StorageError):
                registry.store_authorized(
                    authorized_page(
                        11,
                        ticket="3",
                        time_msc="1792656030000",
                        after_time="1792656030000",
                        after_ticket="2",
                        has_more=False,
                    ),
                    received_at=self.now,
                )

    def test_more_than_twelve_months_survives_restart_without_retention_cutoff(self) -> None:
        old_at = datetime(2025, 8, 1, 12, tzinfo=UTC)
        recent_at = datetime(2026, 10, 20, 12, tzinfo=UTC)
        old = authorized_order_observation(1, ticket="800000000000000001", done_at=old_at)
        recent = authorized_order_observation(2, ticket="800000000000000002", done_at=recent_at)
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(old, received_at=self.now)
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(recent, received_at=self.now)
            page = registry.activity_page(
                "account-demo",
                "order",
                from_msc=int(old_at.timestamp() * 1000) - 60_000,
                to_msc=int(recent_at.timestamp() * 1000) + 60_000,
            )

        self.assertGreater((recent_at - old_at).days, 365)
        self.assertEqual(
            {item.ticket for item in page.items},
            {"800000000000000001", "800000000000000002"},
        )

    def test_position_reconcile_is_durable_without_claiming_account_range(self) -> None:
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(
                authorized("activity-position-reconcile"), received_at=self.now
            )
            deals = registry.activity_page(
                "account-demo",
                "deal",
                from_msc=1792569600000,
                to_msc=1792656060001,
            )
            cycles = registry.position_cycles("account-demo")
            filtered_cycles = registry.position_cycles("account-demo", owner_magic="11122")
            multi_filtered = registry.position_cycles(
                "account-demo", owner_magics=("11122", "99999")
            )
            ranged_cycles = registry.position_cycles(
                "account-demo",
                from_msc=1792656000000,
                to_msc=1792656060001,
                closed_only=True,
            )
            outside_range = registry.position_cycles(
                "account-demo",
                from_msc=1792656060001,
                to_msc=1792656120001,
                closed_only=True,
            )
            other_cycles = registry.position_cycles("account-demo", owner_magic="99999")
            discovered_magics = registry.position_cycle_magics("account-demo")
            coverage = registry.coverage_report(
                "account-demo",
                "deal",
                from_msc=1792569600000,
                to_msc=1792656060001,
            )

        self.assertEqual(len(deals.items), 2)
        self.assertEqual(coverage.complete_ranges, ())
        self.assertEqual(coverage.incomplete_batches, 0)
        self.assertEqual(len(cycles.items), 1)
        self.assertEqual(filtered_cycles.items, cycles.items)
        self.assertEqual(multi_filtered.items, cycles.items)
        self.assertEqual(ranged_cycles.items, cycles.items)
        self.assertEqual(outside_range.items, ())
        self.assertEqual(other_cycles.items, ())
        self.assertEqual(discovered_magics, ("11122",))
        self.assertIsNone(cycles.next_cursor)
        cycle = cycles.items[0].cycle
        self.assertEqual(cycle.position_id, "600000000000000001")
        self.assertEqual(cycle.owner_magic, "11122")
        self.assertEqual(cycle.observed_net_result, Decimal("9.8"))
        self.assertEqual(cycle.deal_tickets, ("700000000000000001", "700000000000000002"))
        self.assertTrue(cycle.eligible_for_autonomous_metrics)
        with self.assertRaisesRegex(ValueError, "período"):
            with open_v2_registry(self.path) as registry:
                registry.position_cycles("account-demo", from_msc=1792656000000)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM activity_coverage").fetchone()[0], 0
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM activity_observations").fetchone()[0], 4
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM position_cycle_observations").fetchone()[
                    0
                ],
                1,
            )

    def test_position_cycles_use_stable_keyset_pagination(self) -> None:
        second = fixture("activity-position-reconcile")
        second["sequence"] = 6
        second["event_id"] = "synthetic-session-1:6"
        position_id = "600000000000000003"
        for index, row in enumerate(second["payload"]["deals"]["items"]):
            row["ticket"] = str(700000000000000003 + index)
            row["order_id"] = str(600000000000000003 + index)
            row["position_id"] = position_id
        for index, row in enumerate(second["payload"]["orders"]["items"]):
            row["ticket"] = str(600000000000000003 + index)
            row["position_id"] = position_id
        second_authorized = directory().authorize(
            json.dumps(second).encode(),
            f"Bearer {ACTIVITY_CREDENTIAL}",
        )

        with open_v2_registry(self.path) as registry:
            registry.store_authorized(
                authorized("activity-position-reconcile"), received_at=self.now
            )
            registry.store_authorized(second_authorized, received_at=self.now)
            first = registry.position_cycles("account-demo", limit=1)
            following = registry.position_cycles(
                "account-demo",
                limit=1,
                cursor=first.next_cursor,
            )
            oldest = registry.position_cycles("account-demo", ascending=True, limit=1)
            newer = registry.position_cycles(
                "account-demo",
                ascending=True,
                limit=1,
                cursor=oldest.next_cursor,
            )

        self.assertEqual(first.items[0].cycle.position_id, position_id)
        self.assertIsNotNone(first.next_cursor)
        self.assertEqual(following.items[0].cycle.position_id, "600000000000000001")
        self.assertIsNone(following.next_cursor)
        self.assertEqual(oldest.items[0].cycle.position_id, "600000000000000001")
        self.assertEqual(newer.items[0].cycle.position_id, position_id)
        self.assertIsNone(newer.next_cursor)

    def test_newer_conflict_preserves_last_unambiguous_order(self) -> None:
        def observation(session: str, captured: str, price: int) -> AuthorizedEnvelope:
            document = fixture("activity-canceled-order")
            document["session_id"] = session
            document["event_id"] = f"{session}:1"
            document["captured_at"] = captured
            document["payload"]["orders"]["items"][0]["price_open"] = price
            return directory().authorize(
                json.dumps(document).encode(), f"Bearer {ACTIVITY_CREDENTIAL}"
            )

        with open_v2_registry(self.path) as registry:
            registry.store_authorized(
                observation("older", "2026-10-22T08:00:00Z", 4200),
                received_at=self.now,
            )
            registry.store_authorized(
                observation("new-a", "2026-10-22T08:00:02Z", 4201),
                received_at=self.now,
            )
            registry.store_authorized(
                observation("new-b", "2026-10-22T08:00:02Z", 4202),
                received_at=self.now,
            )
            page = registry.activity_page(
                "account-demo",
                "order",
                from_msc=1792656000000,
                to_msc=1792656060001,
            )

        self.assertEqual(page.items[0].values["price_open"], 4200)
        self.assertEqual(page.items[0].conflict_at, "2026-10-22T08:00:02.000000Z")


if __name__ == "__main__":
    unittest.main()

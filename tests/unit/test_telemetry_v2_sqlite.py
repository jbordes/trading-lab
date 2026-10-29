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

from tradinglab.telemetry.admission_v2 import (
    AdmissionDisposition,
    AuthorizedEnvelope,
    ProducerIdentity,
    ProducerRegistration,
    ProducerRole,
    V2AuthorizationError,
    V2ConflictError,
    V2ProducerDirectory,
    V2StaleSequenceError,
)
from tradinglab.telemetry.composition_v2 import compose_account
from tradinglab.telemetry.sqlite_store import create_database
from tradinglab.telemetry.sqlite_store_v2 import (
    DATABASE_SCHEMA_VERSION,
    V2RegistrationConflictError,
    V2StorageError,
    V2TelemetryRegistry,
    create_v2_database,
    migrate_v2_database_v3_to_v4,
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


def authorized(name: str, sequence: int | None = None) -> AuthorizedEnvelope:
    credential = ACTIVITY_CREDENTIAL if name.startswith("activity-") else LIVE_CREDENTIAL
    return directory().authorize(body(name, sequence), f"Bearer {credential}")


def authorized_page(
    sequence: int,
    *,
    ticket: str,
    time_msc: str,
    after_time: str,
    after_ticket: str,
    has_more: bool,
) -> AuthorizedEnvelope:
    value = fixture("activity-truncated")
    value["sequence"] = sequence
    value["event_id"] = f"synthetic-session-1:{sequence}"
    deal = value["payload"]["deals"]["items"][0]
    deal["ticket"] = ticket
    deal["time_msc"] = time_msc
    status = "partial" if has_more else "paged_complete"
    value["payload"]["deals"] = {"status": status, "total": 2, "items": [deal]}
    value["payload"]["orders"] = {"status": status, "total": 0, "items": []}
    value["payload"]["pagination"] = {
        "snapshot_id": "p:1792656000000:1792656060000:2:0",
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
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "telemetry-v2.sqlite3"
        self.now = datetime(2026, 10, 22, 8, 30, tzinfo=UTC)
        create_v2_database(self.path)
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

    def rows(self) -> list[tuple[object, ...]]:
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(
                """SELECT source_id, sequence, payload_json, content_sha256,
                out_of_order, gap_count FROM telemetry_v2_messages
                ORDER BY message_id"""
            ).fetchall()

    def test_schema_is_isolated_exact_and_never_replaces_files(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                DATABASE_SCHEMA_VERSION,
            )
        with self.assertRaises(FileExistsError):
            create_v2_database(self.path)

        other = self.path.with_name("v1.sqlite3")
        create_database(other)
        with self.assertRaises(V2StorageError):
            with open_v2_registry(other):
                pass

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
                create_v2_database(path)
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
        self.assertEqual(other_cycles.items, ())
        self.assertEqual(discovered_magics, ("11122",))
        self.assertIsNone(cycles.next_cursor)
        cycle = cycles.items[0].cycle
        self.assertEqual(cycle.position_id, "600000000000000001")
        self.assertEqual(cycle.owner_magic, "11122")
        self.assertEqual(cycle.observed_net_result, Decimal("9.8"))
        self.assertEqual(cycle.deal_tickets, ("700000000000000001", "700000000000000002"))
        self.assertTrue(cycle.eligible_for_autonomous_metrics)
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

    def test_v3_migration_creates_verified_backup_and_backfills_cycles(self) -> None:
        with open_v2_registry(self.path) as registry:
            registry.store_authorized(
                authorized("activity-position-reconcile"), received_at=self.now
            )
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DROP INDEX position_cycle_observations_query")
            connection.execute("DROP TABLE position_cycle_observations")
            connection.execute("PRAGMA user_version = 3")

        backup = self.path.with_name("telemetry-v2-before-v4.sqlite3")
        self.assertEqual(migrate_v2_database_v3_to_v4(self.path, backup), 1)

        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = 'position_cycle_observations'"
                ).fetchone()
            )
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone(), ("ok",))
        with open_v2_registry(self.path) as registry:
            cycles = registry.position_cycles("account-demo")
        self.assertEqual(len(cycles.items), 1)
        self.assertEqual(cycles.items[0].cycle.position_id, "600000000000000001")

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

        self.assertEqual(first.items[0].cycle.position_id, position_id)
        self.assertIsNotNone(first.next_cursor)
        self.assertEqual(following.items[0].cycle.position_id, "600000000000000001")
        self.assertIsNone(following.next_cursor)

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

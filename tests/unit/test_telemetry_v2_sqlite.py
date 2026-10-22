from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
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
from tradinglab.telemetry.sqlite_store import create_database
from tradinglab.telemetry.sqlite_store_v2 import (
    DATABASE_SCHEMA_VERSION,
    V2RegistrationConflictError,
    V2StorageError,
    create_v2_database,
    open_v2_registry,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "telemetry_v2"
IDENTITY = ProducerIdentity("****1234", "DEMO-SERVER", "USD")
LIVE_CREDENTIAL = "synthetic-live-credential-safe-length"
ACTIVITY_CREDENTIAL = "synthetic-activity-credential-safe-length"


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

    def test_tampered_schema_is_rejected_before_use(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TABLE unexpected(value TEXT) STRICT")
            connection.commit()
        with self.assertRaises(V2StorageError):
            with open_v2_registry(self.path):
                pass


if __name__ == "__main__":
    unittest.main()

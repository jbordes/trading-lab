from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import closing
from datetime import UTC, date, datetime
from unittest.mock import patch

import test_central_api as central_fixture
import test_daily_account_store as daily_fixture
from test_mt5_telemetry import encoded, snapshot_message

from tradinglab.telemetry.account_sample_retention import compact_account_samples
from tradinglab.telemetry.sqlite_store import (
    MessageConflictError,
    MessageStaleError,
    TelemetryStorageError,
    open_registry,
)

DAY = daily_fixture.DAY


class AccountSampleRetentionTest(unittest.TestCase):
    def setUp(self) -> None:
        daily_fixture.DailyAccountStoreTest.setUp(self)

    add = daily_fixture.DailyAccountStoreTest.add
    read_daily = daily_fixture.DailyAccountStoreTest.read_daily
    consolidate = daily_fixture.DailyAccountStoreTest.consolidate

    def compact(self, **overrides):
        arguments = {
            "account_id": "test-account",
            "broker_day": DAY,
            "current_broker_day": date(2026, 10, 25),
        }
        arguments.update(overrides)
        return compact_account_samples(self.path, **arguments)

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(
                "SELECT message_id, sequence, payload_json, content_sha256, "
                "compacted_broker_day FROM telemetry_messages ORDER BY message_id"
            ).fetchall()

    def test_preview_changes_neither_samples_nor_summary(self) -> None:
        self.add(1, 10, 120)
        self.add(2, 21, 90)
        before = self.rows()
        result = self.compact()
        self.assertEqual((result["eligible"], result["compacted"]), (1, 0))
        self.assertGreater(result["payload_bytes_releasable"], 0)
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.read_daily(), [])

    def test_compaction_preserves_close_current_state_identity_and_replay(self) -> None:
        raw = self.add(1, 10, 120)
        self.add(2, 21, 90)
        before = self.rows()
        result = self.compact(apply=True)
        self.assertEqual(result["compacted"], 1)
        after = self.rows()
        self.assertEqual(after[0][0:2], before[0][0:2])
        self.assertEqual(after[0][2:], ("null", before[0][3], DAY.isoformat()))
        self.assertEqual(after[1], before[1])
        with open_registry(self.path) as registry:
            duplicate = registry.store_message(raw, received_at=datetime.now(UTC))
            self.assertTrue(duplicate.duplicate)
            self.assertEqual(duplicate.message_id, before[0][0])
            self.assertEqual(
                registry.latest_account_snapshot("demo-terminal-01").envelope.payload["account"][
                    "balance"
                ],
                90,
            )
            history = registry.account_history(
                "demo-terminal-01",
                from_msc=int(datetime(2026, 10, 15, tzinfo=UTC).timestamp() * 1000),
                to_msc=int(datetime(2026, 10, 16, tzinfo=UTC).timestamp() * 1000),
            )
            self.assertEqual([point["balance"] for point in history["points"]], [90])
        self.assertEqual(self.compact(apply=True)["compacted"], 0)
        self.assertEqual(self.rows(), after)

    def test_reused_identity_with_changed_content_still_conflicts(self) -> None:
        raw = self.add(1, 10, 120)
        self.add(2, 21, 90)
        self.compact(apply=True)
        message = json.loads(raw)
        message["payload"]["account"]["balance"] = 999
        with open_registry(self.path) as registry, self.assertRaises(MessageConflictError):
            registry.store_message(encoded(message), received_at=datetime.now(UTC))

    def test_old_unknown_sequences_remain_rejected(self) -> None:
        raw = self.add(1, 10, 120)
        self.add(3, 21, 90)
        self.compact(apply=True)
        message = json.loads(raw)
        message["sequence"] = 2
        message["event_id"] = message["session_id"] + ":2"
        with open_registry(self.path) as registry, self.assertRaises(MessageStaleError):
            registry.store_message(encoded(message), received_at=datetime.now(UTC))

    def test_batches_and_late_captures_preserve_old_extrema_and_first_time(self) -> None:
        self.add(1, 3, 150)
        self.add(2, 8, 130)
        self.add(3, 20, 90)
        self.assertTrue(self.compact(apply=True, max_messages=1)["more_pending"])
        self.assertFalse(self.compact(apply=True, max_messages=1)["more_pending"])
        before = self.consolidate()
        self.assertEqual(before.max_balance, 150)
        self.add(4, 21, 95)
        self.compact(apply=True)
        after = self.consolidate()
        self.assertEqual(after.close.balance, 95)
        self.assertEqual(after.max_balance, 150)
        self.assertEqual(after.min_balance, 90)
        self.assertEqual(after.first_captured_at_utc, before.first_captured_at_utc)

    def test_seven_recent_broker_dates_are_protected(self) -> None:
        self.add(1, 10, 120)
        self.add(2, 21, 90)
        before = self.rows()
        # Oct 15 through Oct 21 are the seven recent broker dates.
        with self.assertRaises(ValueError):
            self.compact(apply=True, current_broker_day=date(2026, 10, 21))
        self.assertEqual(self.rows(), before)
        self.assertEqual(
            self.compact(apply=True, current_broker_day=date(2026, 10, 22))["compacted"], 1
        )

    def test_missing_broker_clock_and_embedded_history_are_preserved(self) -> None:
        raw = self.add(1, 8, 120)
        self.add(2, 10, 110, marker=False)
        self.add(3, 21, 90)
        # Add an independent capture with historical deals: never discard it.
        message = json.loads(raw)
        message["session_id"] = "history-session"
        message["event_id"] = "history-session:1"
        message["payload"]["history"] = {
            "status": "complete",
            "from_server_seconds": "0",
            "to_server_seconds": "100",
            "total": 0,
            "deals": [],
        }
        with open_registry(self.path) as registry:
            registry.store_message(encoded(message), received_at=datetime.now(UTC))
        self.assertEqual(self.compact(apply=True)["compacted"], 1)
        rows = self.rows()
        self.assertEqual([row[4] for row in rows], [DAY.isoformat(), None, None, None])

    def test_failed_compaction_rolls_back_new_summary_and_all_payloads(self) -> None:
        self.add(1, 10, 120)
        self.add(2, 21, 90)
        before = self.rows()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TRIGGER fail_compaction BEFORE UPDATE ON telemetry_messages "
                "BEGIN SELECT RAISE(ABORT, 'test failure'); END;"
            )
        # Fault-injection trigger is deliberately outside the accepted schema.
        with (
            patch("tradinglab.telemetry.account_sample_retention.validate_central_schema"),
            self.assertRaises(TelemetryStorageError),
        ):
            self.compact(apply=True)
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.read_daily(), [])

    def test_invalid_batch_limits_and_other_accounts_cannot_compact(self) -> None:
        self.add(1, 10, 120)
        for limit in (True, 0, -1, 1001):
            with self.assertRaises(ValueError):
                self.compact(apply=True, max_messages=limit)
        with self.assertRaises(TelemetryStorageError):
            self.compact(apply=True, account_id="other-account")
        self.assertIsNone(self.rows()[0][4])


class AccountSampleRetentionApiTest(unittest.TestCase):
    def setUp(self) -> None:
        central_fixture.CentralApiTest.setUp(self)

    def test_retry_over_http_keeps_ack_after_payload_compaction(self) -> None:
        headers = {"Authorization": f"Bearer {self.settings.snapshot_ingest}"}
        bodies = []
        for sequence, hour in ((1, 10), (2, 21)):
            message = snapshot_message(sequence=sequence)
            captured = datetime(2026, 10, 15, hour, tzinfo=UTC)
            message["captured_at"] = captured.isoformat().replace("+00:00", "Z")
            message["payload"]["server_time_msc"] = str(int(captured.timestamp() * 1000) + 7200000)
            bodies.append(message)
            response = self.client.post("/api/account-state", json=message, headers=headers)
            self.assertEqual(response.status_code, 202, response.text)
        compact_account_samples(
            self.settings.database,
            account_id="demo",
            broker_day=DAY,
            current_broker_day=date(2026, 10, 25),
            apply=True,
        )
        response = self.client.post("/api/account-state", json=bodies[0], headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        bodies[0]["payload"]["account"]["balance"] = 999
        response = self.client.post("/api/account-state", json=bodies[0], headers=headers)
        self.assertEqual(response.status_code, 409, response.text)

from __future__ import annotations

import io
import json
import sqlite3
import unittest
from contextlib import closing
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import test_central_api as central_fixture
import test_daily_account_store as daily_fixture
from test_mt5_telemetry import encoded, snapshot_message

from tradinglab.dashboard.snapshot import DashboardReadError
from tradinglab.dashboard.telemetry import LoopbackTelemetryClient
from tradinglab.telemetry.account_evolution import read_account_evolution
from tradinglab.telemetry.account_sample_retention import compact_account_samples
from tradinglab.telemetry.daily_account_store import persist_daily_account_history
from tradinglab.telemetry.sqlite_store import TelemetryStorageError, open_registry


def at(day: int, hour: int = 0) -> int:
    return int(datetime(2026, 10, day, hour, tzinfo=UTC).timestamp() * 1000)


def message(sequence: int, day: int, hour: int, *, marker: bool = True) -> dict:
    result = snapshot_message(sequence=sequence)
    result["captured_at"] = (
        datetime(2026, 10, day, hour, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    )
    result["payload"]["account"]["balance"] = 100 + sequence
    if marker:
        result["payload"]["server_time_msc"] = str(at(day, hour) + 7200000)
    return result


class AccountEvolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        daily_fixture.DailyAccountStoreTest.setUp(self)

    def store(self, sequence: int, day: int, hour: int, *, marker: bool = True) -> None:
        raw = message(sequence, day, hour, marker=marker)
        with open_registry(self.path) as registry:
            registry.store_message(
                encoded(raw), received_at=datetime(2026, 10, day, hour, tzinfo=UTC)
            )

    def close_day(self, day: int) -> None:
        persist_daily_account_history(
            self.path,
            account_id="test-account",
            broker_day=date(2026, 10, day),
            current_broker_day=date(2026, 10, 25),
        )

    def read(self, start=None, end=None):
        return read_account_evolution(
            self.path,
            "demo-terminal-01",
            from_msc=start if start is not None else at(14),
            to_msc=end if end is not None else at(17),
        )

    def test_combines_daily_close_and_latest_day_without_duplicates(self) -> None:
        self.store(1, 15, 8)
        self.store(2, 15, 21)
        self.close_day(15)
        self.store(3, 16, 8)
        self.store(4, 16, 10)
        result = self.read()
        self.assertEqual([p["resolution"] for p in result["points"]], ["daily", "recent", "recent"])
        self.assertEqual([p["balance"] for p in result["points"]], [102, 103, 104])
        self.assertEqual(result["points"][0]["broker_time"], "2026-10-15T23:00:00")
        self.assertFalse(result["unconsolidated_history"])
        self.assertEqual(result["recent_basis"], "broker_day")

    def test_compaction_changes_neither_daily_nor_recent_values(self) -> None:
        self.store(1, 15, 8)
        self.store(2, 15, 21)
        self.close_day(15)
        self.store(3, 16, 10)
        before = self.read()
        compact_account_samples(
            self.path,
            account_id="test-account",
            broker_day=date(2026, 10, 15),
            current_broker_day=date(2026, 10, 25),
            apply=True,
        )
        self.assertEqual(self.read(), before)

    def test_unconsolidated_older_days_are_reported_not_fabricated_or_written(self) -> None:
        self.store(1, 14, 8)
        self.store(2, 16, 10)
        result = self.read()
        self.assertTrue(result["unconsolidated_history"])
        self.assertEqual(len(result["points"]), 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM account_daily_observations").fetchone()[0], 0
            )

    def test_missing_broker_clock_uses_explicit_recent_fallback(self) -> None:
        self.store(1, 15, 8, marker=False)
        self.store(2, 16, 10, marker=False)
        result = self.read()
        self.assertEqual(result["recent_basis"], "last_24h_unassigned")
        self.assertTrue(result["unconsolidated_history"])
        self.assertIsNone(result["points"][0]["broker_day"])

    def test_daily_only_empty_windows_and_exclusive_end(self) -> None:
        self.store(1, 15, 21)
        self.close_day(15)
        self.assertEqual(self.read(end=at(15, 21))["points"], [])
        result = self.read(end=at(16))
        self.assertEqual(len(result["points"]), 1)
        self.assertEqual(result["recent_basis"], "none")
        self.assertEqual(self.read(start=at(16), end=at(17))["points"], [])

    def test_corrupt_summary_does_not_override_verified_capture(self) -> None:
        self.store(1, 15, 21)
        self.close_day(15)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE account_daily_observations SET balance='9999'")
        with self.assertRaises(TelemetryStorageError):
            self.read()

    def test_point_count_is_bounded_for_dense_recent_day(self) -> None:
        with open_registry(self.path) as registry:
            for index in range(600):
                raw = message(index + 1, 16, 0)
                captured = datetime(2026, 10, 16, tzinfo=UTC) + timedelta(seconds=index * 61)
                raw["captured_at"] = captured.isoformat().replace("+00:00", "Z")
                raw["payload"]["server_time_msc"] = str(int(captured.timestamp() * 1000) + 7200000)
                registry.store_message(encoded(raw), received_at=captured)
        result = self.read()
        self.assertLessEqual(len(result["points"]), 480)
        self.assertEqual(result["points"][-1]["balance"], 700)

    def test_invalid_ranges_and_sources_are_rejected(self) -> None:
        for start, end in ((True, 2), (1, 1), (-1, 2), (0, 367 * 86400000)):
            with self.assertRaises(ValueError):
                self.read(start, end)
        with self.assertRaises(TelemetryStorageError):
            read_account_evolution(self.path, "unknown", from_msc=0, to_msc=1)


class AccountEvolutionApiTest(unittest.TestCase):
    def setUp(self) -> None:
        central_fixture.CentralApiTest.setUp(self)
        self.route = (
            f"/api/accounts/evolution?source_id=demo-terminal-01&from_msc={at(14)}&to_msc={at(17)}"
        )
        self.headers = {"Authorization": f"Bearer {self.settings.account_read}"}

    def test_permissions_queries_and_openapi(self) -> None:
        self.assertEqual(self.client.get(self.route).status_code, 401)
        self.assertEqual(
            self.client.get(
                self.route.replace("demo-terminal-01", "other"), headers=self.headers
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(self.route + "&source_id=other", headers=self.headers).status_code, 400
        )
        response = self.client.get(self.route, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sampling"], "daily_close_and_recent")
        self.assertIn("/api/accounts/evolution", self.client.get("/openapi.json").json()["paths"])

    def test_storage_failure_has_no_internal_details(self) -> None:
        with patch(
            "tradinglab.telemetry.persistent_receiver.read_account_evolution",
            side_effect=TelemetryStorageError("private"),
        ):
            response = self.client.get(self.route, headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private", response.text)

    def test_dashboard_client_validates_unified_response(self) -> None:
        self.client.post(
            "/api/account-state",
            json=message(1, 16, 8),
            headers={"Authorization": f"Bearer {self.settings.snapshot_ingest}"},
        )
        payload = self.client.get(self.route, headers=self.headers).json()
        read_key = self.settings.account_read
        adapter = LoopbackTelemetryClient(
            token=read_key,
            source_id="demo-terminal-01",
            port=8782,
            central_api=True,
        )
        with patch.object(
            adapter._opener, "open", return_value=io.BytesIO(json.dumps(payload).encode())
        ):
            result = adapter.account_evolution(from_msc=at(14), to_msc=at(17))
        self.assertEqual(result["points"][0]["resolution"], "recent")
        for key, value in (
            ("source_id", "other"),
            ("points", payload["points"] * 481),
            ("bucket_msc", 0),
        ):
            invalid = deepcopy(payload)
            invalid[key] = value
            with (
                patch.object(
                    adapter._opener, "open", return_value=io.BytesIO(json.dumps(invalid).encode())
                ),
                self.assertRaises(DashboardReadError),
            ):
                adapter.account_evolution(from_msc=at(14), to_msc=at(17))

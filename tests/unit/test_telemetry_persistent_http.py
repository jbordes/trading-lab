from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from test_mt5_telemetry import TOKEN, encoded, snapshot_message
from test_telemetry_history import history_message

from tradinglab.telemetry.contract import parse_envelope
from tradinglab.telemetry.ingest import create_telemetry_server
from tradinglab.telemetry.persistent_receiver import PersistentTelemetryReceiver
from tradinglab.telemetry.sqlite_store import create_database, open_registry

SOURCE = "demo-terminal-01"


class PersistentHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "receiver.sqlite3"
        create_database(self.database)
        now = datetime(2026, 10, 20, 12, tzinfo=UTC)
        with open_registry(self.database) as registry:
            registry.register_account("a", "Demo", "DEMO-SERVER", "USD", created_at=now)
            registry.register_source(SOURCE, "a", created_at=now)
        self.start_receiver()
        self.addCleanup(self.stop_receiver)

    def start_receiver(self) -> None:
        self.backend = PersistentTelemetryReceiver(
            self.database,
            source_id=SOURCE,
            clock=lambda: datetime(2026, 10, 20, 12, tzinfo=UTC),
        )
        self.server = create_telemetry_server(self.backend, token=TOKEN, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def stop_receiver(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.backend.close()

    def request(
        self, route: str, *, message: dict | None = None, token: str = TOKEN
    ) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {token}"}
        if message is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base + route,
            data=encoded(message) if message is not None else None,
            headers=headers,
            method="POST" if message is not None else "GET",
        )
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read())

    def test_recovery_retry_and_health_after_restart(self) -> None:
        self.assertEqual(self.request("/v1/telemetry", message=snapshot_message())[0], 202)
        before = self.request(f"/v1/snapshot?source_id={SOURCE}")
        self.assertEqual(before[1]["sequence"], 1)
        self.stop_receiver()
        self.start_receiver()
        self.assertEqual(self.request(f"/v1/snapshot?source_id={SOURCE}"), before)
        health = self.request("/health")[1]
        self.assertEqual((health["storage"], health["accepted"]), ("sqlite", 0))
        self.assertEqual(self.request("/v1/telemetry", message=snapshot_message())[0], 200)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM telemetry_messages").fetchone()[0], 1
            )

    def test_source_binding_auth_and_conflict(self) -> None:
        self.assertEqual(
            self.request("/v1/telemetry", message=snapshot_message(), token="x")[0], 401
        )
        self.assertEqual(
            self.request("/v1/telemetry", message=snapshot_message(source_id="other"))[0], 403
        )
        self.assertEqual(self.request("/v1/snapshot?source_id=other")[0], 404)
        self.assertEqual(self.request("/v1/telemetry", message=snapshot_message())[0], 202)
        changed = snapshot_message()
        changed["payload"]["account"]["balance"] = 2.0
        self.assertEqual(self.request("/v1/telemetry", message=changed)[0], 409)
        self.assertEqual(
            self.request(f"/v1/snapshot?source_id={SOURCE}")[1]["payload"]["account"]["balance"],
            100000.0,
        )

    def test_account_history_preserves_observed_balances_and_is_authenticated(self) -> None:
        from tradinglab.dashboard.telemetry import LoopbackTelemetryClient

        for sequence, minute, balance in [(1, 0, 100000), (2, 1, 100010), (3, 4, 99990)]:
            message = snapshot_message(sequence=sequence)
            message["captured_at"] = f"2026-10-20T10:{minute:02d}:00Z"
            message["payload"]["account"].update(balance=balance, equity=balance - 50)
            self.assertEqual(self.request("/v1/telemetry", message=message)[0], 202)
        start = int(datetime(2026, 10, 20, 10, tzinfo=UTC).timestamp() * 1000)
        route = f"/v1/account-history?source_id={SOURCE}&from_msc={start}&to_msc={start + 3600000}"
        status, result = self.request(route)
        self.assertEqual(status, 200)
        self.assertEqual([p["balance"] for p in result["points"]], [100000, 100010, 99990])
        self.assertEqual(result["bucket_msc"], 60000)
        self.assertEqual(self.request(route, token="wrong")[0], 401)
        self.assertEqual(self.request(route.replace(SOURCE, "another-source"))[0], 404)
        self.assertEqual(self.request(route + "&from_msc=1")[0], 400)
        self.assertEqual(
            self.request(route.replace(str(start + 3600000), str(start + 367 * 86400000)))[0], 400
        )
        client = LoopbackTelemetryClient(
            token=TOKEN, source_id=SOURCE, port=self.server.server_port
        )
        self.assertEqual(client.account_history(from_msc=start, to_msc=start + 3600000), result)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM telemetry_messages").fetchone()[0], 3
            )

    def test_concurrent_requests_insert_once_and_stale_is_rejected(self) -> None:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda _: self.request("/v1/telemetry", message=snapshot_message())[0], range(2)
                )
            )
        self.assertEqual(sorted(responses), [200, 202])
        self.assertEqual(
            self.request("/v1/telemetry", message=snapshot_message(sequence=3))[0], 202
        )
        self.assertEqual(
            self.request("/v1/telemetry", message=snapshot_message(sequence=2))[0], 409
        )
        self.assertEqual(self.request("/health")[1]["missing_sequences"], 1)

    def test_slow_account_history_does_not_block_ingestion(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def slow_history(*args: object, **kwargs: object) -> dict[str, object]:
            started.set()
            self.assertTrue(release.wait(timeout=2))
            return {"points": []}

        with patch(
            "tradinglab.telemetry.persistent_receiver.read_account_history",
            side_effect=slow_history,
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                history = pool.submit(
                    self.backend.account_history,
                    SOURCE,
                    from_msc=1,
                    to_msc=2,
                )
                self.assertTrue(started.wait(timeout=1))
                ingestion = pool.submit(
                    self.backend.accept,
                    parse_envelope(encoded(snapshot_message())),
                )
                self.assertEqual(ingestion.result(timeout=1).status, "accepted")
                release.set()
                self.assertEqual(history.result(timeout=1), {"points": []})

    def test_unknown_source_fails_before_binding(self) -> None:
        with self.assertRaises(ValueError):
            PersistentTelemetryReceiver(self.database, source_id="bad/source")
        from tradinglab.telemetry.sqlite_store import MessageAdmissionError

        with self.assertRaises(MessageAdmissionError):
            PersistentTelemetryReceiver(self.database, source_id="not-registered")

    def test_authenticated_deal_history_is_filtered_and_paginated(self) -> None:
        message = history_message()
        prototype = message["payload"]["history"]["deals"][0]
        deals = [dict(prototype, ticket=str(ticket), time_msc="999001") for ticket in range(1, 4)]
        message["payload"]["history"].update(deals=deals, total=3)
        self.assertEqual(self.request("/v1/telemetry", message=message)[0], 202)

        route = f"/v1/deals?source_id={SOURCE}&from_msc=999000&to_msc=1000000&limit=2"
        status, first = self.request(route)
        self.assertEqual(status, 200)
        self.assertEqual([deal["ticket"] for deal in first["deals"]], ["3", "2"])
        self.assertIsNotNone(first["next_cursor"])
        status, second = self.request(route + f"&cursor={first['next_cursor']}")
        self.assertEqual(status, 200)
        self.assertEqual([deal["ticket"] for deal in second["deals"]], ["1"])
        self.assertIsNone(second["next_cursor"])

        filtered = self.request(route + "&magic_number=0")
        self.assertEqual(filtered[1]["deals"], [])
        self.assertEqual(self.request(route, token="x")[0], 401)

    def test_deal_history_rejects_invalid_or_unauthorized_queries(self) -> None:
        base = f"/v1/deals?source_id={SOURCE}&from_msc=1&to_msc=2"
        self.assertEqual(self.request(base + "&limit=0")[0], 400)
        self.assertEqual(self.request(base + "&magic_number=01")[0], 400)
        self.assertEqual(self.request(base + "&cursor=invalid")[0], 400)
        self.assertEqual(self.request("/v1/deals?source_id=other&from_msc=1&to_msc=2")[0], 404)


if __name__ == "__main__":
    unittest.main()

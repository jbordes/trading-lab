from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from tradinglab.telemetry.admission_v2 import ProducerIdentity
from tradinglab.telemetry.ingest_v2 import create_v2_telemetry_server
from tradinglab.telemetry.persistent_receiver_v2 import PersistentV2TelemetryReceiver
from tradinglab.telemetry.provisioning_v2 import V2ProvisionPlan
from tradinglab.telemetry.sqlite_store_v2 import open_v2_registry

FIXTURES = Path(__file__).parents[1] / "fixtures/telemetry_v2"


def live_authorization() -> str:
    return "-".join(("synthetic", "live", "credential", "safe", "length"))


def activity_authorization() -> str:
    return "-".join(("synthetic", "activity", "credential", "safe", "length"))


def read_authorization() -> str:
    return "-".join(("synthetic", "read", "credential", "safe", "length"))


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class V2PersistentHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.database = V2ProvisionPlan(
            root,
            "pilot.sqlite3",
            "account-demo",
            "Demo",
            ProducerIdentity("****1234", "DEMO-SERVER", "USD"),
            "synthetic-live",
            "synthetic-activity",
        ).apply(clock=datetime(2026, 10, 25, 10, tzinfo=UTC))
        self.start_receiver()
        self.addCleanup(self.stop_receiver)

    def start_receiver(self) -> None:
        self.backend = PersistentV2TelemetryReceiver(
            self.database,
            account_id="account-demo",
            live_authorization=live_authorization(),
            activity_authorization=activity_authorization(),
            clock=lambda: datetime(2026, 10, 25, 11, tzinfo=UTC),
        )
        self.server = create_v2_telemetry_server(
            self.backend,
            port=0,
            read_authorization=read_authorization(),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def stop_receiver(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.backend.close()

    def request(
        self,
        route: str,
        *,
        body: bytes | None = None,
        authorization: str | None = None,
    ) -> tuple[int, dict[str, object]]:
        headers: dict[str, str] = {}
        if authorization is not None:
            headers["Authorization"] = f"Bearer {authorization}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base + route,
            data=body,
            headers=headers,
            method="POST" if body is not None else "GET",
        )
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read())

    @staticmethod
    def encoded(name: str) -> bytes:
        return json.dumps(fixture(name), separators=(",", ":")).encode()

    def test_both_roles_commit_and_retry_survives_restart(self) -> None:
        live = self.encoded("live-empty")
        activity = self.encoded("activity-canceled-order")
        self.assertEqual(
            self.request("/v2/telemetry", body=live, authorization=live_authorization())[0], 202
        )
        self.assertEqual(
            self.request("/v2/telemetry", body=activity, authorization=activity_authorization())[0],
            202,
        )
        self.stop_receiver()
        self.start_receiver()
        status, retry = self.request(
            "/v2/telemetry", body=activity, authorization=activity_authorization()
        )
        self.assertEqual((status, retry["status"]), (200, "duplicate"))
        with open_v2_registry(self.database) as registry:
            evidence = registry.account_evidence("account-demo")
        self.assertEqual(len(evidence.messages), 2)
        self.assertEqual(len(evidence.messages[1].envelope.payload["orders"]["items"]), 1)

    def test_authentication_precedes_parsing_and_roles_are_isolated(self) -> None:
        invalid = b"not-json"
        self.assertEqual(self.request("/v2/telemetry", body=invalid)[0], 401)
        self.assertEqual(self.request("/v2/telemetry", body=invalid, authorization="x")[0], 401)
        self.assertEqual(
            self.request("/v2/telemetry", body=invalid, authorization=live_authorization())[0],
            400,
        )
        self.assertEqual(
            self.request(
                "/v2/telemetry",
                body=self.encoded("activity-canceled-order"),
                authorization=live_authorization(),
            )[0],
            403,
        )

    def test_conflict_health_and_route_boundaries(self) -> None:
        message = fixture("live-empty")
        body = json.dumps(message).encode()
        self.assertEqual(
            self.request("/v2/telemetry", body=body, authorization=live_authorization())[0],
            202,
        )
        message["payload"]["account"]["balance"] = 2
        self.assertEqual(
            self.request(
                "/v2/telemetry",
                body=json.dumps(message).encode(),
                authorization=live_authorization(),
            )[0],
            409,
        )
        reused_event = fixture("live-empty")
        reused_event["sequence"] = 2
        self.assertEqual(
            self.request(
                "/v2/telemetry",
                body=json.dumps(reused_event).encode(),
                authorization=live_authorization(),
            )[0],
            400,
        )
        status, health = self.request("/health")
        self.assertEqual(status, 200)
        self.assertEqual((health["storage"], health["accepted"]), ("sqlite-v2", 1))
        self.assertNotIn("account_id", health)
        self.assertEqual(
            self.request("/v1/telemetry", body=body, authorization=live_authorization())[0], 404
        )
        self.assertEqual(
            self.request("/v2/telemetry?x=1", body=body, authorization=live_authorization())[0],
            404,
        )

    def test_activity_read_uses_separate_auth_and_returns_coverage(self) -> None:
        self.assertEqual(
            self.request(
                "/v2/telemetry",
                body=self.encoded("activity-canceled-order"),
                authorization=activity_authorization(),
            )[0],
            202,
        )
        route = (
            "/v2/activity?entity=order&from_msc=1792656000000"
            "&to_msc=1792656060001&magic_number=11122&limit=1"
        )
        self.assertEqual(self.request(route)[0], 401)
        self.assertEqual(self.request(route, authorization=activity_authorization())[0], 401)
        status, payload = self.request(route, authorization=read_authorization())

        self.assertEqual(status, 200)
        self.assertEqual(payload["account_id"], "account-demo")
        self.assertEqual(payload["entity_type"], "order")
        self.assertEqual(payload["items"][0]["ticket"], "900000000000000001")
        self.assertEqual(payload["items"][0]["values"]["state"], 2)
        self.assertEqual(
            payload["coverage"]["complete_ranges"],
            [{"from_msc": "1792656000000", "to_msc": "1792656060000"}],
        )
        self.assertEqual(payload["coverage"]["incomplete_batches"], 0)

    def test_activity_authentication_precedes_query_validation(self) -> None:
        self.assertEqual(self.request("/v2/activity?broken")[0], 401)
        self.assertEqual(
            self.request("/v2/activity?broken", authorization=read_authorization())[0],
            400,
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import uvicorn
from fastapi.testclient import TestClient
from test_mt5_telemetry import snapshot_message

from tradinglab.dashboard.telemetry import LoopbackTelemetryClient
from tradinglab.dashboard.telemetry_v2 import LoopbackV2HistoryClient, V2HistoryProvider
from tradinglab.telemetry import api_models as models
from tradinglab.telemetry.admission_v2 import ProducerIdentity, ProducerRole
from tradinglab.telemetry.backup import BackupPlan
from tradinglab.telemetry.central_api import CentralSettings, create_central_app
from tradinglab.telemetry.central_schema import CENTRAL_SCHEMA_VERSION, create_central_database
from tradinglab.telemetry.contract import MAX_BODY_BYTES, parse_envelope
from tradinglab.telemetry.contract_v2 import parse_envelope_v2
from tradinglab.telemetry.relay import RelayForwarder, RelayIngress, RelayProducer
from tradinglab.telemetry.relay_delivery import validate_central_ack
from tradinglab.telemetry.relay_queue import RelayQueue, create_relay_database
from tradinglab.telemetry.sqlite_store import MessageAdmissionError, open_registry
from tradinglab.telemetry.sqlite_store_v2 import V2StorageError, open_v2_registry

FIXTURES = Path(__file__).parents[1] / "fixtures/telemetry_v2"


class CentralApiTest(unittest.TestCase):
    def test_startup_rejects_cross_account_or_wrong_role_sources(self) -> None:
        for settings in (
            replace(self.settings, account_id="another-account"),
            replace(self.settings, source_id="synthetic-activity"),
        ):
            with self.subTest(settings=settings.source_id), self.assertRaises(ValueError):
                with TestClient(create_central_app(settings)):
                    self.fail("No debe iniciar con identidad de cuenta o rol incorrectos")

    def test_v1_rejects_wrong_masked_account_and_activity_source(self) -> None:
        message = snapshot_message()
        message["payload"]["account"]["login_masked"] = "****9999"
        response = self.client.post(
            "/v1/telemetry",
            json=message,
            headers={"Authorization": f"Bearer {self.settings.v1_ingest}"},
        )
        self.assertEqual(response.status_code, 403, response.text)
        message = snapshot_message()
        message["source_id"] = "synthetic-activity"
        with (
            open_registry(self.settings.database) as registry,
            self.assertRaises(MessageAdmissionError),
        ):
            registry.store_message(json.dumps(message).encode(), received_at=datetime.now(UTC))

    def test_concurrent_contracts_commit_to_one_file_and_deduplicate(self) -> None:
        messages = (
            ("/v1/telemetry", self.settings.v1_ingest, snapshot_message()),
            (
                "/v2/telemetry",
                self.settings.v2_activity,
                json.loads((FIXTURES / "activity-canceled-order.json").read_text()),
            ),
        )

        def send(item):
            route, token, payload = item
            return self.client.post(
                route, json=payload, headers={"Authorization": f"Bearer {token}"}
            )

        for expected in (202, 200):
            with ThreadPoolExecutor(max_workers=2) as pool:
                for response in pool.map(send, messages):
                    self.assertEqual(response.status_code, expected, response.text)
        with closing(sqlite3.connect(self.settings.database)) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 1)
            for table in ("telemetry_messages", "telemetry_v2_messages"):
                self.assertEqual(database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1)

        copied = BackupPlan(
            self.root, self.settings.database.name, self.root, (CENTRAL_SCHEMA_VERSION,)
        ).apply()
        with closing(sqlite3.connect(copied.directory / "data.sqlite3")) as database:
            for table in ("telemetry_messages", "telemetry_v2_messages"):
                self.assertEqual(database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1)

    def test_v1_health_requires_read_permission_and_exposes_no_payload(self) -> None:
        for key in (self.settings.v1_ingest, self.settings.v2_read):
            response = self.client.get("/v1/health", headers={"Authorization": f"Bearer {key}"})
            self.assertEqual(response.status_code, 401)
        response = self.client.get(
            "/v1/health", headers={"Authorization": f"Bearer {self.settings.v1_read}"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("latest", response.json())
        self.assertEqual(response.json()["history_status"], "unavailable")
        self.assertNotIn("accepted", self.client.get("/health").json())

    def test_relay_to_fastapi_to_dashboard_clients_over_real_http(self) -> None:
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                create_central_app(self.settings),
                log_level="error",
                access_log=False,
                proxy_headers=False,
                timeout_graceful_shutdown=2,
            )
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                thread.join(0.01)
            self.assertTrue(server.started, "La API de prueba no inició")
            producers = (
                RelayProducer(
                    "v1",
                    "demo-terminal-01",
                    "demo",
                    ProducerRole.LIVE,
                    ProducerIdentity("****1234", "DEMO-SERVER", "USD"),
                    f"http://127.0.0.1:{port}/v1/telemetry",
                    "synthetic-local-live-key-12345",
                    self.settings.v1_ingest,
                ),
                RelayProducer(
                    "v2",
                    "synthetic-activity",
                    "demo",
                    ProducerRole.ACTIVITY,
                    ProducerIdentity("****1234", "DEMO-SERVER", "USD"),
                    f"http://127.0.0.1:{port}/v2/telemetry",
                    "synthetic-local-activity-key-12345",
                    self.settings.v2_activity,
                ),
            )
            queue_path = self.root / "outbox.sqlite3"
            create_relay_database(queue_path)
            queue = RelayQueue(queue_path)
            try:
                ingress = RelayIngress(queue, producers)
                ingress.accept(
                    "v2",
                    (FIXTURES / "activity-canceled-order.json").read_bytes(),
                    f"Bearer {producers[1].local_token}",
                    now=1,
                )
                for producer, raw in zip(
                    producers,
                    (
                        json.dumps(snapshot_message()).encode(),
                        (FIXTURES / "activity-position-reconcile.json").read_bytes(),
                    ),
                    strict=True,
                ):
                    ingress.accept(producer.version, raw, f"Bearer {producer.local_token}", now=1)
                forwarder = RelayForwarder(queue, producers)
                forwarder.run_once(now=2)
                forwarder.run_once(now=3)
                for producer in producers:
                    self.assertIsNone(queue.next(producer.stream, now=1000))
            finally:
                queue.close()
            key = self.settings.v1_read
            live = LoopbackTelemetryClient(
                token=key,
                source_id="demo-terminal-01",
                port=port,
                central_api=True,
            )
            self.assertEqual(live.latest().source_id, "demo-terminal-01")
            self.assertEqual(live.health().accepted, 1)
            history = live.account_history(from_msc=1792000000000, to_msc=1793000000000)
            self.assertTrue(history["points"])
            activity = LoopbackV2HistoryClient(
                read_authorization=self.settings.v2_read,
                activity_source_id="synthetic-activity",
                port=port,
            )
            self.assertTrue(activity.position_cycles(closed_only=True).cycles)
            self.assertTrue(activity.position_cycle_magics())
            self.assertTrue(
                activity.deal_history(from_msc=1792000000000, to_msc=1793000000000).deals
            )
            self.assertTrue(
                activity.order_history(from_msc=1792000000000, to_msc=1793000000000).orders
            )
            metrics = V2HistoryProvider(activity).cycle_performance_metrics(
                from_msc=1792000000000, to_msc=1793000000000
            )
            self.assertGreater(metrics.as_dict()["trade_count"], 0)
        finally:
            server.should_exit = True
            thread.join(5)
        self.assertFalse(thread.is_alive(), "La API de prueba no cerró")

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        database = self.root / "central.sqlite3"
        create_central_database(database)
        stamp = datetime.now(UTC)
        with open_v2_registry(database) as registry:
            registry.register_account(
                "demo",
                "Demo",
                ProducerIdentity("****1234", "DEMO-SERVER", "USD"),
                created_at=stamp,
            )
            registry.register_source("synthetic-live", "demo", ProducerRole.LIVE, created_at=stamp)
            registry.register_source(
                "synthetic-activity", "demo", ProducerRole.ACTIVITY, created_at=stamp
            )
        with open_registry(database) as registry:
            registry.register_source("demo-terminal-01", "demo", created_at=stamp)
        self.settings = CentralSettings(
            database,
            "demo-terminal-01",
            "demo",
            *(f"synthetic-central-api-key-number-{i}" for i in range(5)),
        )
        self.app = create_central_app(self.settings)
        self.client = TestClient(self.app, base_url="http://127.0.0.1")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_openapi_and_docs_have_real_request_response_and_security_models(self) -> None:
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200, response.text)
        schema = response.json()
        self.assertTrue(schema["openapi"].startswith("3."))
        operation = schema["paths"]["/v2/telemetry"]["post"]
        self.assertIn("requestBody", operation)
        self.assertIn("202", operation["responses"])
        self.assertNotIn("422", operation["responses"])
        self.assertTrue(operation["security"])
        self.assertIn("V2Activity", schema["components"]["schemas"])
        self.assertIn("HistoryOrder", schema["components"]["schemas"])
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertNotIn(self.settings.v2_live, response.text)

    def test_durable_v1_ingestion_duplicate_and_read_separation(self) -> None:
        message = snapshot_message()
        headers = {"Authorization": f"Bearer {self.settings.v1_ingest}"}
        for expected in (202, 200):
            response = self.client.post("/v1/telemetry", json=message, headers=headers)
            self.assertEqual(response.status_code, expected, response.text)
        path = "/v1/snapshot?source_id=demo-terminal-01"
        self.assertEqual(self.client.get(path, headers=headers).status_code, 401)
        read = {"Authorization": f"Bearer {self.settings.v1_read}"}
        self.assertEqual(self.client.get(path, headers=read).status_code, 200)
        self.assertEqual(
            self.client.post("/v1/telemetry", json=message, headers=read).status_code, 401
        )

    def test_v2_fixtures_and_durable_queries(self) -> None:
        body = json.loads((FIXTURES / "activity-canceled-order.json").read_text(encoding="utf-8"))
        headers = {"Authorization": f"Bearer {self.settings.v2_activity}"}
        response = self.client.post("/v2/telemetry", json=body, headers=headers)
        self.assertEqual(response.status_code, 202, response.text)
        read = {"Authorization": f"Bearer {self.settings.v2_read}"}
        response = self.client.get(
            "/v2/activity?entity=order&from_msc=1792656000000&to_msc=1792656060001", headers=read
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["items"]), 1)
        for path in ("/v2/activity-progress", "/v2/position-cycle-magics", "/v2/position-cycles"):
            self.assertEqual(self.client.get(path, headers=read).status_code, 200)

    def test_invalid_json_duplicate_keys_and_bool_sequence_are_rejected_without_422(self) -> None:
        headers = {
            "Authorization": f"Bearer {self.settings.v2_live}",
            "Content-Type": "application/json",
        }
        body = (FIXTURES / "heartbeat.json").read_text(encoding="utf-8")
        for value in (
            "{",
            body.replace('"sequence": 2', '"sequence": true'),
            body.replace('"sequence": 2', '"sequence": 2, "sequence": 2'),
        ):
            response = self.client.post("/v2/telemetry", content=value, headers=headers)
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(
            self.client.get(
                "/v2/activity", headers={"Authorization": f"Bearer {self.settings.v2_read}"}
            ).status_code,
            400,
        )

    def test_all_v2_fixture_structures_and_examples_match_documented_models(self) -> None:
        for path in FIXTURES.glob("*.json"):
            with self.subTest(path=path.name):
                envelope = parse_envelope_v2(path.read_bytes())
                models.V2_REQUEST.validate_python(envelope.as_dict())
        parse_envelope(json.dumps(models.EXAMPLE_V1).encode())
        parse_envelope_v2(json.dumps(models.EXAMPLE_V2).encode())

    def test_openapi_component_references_resolve(self) -> None:
        schema = self.client.get("/openapi.json").json()

        def visit(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    self.assertTrue(value["$ref"].startswith("#/components/schemas/"))
                    self.assertIn(value["$ref"].split("/")[-1], schema["components"]["schemas"])
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(schema)

    def test_limits_auth_origin_and_query_validation(self) -> None:
        producer = {
            "Authorization": f"Bearer {self.settings.v2_live}",
            "Content-Type": "application/json",
        }
        self.assertEqual(
            self.client.post(
                "/v2/telemetry", content=b"x" * (MAX_BODY_BYTES + 1), headers=producer
            ).status_code,
            413,
        )
        self.assertEqual(self.client.post("/v2/telemetry", json=models.EXAMPLE_V2).status_code, 401)
        self.assertEqual(
            self.client.get("/health", headers={"Host": "attacker.invalid"}).status_code, 400
        )
        self.assertEqual(
            self.client.get("/health", headers={"Origin": "https://attacker.invalid"}).status_code,
            403,
        )
        read = {"Authorization": f"Bearer {self.settings.v2_read}"}
        for query in ("limit=1&limit=2", "unknown=1", "limit=01", "closed_only=1"):
            self.assertEqual(
                self.client.get("/v2/position-cycles?" + query, headers=read).status_code, 400
            )

    def test_populated_cycle_and_v1_history_response_models(self) -> None:
        headers = {"Authorization": f"Bearer {self.settings.v2_activity}"}
        body = json.loads(
            (FIXTURES / "activity-position-reconcile.json").read_text(encoding="utf-8")
        )
        response = self.client.post("/v2/telemetry", json=body, headers=headers)
        self.assertEqual(response.status_code, 202, response.text)
        read = {"Authorization": f"Bearer {self.settings.v2_read}"}
        response = self.client.get("/v2/position-cycles?closed_only=true", headers=read)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["items"])
        self.client.post(
            "/v1/telemetry",
            json=snapshot_message(),
            headers={"Authorization": f"Bearer {self.settings.v1_ingest}"},
        )
        read1 = {"Authorization": f"Bearer {self.settings.v1_read}"}
        for path in ("deals", "account-history"):
            response = self.client.get(
                f"/v1/{path}?source_id=demo-terminal-01&from_msc=1792000000000&to_msc=1792300000000",
                headers=read1,
            )
            self.assertEqual(response.status_code, 200, response.text)

    def test_producer_roles_are_enforced_and_ack_matches_relay_contract(self) -> None:
        raw = (FIXTURES / "activity-canceled-order.json").read_bytes()
        live = {"Authorization": f"Bearer {self.settings.v2_live}"}
        activity = {"Authorization": f"Bearer {self.settings.v2_activity}"}
        self.assertEqual(
            self.client.post(
                "/v2/telemetry", content=raw, headers={**live, "Content-Type": "application/json"}
            ).status_code,
            403,
        )
        for expected in (202, 200):
            response = self.client.post(
                "/v2/telemetry",
                content=raw,
                headers={**activity, "Content-Type": "application/json"},
            )
            self.assertEqual(response.status_code, expected, response.text)
            validate_central_ack(
                response.status_code,
                response.headers["content-type"],
                response.content,
                version="v2",
            )
        self.assertEqual(
            self.client.get("/v2/activity-progress", headers=activity).status_code, 401
        )

    def test_accepted_messages_survive_reopening_services(self) -> None:
        headers = {"Authorization": f"Bearer {self.settings.v1_ingest}"}
        response = self.client.post("/v1/telemetry", json=snapshot_message(), headers=headers)
        self.assertEqual(response.status_code, 202)
        reopened_app = create_central_app(self.settings)
        with TestClient(reopened_app, base_url="http://127.0.0.1") as reopened:
            response = reopened.post("/v1/telemetry", json=snapshot_message(), headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            validate_central_ack(
                response.status_code,
                response.headers["content-type"],
                response.content,
                version="v1",
            )
        self.assertFalse(hasattr(reopened_app.state, "services"))

    def test_storage_failure_returns_no_ack_and_no_internal_details(self) -> None:
        receiver = self.app.state.services.v2
        with patch.object(
            type(receiver), "accept", side_effect=V2StorageError("private database path")
        ):
            response = self.client.post(
                "/v2/telemetry",
                json=models.EXAMPLE_V2,
                headers={"Authorization": f"Bearer {self.settings.v2_live}"},
            )
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json(), {"error": "storage_unavailable"})


if __name__ == "__main__":
    unittest.main()

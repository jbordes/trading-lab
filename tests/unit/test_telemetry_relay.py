from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import patch

from test_mt5_telemetry import snapshot_message

from tradinglab.telemetry.admission_v2 import (
    ProducerIdentity,
    ProducerRole,
    V2AuthorizationError,
    V2StaleSequenceError,
)
from tradinglab.telemetry.http_server import BoundedTelemetryServer
from tradinglab.telemetry.ingest import create_telemetry_server
from tradinglab.telemetry.ingest_v2 import create_v2_telemetry_server
from tradinglab.telemetry.persistent_receiver import PersistentTelemetryReceiver
from tradinglab.telemetry.persistent_receiver_v2 import PersistentV2TelemetryReceiver
from tradinglab.telemetry.provisioning_v2 import V2ProvisionPlan
from tradinglab.telemetry.relay import RelayForwarder, RelayIngress, RelayProducer
from tradinglab.telemetry.relay_config import load_relay_producers
from tradinglab.telemetry.relay_http import create_relay_server
from tradinglab.telemetry.relay_queue import (
    RelayConflict,
    RelayQueue,
    RelayStorageError,
    create_relay_database,
)
from tradinglab.telemetry.sqlite_store import create_database, open_registry

FIXTURES = Path(__file__).parents[1] / "fixtures/telemetry_v2"
LOCAL = "synthetic-local-relay-credential-01"
CENTRAL = "synthetic-central-relay-credential-01"
READ = "synthetic-central-read-credential-01"
ACTIVITY = "synthetic-central-activity-credential-01"


def message(sequence: int = 1) -> bytes:
    body = json.loads((FIXTURES / "heartbeat.json").read_text(encoding="utf-8"))
    body["sequence"] = sequence
    body["event_id"] = f"{body['session_id']}:{sequence}"
    return json.dumps(body).encode()


class RelayTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "outbox.sqlite3"
        create_relay_database(self.path)
        self.queue = RelayQueue(self.path)
        self.addCleanup(lambda: self.queue.close())
        self.producer = RelayProducer(
            "v2",
            "synthetic-live",
            "account-demo",
            ProducerRole.LIVE,
            ProducerIdentity("****1234", "DEMO-SERVER", "USD"),
            "http://127.0.0.1:8777/v2/telemetry",
            LOCAL,
            CENTRAL,
        )
        self.ingress = RelayIngress(self.queue, (self.producer,))

    def enqueue(self, sequence: int = 1) -> tuple[bool, int, bool]:
        return self.ingress.accept("v2", message(sequence), f"Bearer {LOCAL}", now=10)

    def server(self, server) -> str:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop() -> None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        self.addCleanup(stop)
        return f"http://127.0.0.1:{server.server_port}"

    def central_v2(self) -> str:
        db = V2ProvisionPlan(
            self.root,
            "central.sqlite3",
            "account-demo",
            "Demo",
            self.producer.identity,
            "synthetic-live",
            "synthetic-activity",
        ).apply()
        backend = PersistentV2TelemetryReceiver(
            db,
            account_id="account-demo",
            live_authorization=CENTRAL,
            activity_authorization=ACTIVITY,
        )
        self.addCleanup(backend.close)
        return self.server(create_v2_telemetry_server(backend, port=0, read_authorization=READ))

    def test_restart_duplicates_conflicts_and_full_queue(self) -> None:
        self.assertTrue(self.enqueue()[0])
        self.queue.close()
        self.queue = RelayQueue(self.path, max_records=1)
        self.ingress = RelayIngress(self.queue, (self.producer,))
        self.assertFalse(self.enqueue()[0])
        changed = json.loads(message())
        changed["collector_version"] = "changed"
        with self.assertRaises(RelayConflict):
            self.ingress.accept("v2", json.dumps(changed).encode(), f"Bearer {LOCAL}", now=11)
        with self.assertRaises(RelayStorageError):
            self.enqueue(2)
        self.assertEqual(self.queue.status(now=20)["states"], {"pending": 1})

    def test_network_outage_retries_same_bytes_after_restart(self) -> None:
        self.enqueue()
        forwarder = RelayForwarder(self.ingress)
        with patch.object(forwarder, "_send", side_effect=OSError("offline")):
            forwarder.run_once(now=10)
        self.queue.close()
        self.queue = RelayQueue(self.path)
        pending = self.queue.next(self.producer.stream, now=12)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.attempts, 1)
        self.assertEqual(json.loads(pending.body), json.loads(message()))
        self.assertIsNone(self.queue.next(self.producer.stream, now=10))

    def test_ack_lost_replays_into_real_central_database_without_duplicates(self) -> None:
        url = self.central_v2()
        # Use a new outbox binding for this actual test endpoint.
        path = self.root / "e2e.sqlite3"
        create_relay_database(path)
        queue = RelayQueue(path)
        self.addCleanup(queue.close)
        producer = replace(self.producer, target=url + "/v2/telemetry")
        ingress = RelayIngress(queue, (producer,))
        ingress.accept("v2", message(), f"Bearer {LOCAL}", now=10)
        forwarder = RelayForwarder(ingress)
        original = forwarder._send

        def lose_ack(*args, **kwargs):
            status, _, _ = original(*args, **kwargs)
            self.assertEqual(status, 202)
            raise OSError("ACK lost")

        with patch.object(forwarder, "_send", side_effect=lose_ack):
            forwarder.run_once(now=10)
        self.assertEqual(queue.status(now=10)["states"], {"pending": 1})
        forwarder.run_once(now=12)
        self.assertEqual(queue.status(now=12)["states"], {"acked": 1})
        self.assertEqual(queue.status(now=12)["pending_bytes"], 0)
        self.assertFalse(ingress.accept("v2", message(), f"Bearer {LOCAL}", now=13)[0])

    def test_rejected_source_blocks_following_messages(self) -> None:
        self.enqueue()
        self.enqueue(2)
        forwarder = RelayForwarder(self.ingress)
        with patch.object(forwarder, "_send", return_value=(409, "application/json", b"{}")):
            forwarder.run_once(now=10)
        self.assertIsNone(self.queue.next(self.producer.stream, now=100))
        self.assertEqual(self.queue.status(now=100)["states"], {"pending": 1, "rejected": 1})
        self.assertEqual(self.queue.retry_rejected(self.producer.stream), 1)
        self.assertIsNone(self.queue.next(self.producer.stream, now=100))
        self.queue.retry_rejected(self.producer.stream, apply=True)
        self.assertIsNotNone(self.queue.next(self.producer.stream, now=100))

    def test_invalid_ack_never_removes_pending(self) -> None:
        self.enqueue()
        forwarder = RelayForwarder(self.ingress)

        for index, (status, document) in enumerate(
            (
                (204, b'{"status":null,"sequence_gap":0,"out_of_order":false}'),
                (202, b'{"status":"accepted"}'),
                (
                    202,
                    b'{"status":"wrong","status":"accepted","sequence_gap":0,"out_of_order":false}',
                ),
            )
        ):
            with patch.object(
                forwarder, "_send", return_value=(status, "application/json", document)
            ) as send:
                forwarder.run_once(now=100 + index * 100)
                send.assert_called_once()
            self.assertEqual(self.queue.status(now=200)["states"], {"pending": 1})

    def test_old_activity_reaches_central_with_coverage_and_original_capture(self) -> None:
        url = self.central_v2()
        producer = replace(
            self.producer,
            source_id="synthetic-activity",
            role=ProducerRole.ACTIVITY,
            target=url + "/v2/telemetry",
            central_token=ACTIVITY,
        )
        ingress = RelayIngress(self.queue, (producer,))
        body = (FIXTURES / "activity-canceled-order.json").read_bytes()
        ingress.accept("v2", body, f"Bearer {LOCAL}", now=10)
        RelayForwarder(ingress).run_once(now=10)
        self.assertEqual(self.queue.status(now=10)["states"], {"acked": 1})
        request = urllib.request.Request(
            url + "/v2/activity?entity=order&from_msc=1792656000000&to_msc=1792656060001",
            headers={"Authorization": f"Bearer {READ}"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.load(response)
        self.assertEqual(len(result["items"]), 1)
        self.assertTrue(result["coverage"]["complete_ranges"])

    def test_strict_sequence_stream_rejects_old_unknown_but_accepts_duplicate(self) -> None:
        self.enqueue(2)
        with self.assertRaises(V2StaleSequenceError):
            self.enqueue(1)
        self.assertFalse(self.enqueue(2)[0])

    def test_rejected_source_does_not_block_other_source(self) -> None:
        second = replace(
            self.producer,
            source_id="second-live",
            local_token=LOCAL + "2",
            central_token=CENTRAL + "2",
        )
        ingress = RelayIngress(self.queue, (self.producer, second))
        self.enqueue()
        body = json.loads(message())
        body["source_id"] = second.source_id
        ingress.accept("v2", json.dumps(body).encode(), f"Bearer {second.local_token}", now=10)

        def send(producer, body):
            return (
                (409, "application/json", b"{}")
                if producer == self.producer
                else (
                    202,
                    "application/json",
                    b'{"status":"accepted","sequence_gap":0,"out_of_order":false}',
                )
            )

        forwarder = RelayForwarder(ingress)
        with patch.object(forwarder, "_send", side_effect=send):
            forwarder.run_once(now=10)
        self.assertEqual(self.queue.status(now=10)["states"], {"acked": 1, "rejected": 1})

    def test_example_configuration_requires_separate_secrets_and_https_remote(self) -> None:
        config = Path(__file__).parents[2] / "docs/development/telemetry-relay.example.json"
        environment = {
            "RELAY_LIVE_LOCAL_TOKEN": LOCAL,
            "RELAY_LIVE_CENTRAL_TOKEN": CENTRAL,
            "RELAY_ACTIVITY_LOCAL_TOKEN": LOCAL + "2",
            "RELAY_ACTIVITY_CENTRAL_TOKEN": CENTRAL + "2",
        }
        producers = load_relay_producers(config, environment)
        self.assertEqual(len(producers), 2)
        with self.assertRaises(ValueError):
            load_relay_producers(config, {})
        for target in (
            "http://example.com/v2/telemetry",
            "https://user:password@example.com/v2/telemetry",
            "https://example.com/v2/telemetry?token=value",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                replace(self.producer, target=target)

    def test_storage_failure_does_not_return_a_local_success(self) -> None:
        url = self.server(create_relay_server(self.ingress, port=0))
        request = urllib.request.Request(
            url + "/v2/telemetry",
            data=message(),
            headers={
                "Authorization": f"Bearer {LOCAL}",
                "Content-Type": "application/json",
            },
        )
        with patch.object(self.queue, "enqueue", side_effect=RelayStorageError("disk failure")):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=3)
            self.assertEqual(caught.exception.code, 503)
            caught.exception.close()
        self.assertEqual(self.queue.status(now=10)["states"], {})

    def test_binding_prevents_reassignment_but_allows_credential_rotation(self) -> None:
        with self.assertRaises(RelayStorageError):
            RelayIngress(self.queue, (replace(self.producer, account_id="another-account"),))
        RelayIngress(self.queue, (replace(self.producer, central_token=CENTRAL + "rotated"),))

    def test_local_http_ack_is_durable_and_invalid_auth_cannot_enqueue(self) -> None:
        url = self.server(create_relay_server(self.ingress, port=0))
        for token, expected in (("invalid", 401), (LOCAL, 202), (LOCAL, 200)):
            request = urllib.request.Request(
                url + "/v2/telemetry",
                data=message(),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            try:
                response = urllib.request.urlopen(request, timeout=3)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                self.assertEqual(response.status, expected)
                response.read()
        with urllib.request.urlopen(url + "/health", timeout=3) as response:
            self.assertEqual(json.load(response)["states"], {"pending": 1})

    def test_v1_forwarding_and_separate_central_read_credential(self) -> None:
        db = self.root / "central-v1.sqlite3"
        create_database(db)
        with open_registry(db) as registry:
            registry.register_account(
                "a", "Demo", "DEMO-SERVER", "USD", created_at=datetime.now(UTC)
            )
            registry.register_source("demo-terminal-01", "a", created_at=datetime.now(UTC))
        backend = PersistentTelemetryReceiver(db, source_id="demo-terminal-01")
        self.addCleanup(backend.close)
        url = self.server(create_telemetry_server(backend, token=CENTRAL, read_token=READ, port=0))
        producer = replace(
            self.producer, version="v1", source_id="demo-terminal-01", target=url + "/v1/telemetry"
        )
        ingress = RelayIngress(self.queue, (producer,))
        body = json.dumps(snapshot_message()).encode()
        ingress.accept("v1", body, f"Bearer {LOCAL}", now=10)
        RelayForwarder(ingress).run_once(now=10)
        self.assertEqual(self.queue.status(now=10)["states"], {"acked": 1})
        for token, expected in ((CENTRAL, 401), (READ, 200)):
            request = urllib.request.Request(
                url + "/v1/snapshot?source_id=demo-terminal-01",
                headers={"Authorization": f"Bearer {token}"},
            )
            try:
                response = urllib.request.urlopen(request, timeout=3)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                self.assertEqual(response.status, expected)
                response.read()

    def test_wrong_role_or_source_is_not_accepted(self) -> None:
        changed = json.loads(message())
        changed["source_id"] = "other-source"
        with self.assertRaises(V2AuthorizationError):
            self.ingress.accept("v2", json.dumps(changed).encode(), f"Bearer {LOCAL}", now=10)
        self.assertEqual(self.queue.status(now=10)["states"], {})

    def test_response_deadline_preserves_message_when_central_never_finishes_body(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)

        class Stalled(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "500")
                self.end_headers()
                self.wfile.flush()
                release.wait(2)

            def log_message(self, *args):
                pass

        url = self.server(
            BoundedTelemetryServer(("127.0.0.1", 0), Stalled, max_connections=2, request_timeout=2)
        )
        path = self.root / "deadline.sqlite3"
        create_relay_database(path)
        queue = RelayQueue(path)
        self.addCleanup(queue.close)
        producer = replace(self.producer, target=url + "/v2/telemetry")
        ingress = RelayIngress(queue, (producer,))
        ingress.accept("v2", message(), f"Bearer {LOCAL}", now=10)
        try:
            RelayForwarder(ingress, timeout=0.05).run_once(now=10)
        finally:
            release.set()
        self.assertEqual(queue.status(now=10)["states"], {"pending": 1})

    def test_cli_initialization_is_explicit_and_never_replaces_existing_queue(self) -> None:
        command = [
            sys.executable,
            str(Path(__file__).parents[2] / "scripts/telemetry_relay.py"),
            "--queue",
            str(self.root / "cli.sqlite3"),
            "--init-queue",
        ]
        first = subprocess.run(command, capture_output=True, timeout=15, check=False)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = subprocess.run(command, capture_output=True, timeout=15, check=False)
        self.assertEqual(second.returncode, 1)


if __name__ == "__main__":
    unittest.main()

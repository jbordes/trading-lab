from __future__ import annotations

import http.client
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
from tradinglab.telemetry.relay_delivery import HttpRelayTransport
from tradinglab.telemetry.relay_http import create_relay_server, relay_listeners
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
    def test_header_rejection_diagnostics_are_bounded_and_do_not_echo_headers(self) -> None:
        server = create_relay_server(self.ingress, port=0)
        url = self.server(server)
        for headers in (
            [],
            [("Host", "127.0.0.1"), ("Host", "localhost")],
            [("Host", "private-header-marker.invalid")],
            [("Host", f"127.0.0.1:{server.server_port}"), ("Origin", "private-origin-marker")],
        ):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                connection.putrequest("GET", "/health", skip_host=True)
                for key, value in headers:
                    connection.putheader(key, value)
                connection.endheaders()
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                self.assertEqual(json.loads(response.read()), {"error": "host_not_allowed"})
            finally:
                connection.close()
        with urllib.request.urlopen(url + "/health", timeout=3) as response:
            health = json.load(response)
        self.assertEqual(
            health["ingress_rejections"],
            {
                "host_missing": 1,
                "host_multiple": 1,
                "host_not_allowed": 1,
                "origin_not_allowed": 1,
            },
        )
        self.assertNotIn("private-", json.dumps(health))

    def test_mt5_host_without_port_preserves_authentication_and_origin_guards(self) -> None:
        server = create_relay_server(self.ingress, port=0)
        url = self.server(server)
        for host, key, origin, expected in (
            ("127.0.0.1", LOCAL, None, 202),
            ("localhost", LOCAL, None, 200),
            ("127.0.0.1", "invalid", None, 401),
            ("localhost", "invalid", None, 401),
            ("127.0.0.1", LOCAL, "http://127.0.0.1", 403),
            ("localhost.evil.invalid", LOCAL, None, 403),
            ("127.0.0.1:1", LOCAL, None, 403),
        ):
            headers = {
                "Host": host,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            if origin is not None:
                headers["Origin"] = origin
            request = urllib.request.Request(url + "/v2/telemetry", data=message(), headers=headers)
            try:
                response = urllib.request.urlopen(request, timeout=3)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                self.assertEqual(response.status, expected)
                response.read()
        with urllib.request.urlopen(url + "/health", timeout=3) as response:
            health = json.load(response)
        self.assertEqual(health["states"], {"pending": 1})
        self.assertEqual(
            health["ingress_rejections"],
            {
                "unauthorized": 2,
                "origin_not_allowed": 1,
                "host_not_allowed": 2,
            },
        )

    def test_authorization_diagnostics_distinguish_source_role_identity_and_version(self) -> None:
        url = self.server(create_relay_server(self.ingress, port=0))
        source = json.loads(message())
        source["source_id"] = "another-source"
        identity = json.loads(message())
        identity["payload"]["identity"]["server"] = "another-server"
        role = json.loads((FIXTURES / "activity-canceled-order.json").read_bytes())
        role["source_id"] = self.producer.source_id
        for path, body in (
            ("/v2/telemetry", source),
            ("/v2/telemetry", identity),
            ("/v2/telemetry", role),
            ("/v1/telemetry", snapshot_message()),
        ):
            request = urllib.request.Request(
                url + path,
                data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {LOCAL}", "Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as captured:
                urllib.request.urlopen(request, timeout=3)
            with captured.exception as response:
                self.assertEqual(response.code, 403)
                self.assertEqual(json.load(response), {"error": "source_not_allowed"})
        with urllib.request.urlopen(url + "/health", timeout=3) as response:
            health = json.load(response)
        self.assertEqual(
            health["ingress_rejections"],
            {
                "source_mismatch": 1,
                "identity_mismatch": 1,
                "role_mismatch": 1,
                "version_mismatch": 1,
            },
        )
        self.assertEqual(health["states"], {})
        self.assertNotIn(LOCAL, json.dumps(health))

    def test_two_listeners_share_one_queue_authentication_and_deduplication(self) -> None:
        live = replace(
            self.producer,
            version="v1",
            source_id="demo-terminal-01",
            target="http://127.0.0.1:8776/v1/telemetry",
            local_token=LOCAL + "v1",
            central_token=CENTRAL + "v1",
        )
        ingress = RelayIngress(self.queue, (live, self.producer))
        with relay_listeners(ingress, (0, 0)) as servers:
            first, second = (f"http://127.0.0.1:{server.server_port}" for server in servers)
            for url, path, raw, key, expected in (
                (
                    first,
                    "/v1/telemetry",
                    json.dumps(snapshot_message()).encode(),
                    live.local_token,
                    202,
                ),
                (second, "/v2/telemetry", message(), LOCAL, 202),
                (first, "/v2/telemetry", message(), LOCAL, 200),
                (second, "/v2/telemetry", message(), "invalid", 401),
            ):
                request = urllib.request.Request(
                    url + path,
                    data=raw,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                )
                try:
                    response = urllib.request.urlopen(request, timeout=3)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    self.assertEqual(response.status, expected)
                    response.read()
            for url in (first, second):
                with urllib.request.urlopen(url + "/health", timeout=3) as response:
                    health = json.load(response)
                    self.assertEqual(health["states"], {"pending": 2})
                    self.assertEqual(health["ingress_rejections"], {"unauthorized": 1})
        self.assertTrue(all(server.socket.fileno() == -1 for server in servers))

    def test_second_bind_failure_closes_first_without_starting_acceptance(self) -> None:
        opened = []

        def bind(ingress, *, port, diagnostics):
            if opened:
                raise OSError("port busy")
            server = create_relay_server(ingress, port=port, diagnostics=diagnostics)
            opened.append(server)
            return server

        with (
            patch("tradinglab.telemetry.relay_http.create_relay_server", side_effect=bind),
            patch("tradinglab.telemetry.relay_http.threading.Thread.start") as start,
        ):
            with self.assertRaises(OSError), relay_listeners(self.ingress, (0, 0)):
                self.fail("No debe abrir un relay parcial")
        start.assert_not_called()
        self.assertEqual(opened[0].socket.fileno(), -1)

    def test_invalid_and_duplicate_listener_ports_fail_before_binding(self) -> None:
        for ports in ((), (8776, 8776), (-1,), (65536,), (True,), tuple(range(9))):
            with self.subTest(ports=ports):
                with patch("tradinglab.telemetry.relay_http.create_relay_server") as bind:
                    with self.assertRaises(ValueError), relay_listeners(self.ingress, ports):
                        self.fail("Puertos inválidos aceptados")
                    bind.assert_not_called()

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
        self.transport = HttpRelayTransport()

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
        forwarder = RelayForwarder(self.queue, self.ingress.producers, transport=self.transport)
        with patch.object(self.transport, "send", side_effect=OSError("offline")):
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
        forwarder = RelayForwarder(queue, ingress.producers, transport=self.transport)
        original = self.transport.send

        def lose_ack(*args, **kwargs):
            status, _, _ = original(*args, **kwargs)
            self.assertEqual(status, 202)
            raise OSError("ACK lost")

        with patch.object(self.transport, "send", side_effect=lose_ack):
            forwarder.run_once(now=10)
        self.assertEqual(queue.status(now=10)["states"], {"pending": 1})
        forwarder.run_once(now=12)
        self.assertEqual(queue.status(now=12)["states"], {"acked": 1})
        self.assertEqual(queue.status(now=12)["pending_bytes"], 0)
        self.assertFalse(ingress.accept("v2", message(), f"Bearer {LOCAL}", now=13)[0])

    def test_rejected_source_blocks_following_messages(self) -> None:
        self.enqueue()
        self.enqueue(2)
        forwarder = RelayForwarder(self.queue, self.ingress.producers, transport=self.transport)
        with patch.object(self.transport, "send", return_value=(409, "application/json", b"{}")):
            forwarder.run_once(now=10)
        self.assertIsNone(self.queue.next(self.producer.stream, now=100))
        self.assertEqual(self.queue.status(now=100)["states"], {"pending": 1, "rejected": 1})
        self.assertEqual(self.queue.retry_rejected(self.producer.stream), 1)
        self.assertIsNone(self.queue.next(self.producer.stream, now=100))
        self.queue.retry_rejected(self.producer.stream, apply=True)
        self.assertIsNotNone(self.queue.next(self.producer.stream, now=100))

    def test_invalid_ack_never_removes_pending(self) -> None:
        self.enqueue()
        forwarder = RelayForwarder(self.queue, self.ingress.producers, transport=self.transport)

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
                self.transport, "send", return_value=(status, "application/json", document)
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
        RelayForwarder(self.queue, ingress.producers).run_once(now=10)
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

        forwarder = RelayForwarder(self.queue, ingress.producers, transport=self.transport)
        with patch.object(self.transport, "send", side_effect=send):
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
        RelayForwarder(self.queue, ingress.producers).run_once(now=10)
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
            RelayForwarder(
                queue, ingress.producers, transport=HttpRelayTransport(timeout=0.05)
            ).run_once(now=10)
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

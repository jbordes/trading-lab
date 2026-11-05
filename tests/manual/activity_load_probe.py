"""Explicit synthetic load probe; never connects to running pilot services.

Run with the project Python. Uses existing test provisioning and in-process ASGI,
not real HTTP sockets or MT5. Temporary databases are removed by test cleanup.
"""

from __future__ import annotations

import copy
import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests/unit")]

from test_central_api import CentralApiTest  # noqa: E402

from tradinglab.telemetry.admission_v2 import ProducerIdentity, ProducerRole  # noqa: E402
from tradinglab.telemetry.relay import RelayForwarder, RelayIngress, RelayProducer  # noqa: E402
from tradinglab.telemetry.relay_queue import RelayQueue, create_relay_database  # noqa: E402

BATCHES = 20
POSITIONS_PER_BATCH = 50
MESSAGE_COUNT = BATCHES + BATCHES * POSITIONS_PER_BATCH


def batch(sequence: int, template: dict) -> bytes:
    result = copy.deepcopy(template)
    result.update(sequence=sequence, event_id=f"synthetic-session-1:{sequence}")
    payload = result["payload"]
    # A history window may contain many positions; position_reconcile may not.
    payload["reason"] = "reconcile"
    start = 1792652400000 + (sequence - 1) * POSITIONS_PER_BATCH * 1000
    payload["window"] = {
        "from_server_msc": str(start),
        "to_server_msc": str(start + POSITIONS_PER_BATCH * 1000),
    }
    deals, orders = [], []
    for offset in range(POSITIONS_PER_BATCH):
        index = (sequence - 1) * POSITIONS_PER_BATCH + offset
        position = 600000000000000001 + index * 2
        for side in range(2):
            deal = copy.deepcopy(template["payload"]["deals"]["items"][side])
            order = copy.deepcopy(template["payload"]["orders"]["items"][side])
            deal.update(
                ticket=str(700000000000000001 + index * 2 + side),
                order_id=str(position + side),
                position_id=str(position),
                magic_number=str(11122 + index % 5),
            )
            if side:
                deal["profit"] = (-10, 0, 10)[index % 3]
            order.update(
                ticket=str(position + side),
                position_id=str(position),
                magic_number=deal["magic_number"],
            )
            timestamp = str(start + offset * 1000 + side * 500)
            deal["time_msc"] = timestamp
            order.update(setup_time_msc=timestamp, done_time_msc=timestamp)
            deals.append(deal)
            orders.append(order)
    payload["deals"].update(total=len(deals), items=deals)
    payload["orders"].update(total=len(orders), items=orders)
    return json.dumps(result).encode()


def messages(template: dict) -> Iterator[bytes]:
    for sequence in range(1, BATCHES + 1):
        yield batch(sequence, template)
    # Like Activity, reconcile each position separately after history windows.
    sequence = BATCHES
    for batch_number in range(1, BATCHES + 1):
        history = json.loads(batch(batch_number, template))
        for offset in range(POSITIONS_PER_BATCH):
            sequence += 1
            result = copy.deepcopy(history)
            result.update(sequence=sequence, event_id=f"synthetic-session-1:{sequence}")
            result["payload"]["reason"] = "position_reconcile"
            for entity in ("deals", "orders"):
                rows = history["payload"][entity]["items"][offset * 2 : offset * 2 + 2]
                result["payload"][entity].update(total=2, items=rows)
            yield json.dumps(result).encode()


def main() -> None:
    fixture = CentralApiTest()
    queue = None
    started = time.perf_counter()
    try:
        fixture.setUp()
        template = json.loads(
            (ROOT / "tests/fixtures/telemetry_v2/activity-position-reconcile.json").read_bytes()
        )
        path = fixture.root / "synthetic-outbox.sqlite3"
        create_relay_database(path)
        queue = RelayQueue(path)
        producer = RelayProducer(
            "v2",
            "synthetic-activity",
            "demo",
            ProducerRole.ACTIVITY,
            ProducerIdentity("****1234", "DEMO-SERVER", "USD"),
            "http://127.0.0.1:1/v2/telemetry",
            "synthetic-load-probe-local-key",
            fixture.settings.v2_activity,
        )
        ingress = RelayIngress(queue, (producer,))
        for body in messages(template):
            fixture.assertTrue(
                ingress.accept("v2", body, f"Bearer {producer.local_token}", now=1)[0]
            )
        fixture.assertEqual(queue.status(now=1)["states"], {"pending": MESSAGE_COUNT})
        enqueued = time.perf_counter()
        print("Backlog sintético persistido; probando reapertura y ACK perdido.", flush=True)
        queue.close()
        queue = RelayQueue(path)
        ingress = RelayIngress(queue, (producer,))

        class Transport:
            lose_first_ack = True

            def send(self, producer: RelayProducer, body: bytes) -> tuple[int, str, bytes]:
                response = fixture.client.post(
                    "/v2/telemetry",
                    content=body,
                    headers={
                        "Authorization": f"Bearer {producer.central_token}",
                        "Content-Type": "application/json",
                    },
                )
                fixture.assertIn(response.status_code, (200, 202), response.text[:200])
                if self.lose_first_ack:
                    self.lose_first_ack = False
                    raise OSError("synthetic lost ACK after central commit")
                return response.status_code, response.headers["content-type"], response.content

        forwarder = RelayForwarder(queue, (producer,), transport=Transport())
        forwarder.run_once(now=10)
        fixture.assertEqual(queue.status(now=10)["states"], {"pending": MESSAGE_COUNT})
        for sequence in range(MESSAGE_COUNT):
            forwarder.run_once(now=1000 + sequence * 1000)
        fixture.assertEqual(queue.status(now=100000)["states"], {"acked": MESSAGE_COUNT})
        fixture.assertEqual(queue.status(now=100000)["pending_bytes"], 0)
        for body in messages(template):
            fixture.assertFalse(
                ingress.accept("v2", body, f"Bearer {producer.local_token}", now=100000)[0]
            )
        delivered = time.perf_counter()

        def count(path: str, params: dict[str, str | int]) -> int:
            total = 0
            seen_cursors = set()
            while True:
                response = fixture.client.get(
                    path,
                    params=params,
                    headers={"Authorization": f"Bearer {fixture.settings.v2_read}"},
                )
                fixture.assertEqual(response.status_code, 200, response.text[:200])
                page = response.json()
                total += len(page["items"])
                cursor = page["next_cursor"]
                if cursor is None:
                    return total
                fixture.assertNotIn(cursor, seen_cursors)
                seen_cursors.add(cursor)
                params = {**params, "cursor": cursor}

        counts = {}
        for entity in ("deal", "order"):
            counts[entity] = count(
                "/v2/activity",
                {
                    "entity": entity,
                    "from_msc": 1792000000000,
                    "to_msc": 1793000000000,
                    "limit": 100,
                },
            )
            fixture.assertEqual(counts[entity], BATCHES * POSITIONS_PER_BATCH * 2)
        counts["closed_cycles"] = count(
            "/v2/position-cycles", {"closed_only": "true", "limit": 100}
        )
        fixture.assertEqual(counts["closed_cycles"], BATCHES * POSITIONS_PER_BATCH)
        print(
            json.dumps(
                {
                    "result": "OK",
                    "history_batches": BATCHES,
                    "messages": MESSAGE_COUNT,
                    **counts,
                    "enqueue_seconds": round(enqueued - started, 3),
                    "forward_and_replay_seconds": round(delivered - enqueued, 3),
                    "total_seconds": round(time.perf_counter() - started, 3),
                    "queue_file_bytes": path.stat().st_size,
                    "scope": "isolated SQLite + ASGI; no MT5 or real HTTP load",
                },
                indent=2,
            ),
            flush=True,
        )
    finally:
        if queue is not None:
            queue.close()
        fixture.doCleanups()


if __name__ == "__main__":
    main()

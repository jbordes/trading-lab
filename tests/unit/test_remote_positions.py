"""Financial reconstruction through normal admission, without a position message."""

import json
import sqlite3
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from test_telemetry_v2_sqlite import ACTIVITY_CREDENTIAL, IDENTITY, directory, fixture

from tradinglab.telemetry.admission_v2 import ProducerRole
from tradinglab.telemetry.central_schema import MULTI_SCHEMA
from tradinglab.telemetry.remote_activity_upgrade import upgrade
from tradinglab.telemetry.sqlite_store_v2 import open_v2_registry


class RemotePositionsTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "central.sqlite3"
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(MULTI_SCHEMA)
        self.now = datetime(2026, 10, 22, 9, tzinfo=UTC)
        with open_v2_registry(self.path) as store:
            store.register_account("account-demo", "Demo", IDENTITY, created_at=self.now)
            store.register_source(
                "synthetic-activity", "account-demo", ProducerRole.ACTIVITY, created_at=self.now
            )
        self.sample = fixture("activity-position-reconcile")
        self.start, self.end = (
            int(d["time_msc"]) for d in self.sample["payload"]["deals"]["items"]
        )
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO mt5_accounts VALUES (?,?,?,?,?,?)",
                ("account-demo", "Broker", "1234", "demo", self.start // 1000, 0),
            )

    def send(self, seq, start, end, indices):
        msg = fixture("activity-position-reconcile")
        msg.update(sequence=seq, event_id=f"synthetic-session-1:{seq}")
        payload = msg["payload"]
        payload.update(
            reason="recovery", window=dict(from_server_msc=str(start), to_server_msc=str(end))
        )
        for name in ("orders", "deals"):
            rows = [self.sample["payload"][name]["items"][i] for i in indices]
            payload[name] = dict(status="complete", total=len(rows), items=rows)
        envelope = directory().authorize(json.dumps(msg).encode(), f"Bearer {ACTIVITY_CREDENTIAL}")
        with open_v2_registry(self.path) as store:
            store.store_authorized(envelope, received_at=self.now)

    def test_upgrade_with_close_first_waits_for_empty_gap_then_deduplicates(self):
        self.send(3, self.end - 10, self.end, [1])
        self.assertEqual(upgrade(self.path), (9, 10))
        self.assertEqual(upgrade(self.path, apply=True), (9, 10))
        self.send(1, self.start, self.start + 60000, [0])
        with open_v2_registry(self.path) as store:
            self.assertFalse(store.position_cycles("account-demo").items)
        self.send(2, self.start + 60000, self.end - 10, [])
        self.send(4, self.end - 10, self.end, [1])
        with open_v2_registry(self.path) as store:
            items = store.position_cycles("account-demo", closed_only=True).items
            self.assertEqual(len(items), 1)
            self.assertEqual(str(items[0].cycle.observed_net_result), "9.8")
            self.assertEqual(items[0].details["close_price"], 4210)
            self.assertEqual(store.position_cycle_magics("account-demo"), ("11122",))
        self.assertEqual(upgrade(self.path, apply=True), (10, 10))

    def test_same_capture_preserves_distinct_windows_for_both_consumers(self):
        upgrade(self.path, apply=True)
        middle = (self.start + self.end) // 2
        self.send(1, self.start, middle, [0])
        self.send(2, middle + 1, self.end, [1])
        with open_v2_registry(self.path) as store:
            for entity in ("deal", "order"):
                report = store.coverage_report(
                    "account-demo", entity, from_msc=self.start, to_msc=self.end + 1
                )
                self.assertEqual(report.complete_ranges, ((str(self.start), str(self.end)),))
            self.assertEqual(len(store.position_cycles("account-demo").items), 1)

    def test_pending_order_placed_before_cutoff_and_partial_closes(self):
        upgrade(self.path, apply=True)
        deals = self.sample["payload"]["deals"]["items"]
        orders = self.sample["payload"]["orders"]["items"]
        orders[0]["setup_time_msc"] = str(self.start - 86400000)
        deals[0]["volume"] = orders[0]["volume_initial"] = 0.02
        orders[1]["done_time_msc"] = orders[1]["setup_time_msc"] = str(self.start + 10)
        deals[1]["time_msc"] = str(self.start + 10)
        self.send(1, self.start, self.start + 10, [0, 1])
        with open_v2_registry(self.path) as store:
            self.assertFalse(store.position_cycles("account-demo", closed_only=True).items)
        exit_ticket = str(int(orders[1]["ticket"]) + 1)
        deals.append(
            deals[1]
            | {
                "time_msc": str(self.start + 20),
                "ticket": str(int(deals[1]["ticket"]) + 1),
                "order_id": exit_ticket,
            }
        )
        orders.append(
            orders[1]
            | {
                "ticket": exit_ticket,
                "setup_time_msc": str(self.start + 20),
                "done_time_msc": str(self.start + 20),
            }
        )
        self.send(2, self.start + 10, self.start + 20, [2])
        with open_v2_registry(self.path) as store:
            page = store.position_cycles("account-demo", closed_only=True)
            self.assertEqual(len(page.items), 1)
            self.assertEqual(len(page.items[0].cycle.deal_tickets), 3)
            self.assertEqual(page.items[0].details["volume"], 0.02)

    def test_fills_before_cutoff_exclude_legacy_and_raw_cycles(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE mt5_accounts SET history_from=?", (self.start // 1000 + 1,))
        upgrade(self.path, apply=True)
        with open_v2_registry(self.path) as store:
            authorized = directory().authorize(
                json.dumps(self.sample).encode(), f"Bearer {ACTIVITY_CREDENTIAL}"
            )
            store.store_authorized(authorized, received_at=self.now)
            self.assertFalse(store.position_cycles("account-demo").items)
            self.assertFalse(store.position_cycle_magics("account-demo"))

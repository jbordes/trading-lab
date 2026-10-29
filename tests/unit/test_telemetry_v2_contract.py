from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from tradinglab.telemetry.contract import MAX_BODY_BYTES, TelemetryValidationError, parse_envelope
from tradinglab.telemetry.contract_v2 import parse_envelope_v2

FIXTURES = Path(__file__).parents[1] / "fixtures" / "telemetry_v2"


def fixture(name: str = "activity-canceled-order") -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def encoded(value: Any) -> bytes:
    return json.dumps(value).encode()


class TelemetryV2ContractTest(unittest.TestCase):
    def test_live_rows_preserve_v1_rules_and_explicit_truncation(self) -> None:
        value = fixture("live-empty")
        row = {
            "ticket": "18446744073709551615",
            "magic_number": "-11122",
            "symbol": "XAUUSD",
            "comment": "synthetic",
            "volume": 0.01,
            "price_open": 4200,
            "price_current": 4201,
            "stop_loss": 0,
            "take_profit": 0,
            "order_type": 3,
            "created_at_msc": "1792656000000",
        }
        value["payload"].update(orders=[row], orders_total=2)
        result = parse_envelope_v2(encoded(value))
        self.assertEqual(result.payload["orders_total"], 2)
        self.assertEqual(len(result.payload["orders"]), 1)
        for total in (0, True, -1):
            value["payload"]["orders_total"] = total
            with self.assertRaises(TelemetryValidationError):
                parse_envelope_v2(encoded(value))
        value["payload"]["orders_total"] = 2
        value["payload"]["orders"].append(copy.deepcopy(row))
        with self.assertRaises(TelemetryValidationError):
            parse_envelope_v2(encoded(value))

    def test_all_design_fixtures_round_trip_and_are_rejected_by_v1(self) -> None:
        for path in sorted(FIXTURES.glob("*.json")):
            with self.subTest(path=path.name):
                body = path.read_bytes()
                result = parse_envelope_v2(body)
                self.assertEqual(result.as_dict(), json.loads(body))
                self.assertEqual(parse_envelope_v2(result.canonical_bytes()), result)
                with self.assertRaises(TelemetryValidationError):
                    parse_envelope(body)

    def test_v1_still_accepts_original_shape_and_v2_rejects_it(self) -> None:
        value = fixture("live-empty")
        value["schema_version"] = "mt5-telemetry-v1"
        value["kind"] = "account_snapshot"
        value["payload"]["account"].update(value["payload"].pop("identity"))
        self.assertEqual(parse_envelope(encoded(value)).kind, "account_snapshot")
        with self.assertRaises(TelemetryValidationError):
            parse_envelope_v2(encoded(value))

    def test_cancellation_preserves_identifiers_without_inventing_a_deal(self) -> None:
        result = parse_envelope_v2(encoded(fixture()))
        self.assertEqual(result.payload["deals"], {"status": "complete", "total": 0, "items": []})
        order = result.payload["orders"]["items"][0]
        self.assertEqual(order["ticket"], "900000000000000001")
        self.assertEqual(order["position_id"], "0")
        self.assertEqual(order["state"], 2)

    def test_rejects_missing_and_extra_fields_at_each_object_boundary(self) -> None:
        cases = [
            ("live-empty", ()),
            ("live-empty", ("payload",)),
            ("live-empty", ("payload", "identity")),
            ("live-empty", ("payload", "account")),
            ("heartbeat", ("payload",)),
            ("activity-canceled-order", ("payload",)),
            ("activity-canceled-order", ("payload", "window")),
            ("activity-canceled-order", ("payload", "orders")),
            ("activity-canceled-order", ("payload", "orders", "items", 0)),
            ("activity-truncated", ("payload", "deals", "items", 0)),
        ]
        for name, path in cases:
            original = fixture(name)
            obj = original
            for key in path:
                obj = obj[key]
            for field in [*obj, "unexpected"]:
                value = copy.deepcopy(original)
                target = value
                for key in path:
                    target = target[key]
                if field == "unexpected":
                    target[field] = 0
                else:
                    del target[field]
                with self.subTest(name=name, path=path, field=field):
                    with self.assertRaises(TelemetryValidationError):
                        parse_envelope_v2(encoded(value))

    def test_rejects_malformed_json_unicode_depth_size_and_duplicate_keys(self) -> None:
        body = encoded(fixture())
        cases = [
            b"",
            b"\xff",
            b"[",
            b"null",
            b"[]",
            b" " * (MAX_BODY_BYTES + 1),
            b'{"x":1,"x":2}',
            b"[" * 1200 + b"0" + b"]" * 1200,
            body.replace(b"DEMO-SERVER", b"\\ud800"),
            body.replace(b'"state": 2', b'"state": NaN'),
        ]
        for candidate in cases:
            with self.subTest(body=candidate[:30]), self.assertRaises(TelemetryValidationError):
                parse_envelope_v2(candidate)

    def test_rejects_wrong_types_and_ranges_without_leaking_python_errors(self) -> None:
        changes = [
            (("sequence",), True),
            (("sequence",), 0),
            (("sequence",), 2**63),
            (("event_id",), "wrong:1"),
            (("kind",), []),
            (("kind",), "account_snapshot"),
            (("captured_at",), "2026-10-22T08:00:01"),
            (("source_id",), "bad source"),
            (("payload",), []),
            (("payload", "reason"), {}),
            (("payload", "identity"), None),
            (("payload", "identity", "login_masked"), "1234"),
            (("payload", "window", "to_server_msc"), "-0"),
            (("payload", "window", "from_server_msc"), "999999999999999999999"),
            (("payload", "orders", "status"), []),
            (("payload", "orders", "items"), {}),
            (("payload", "orders", "items", 0), []),
            (("payload", "orders", "items", 0, "ticket"), 1),
            (("payload", "orders", "items", 0, "state"), True),
            (("payload", "orders", "items", 0, "state"), 10),
            (("payload", "orders", "items", 0, "order_type"), 9),
            (("payload", "orders", "items", 0, "volume_current"), 0.02),
            (("payload", "orders", "items", 0, "volume_initial"), -1),
            (("payload", "orders", "items", 0, "price_open"), float("inf")),
            (("payload", "orders", "items", 0, "comment"), "x" * 257),
        ]
        for path, replacement in changes:
            value = fixture()
            target = value
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            with self.subTest(path=path, value=replacement):
                with self.assertRaises(TelemetryValidationError):
                    parse_envelope_v2(encoded(value))

    def test_collection_status_count_rules(self) -> None:
        for status, total, rows in [
            ("complete", 0, 1),
            ("complete", True, 1),
            ("error", 0, 0),
            ("error", None, 1),
            ("truncated", 1, 1),
            ("truncated", 1, 0),
            ("other", 1, 1),
            ("complete", 201, 201),
        ]:
            value = fixture()
            collection = value["payload"]["orders"]
            collection.update(status=status, total=total, items=collection["items"] * rows)
            with self.subTest(status=status, total=total, rows=rows):
                with self.assertRaises(TelemetryValidationError):
                    parse_envelope_v2(encoded(value))

    def test_window_is_inclusive_and_setup_can_precede_window(self) -> None:
        value = fixture()
        window = value["payload"]["window"]
        for timestamp in (window["from_server_msc"], window["to_server_msc"]):
            value["payload"]["orders"]["items"][0]["done_time_msc"] = timestamp
            parse_envelope_v2(encoded(value))
        for timestamp in (
            str(int(window["from_server_msc"]) - 1),
            str(int(window["to_server_msc"]) + 1),
        ):
            value["payload"]["orders"]["items"][0]["done_time_msc"] = timestamp
            with self.assertRaises(TelemetryValidationError):
                parse_envelope_v2(encoded(value))
        for delta in (-1, 86_400_001):
            value = fixture()
            window = value["payload"]["window"]
            window["to_server_msc"] = str(int(window["from_server_msc"]) + delta)
            with self.assertRaises(TelemetryValidationError):
                parse_envelope_v2(encoded(value))
        value = fixture()
        row = value["payload"]["orders"]["items"][0]
        row["setup_time_msc"] = str(int(row["done_time_msc"]) + 1)
        with self.assertRaises(TelemetryValidationError):
            parse_envelope_v2(encoded(value))

    def test_deal_rows_use_exact_millisecond_window_and_preserve_costs(self) -> None:
        value = fixture("activity-truncated")
        result = parse_envelope_v2(encoded(value))
        self.assertEqual(result.payload["deals"]["items"][0]["commission"], -0.1)
        row = value["payload"]["deals"]["items"][0]
        for field, replacement in [
            ("time_msc", "1792656060001"),
            ("volume", -1),
            ("entry", 4),
            ("deal_type", 18),
            ("symbol", None),
            ("magic_number", "01"),
            ("fee", True),
        ]:
            original = row[field]
            row[field] = replacement
            with self.subTest(field=field), self.assertRaises(TelemetryValidationError):
                parse_envelope_v2(encoded(value))
            row[field] = original

    def test_duplicate_tickets_rejected_but_same_timestamp_distinct_tickets_allowed(self) -> None:
        for name, entity in [
            ("activity-canceled-order", "orders"),
            ("activity-truncated", "deals"),
        ]:
            value = fixture(name)
            collection = value["payload"][entity]
            collection.update(status="complete", total=2)
            collection["items"].append(copy.deepcopy(collection["items"][0]))
            with self.assertRaises(TelemetryValidationError):
                parse_envelope_v2(encoded(value))
            collection["items"][1]["ticket"] = "18446744073709551615"
            parse_envelope_v2(encoded(value))

    def test_position_reconcile_requires_one_complete_position_lifecycle(self) -> None:
        original = fixture("activity-position-reconcile")
        result = parse_envelope_v2(encoded(original))
        self.assertEqual(result.payload["reason"], "position_reconcile")
        self.assertGreater(
            int(result.payload["window"]["to_server_msc"])
            - int(result.payload["window"]["from_server_msc"]),
            86_400_000,
        )

        changes = []
        value = copy.deepcopy(original)
        value["payload"]["deals"]["status"] = "truncated"
        changes.append(value)
        value = copy.deepcopy(original)
        value["payload"]["deals"].update(status="complete", total=0, items=[])
        changes.append(value)
        value = copy.deepcopy(original)
        value["payload"]["deals"]["items"][1]["position_id"] = "99"
        changes.append(value)
        value = copy.deepcopy(original)
        value["payload"]["deals"]["items"][1]["volume"] = 0.005
        changes.append(value)
        value = copy.deepcopy(original)
        value["payload"]["deals"]["items"][1]["deal_type"] = 2
        changes.append(value)
        value = copy.deepcopy(original)
        value["payload"]["orders"]["items"][0]["ticket"] = "99"
        changes.append(value)
        value = copy.deepcopy(original)
        value["payload"]["orders"]["items"][1]["position_id"] = "99"
        changes.append(value)
        for candidate in changes:
            with self.subTest(candidate=candidate), self.assertRaises(TelemetryValidationError):
                parse_envelope_v2(encoded(candidate))

    def test_heartbeat_counts_and_live_numbers_are_strict(self) -> None:
        for name, group, field in [
            ("heartbeat", (), "queued_messages"),
            ("heartbeat", (), "dropped_messages"),
            ("live-empty", ("account",), "equity"),
        ]:
            for invalid in (True, "1", None, float("nan"), 10**400):
                value = fixture(name)
                target = value["payload"]
                for key in group:
                    target = target[key]
                target[field] = invalid
                with self.subTest(name=name, field=field, invalid=invalid):
                    with self.assertRaises(TelemetryValidationError):
                        parse_envelope_v2(encoded(value))
        value = fixture("live-empty")
        value["payload"]["history"] = {}
        with self.assertRaises(TelemetryValidationError):
            parse_envelope_v2(encoded(value))

    def test_activity_heartbeat_accepts_strict_progress(self) -> None:
        value = fixture("heartbeat")
        value["payload"]["activity_progress"] = {
            "recent_cursor_msc": "1793260800000",
            "deep_cursor_msc": "1767225600000",
            "backlog_msc": "26035200000",
            "recent_blocked": False,
            "deep_blocked": False,
            "deep_paused": True,
            "queued_hints": 0,
            "dropped_hints": 0,
            "last_transaction_age_ms": "2500",
            "latest_deal_ticket": "2690316619",
            "latest_order_ticket": "2690316618",
            "latest_position_id": "12345",
        }
        parsed = parse_envelope_v2(encoded(value))
        self.assertEqual(parsed.payload["activity_progress"]["latest_position_id"], "12345")

        for field, invalid in (
            ("recent_blocked", 0),
            ("deep_paused", 0),
            ("queued_hints", True),
            ("deep_cursor_msc", 1),
        ):
            candidate = copy.deepcopy(value)
            candidate["payload"]["activity_progress"][field] = invalid
            with self.subTest(field=field), self.assertRaises(TelemetryValidationError):
                parse_envelope_v2(encoded(candidate))

    def test_activity_pagination_uses_strict_composite_cursors(self) -> None:
        value = fixture("activity-truncated")
        deal = value["payload"]["deals"]["items"][0]
        value["payload"]["deals"] = {
            "status": "partial",
            "total": 2,
            "items": [deal],
        }
        value["payload"]["orders"] = {
            "status": "partial",
            "total": 0,
            "items": [],
        }
        value["payload"]["pagination"] = {
            "snapshot_id": "p:1792656000000:1792656060000:2:0",
            "after": {"time_msc": "0", "entity_type": "deal", "ticket": "0"},
            "through": {
                "time_msc": deal["time_msc"],
                "entity_type": "deal",
                "ticket": deal["ticket"],
            },
            "has_more": True,
        }
        parsed = parse_envelope_v2(encoded(value))
        self.assertTrue(parsed.payload["pagination"]["has_more"])

        for mutation in ("bad_status", "bad_through", "bad_boolean"):
            candidate = copy.deepcopy(value)
            if mutation == "bad_status":
                candidate["payload"]["orders"]["status"] = "paged_complete"
            elif mutation == "bad_through":
                candidate["payload"]["pagination"]["through"]["ticket"] = "1"
            else:
                candidate["payload"]["pagination"]["has_more"] = 1
            with self.subTest(mutation=mutation), self.assertRaises(TelemetryValidationError):
                parse_envelope_v2(encoded(candidate))


if __name__ == "__main__":
    unittest.main()

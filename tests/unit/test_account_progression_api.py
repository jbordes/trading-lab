from __future__ import annotations

import io
import json
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import test_central_api as central_fixture
from test_mt5_telemetry import encoded, snapshot_message

from tradinglab.dashboard.snapshot import DashboardReadError
from tradinglab.dashboard.telemetry import LoopbackTelemetryClient
from tradinglab.telemetry.contract import TelemetryValidationError, parse_envelope


class AccountProgressionApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = central_fixture.CentralApiTest(
            "test_openapi_and_docs_have_real_request_response_and_security_models"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client = self.fixture.client
        self.settings = self.fixture.settings
        self.read = {"Authorization": f"Bearer {self.settings.account_read}"}

    def test_optional_broker_stamp_is_backward_compatible_and_validated(self) -> None:
        message = snapshot_message()
        parse_envelope(encoded(message))
        for value in ("300000", "1790812800000"):
            message["captured_at"] = datetime.fromtimestamp(int(value) / 1000, UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            message["payload"]["server_time_msc"] = value
            parse_envelope(encoded(message))
        for value in ("0", "0300000", "300001", -1, "NaN", "9999999999999999999"):
            message["payload"]["server_time_msc"] = value
            with self.subTest(value=value), self.assertRaises(TelemetryValidationError):
                parse_envelope(encoded(message))

    def test_authorization_range_and_old_snapshots_without_anchor(self) -> None:
        route = "/api/accounts/progression?source_id=demo-terminal-01&from_server_msc=0&to_server_msc=240000"
        self.assertEqual(self.client.get(route).status_code, 401)
        other = {"Authorization": f"Bearer {self.settings.trading_read}"}
        self.assertEqual(self.client.get(route, headers=other).status_code, 401)
        self.assertEqual(
            self.client.get(
                route.replace("demo-terminal-01", "other"), headers=self.read
            ).status_code,
            403,
        )
        response = self.client.get(route, headers=self.read)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["balance_status"], "missing_anchor")
        self.assertEqual(response.json()["status"], "partial")
        self.assertEqual(
            self.client.get(route + "&source_id=demo-terminal-01", headers=self.read).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(route.replace("240000", "0"), headers=self.read).status_code, 400
        )

    def test_real_ledger_replay_deduplicates_and_broker_anchor_reconstructs(self) -> None:
        fixture_path = (
            Path(__file__).parents[1] / "fixtures/telemetry_v2/activity-canceled-order.json"
        )
        activity = json.loads(fixture_path.read_text(encoding="utf-8"))
        activity["payload"]["window"] = {"from_server_msc": "0", "to_server_msc": "400000"}
        activity["payload"]["orders"] = {"status": "complete", "total": 0, "items": []}
        deal = {
            "ticket": "1",
            "order_id": "1",
            "position_id": "1",
            "magic_number": "11122",
            "time_msc": "1000",
            "deal_type": 1,
            "entry": 1,
            "symbol": "TEST",
            "volume": 1,
            "price": 10,
            "profit": 10,
            "commission": -1,
            "swap": 0,
            "fee": 0,
        }
        activity["payload"]["deals"] = {"status": "complete", "total": 1, "items": [deal]}
        headers = {"Authorization": f"Bearer {self.settings.activity_ingest}"}
        for status in (202, 200):
            response = self.client.post("/api/trading-events", json=activity, headers=headers)
            self.assertEqual(response.status_code, status, response.text)
        snapshot = snapshot_message()
        snapshot["captured_at"] = "1970-01-01T00:05:00Z"
        snapshot["payload"]["server_time_msc"] = "300000"
        snapshot["payload"]["account"]["balance"] = 109
        response = self.client.post(
            "/api/account-state",
            json=snapshot,
            headers={"Authorization": f"Bearer {self.settings.snapshot_ingest}"},
        )
        self.assertEqual(response.status_code, 202, response.text)
        route = "/api/accounts/progression?source_id=demo-terminal-01&from_server_msc=0&to_server_msc=240000"
        response = self.client.get(route, headers=self.read)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["balance_status"], "available")
        self.assertEqual(result["points"][-1]["balance"], 109)
        self.assertEqual(result["points"][-1]["realized_pnl"], 9)
        self.assertNotIn("equity", result["points"][-1])

    def test_read_failure_is_no_successful_empty_history(self) -> None:
        from tradinglab.telemetry.sqlite_store_v2 import V2StorageError

        with patch(
            "tradinglab.telemetry.central_api.read_account_progression",
            side_effect=V2StorageError("private path"),
        ):
            response = self.client.get(
                "/api/accounts/progression?source_id=demo-terminal-01&from_server_msc=0&to_server_msc=240000",
                headers=self.read,
            )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private path", response.text)

    def test_dashboard_client_validates_new_response_and_keeps_broker_time(self) -> None:
        route = "/api/accounts/progression?source_id=demo-terminal-01&from_server_msc=0&to_server_msc=240000"
        payload = self.client.get(route, headers=self.read).json()
        read_key = self.settings.account_read
        adapter = LoopbackTelemetryClient(
            token=read_key,
            source_id="demo-terminal-01",
            port=8782,
            central_api=True,
        )
        with patch.object(
            adapter._opener, "open", return_value=io.BytesIO(json.dumps(payload).encode())
        ) as opened:
            result = adapter.account_progression(from_msc=0, to_msc=240000)
        self.assertEqual(result["time_basis"], "broker_wall_clock")
        self.assertIn("/api/accounts/progression?", opened.call_args.args[0].full_url)
        self.assertIn("from_server_msc=0", opened.call_args.args[0].full_url)
        for field, value in (
            ("source_id", "other-source"),
            ("from_server_msc", 1),
            ("points", [payload["points"][0]] * 481),
        ):
            invalid = deepcopy(payload)
            invalid[field] = value
            with (
                self.subTest(field=field),
                patch.object(
                    adapter._opener, "open", return_value=io.BytesIO(json.dumps(invalid).encode())
                ),
            ):
                with self.assertRaises(DashboardReadError):
                    adapter.account_progression(from_msc=0, to_msc=240000)


if __name__ == "__main__":
    unittest.main()

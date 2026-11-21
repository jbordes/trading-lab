import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tradinglab.multi_catalog import central_app, valid_credential
from tradinglab.telemetry.central_schema import create_central_database
from tradinglab.telemetry.remote_host import CENTRAL_KEYS


class MultiCatalogTest(unittest.TestCase):
    def test_relay_resolves_registered_identity_per_server_and_role(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "central.sqlite3"
            create_central_database(database, multicuenta=True)
            keys = {
                name: f"fixture-{name}-" + "x" * 32 for name in (*CENTRAL_KEYS, "admin", "pairing")
            }
            admin = {"Authorization": f"Bearer {keys['admin']}"}
            with TestClient(
                central_app(database, keys, "localhost"), base_url="http://localhost"
            ) as api:
                pair = api.post("/pair/relay/" + "a" * 32, headers=admin)
                self.assertEqual(pair.status_code, 200)
                activity = {"Authorization": "Bearer " + pair.json()["trading-events"]}
                terminal = "b" * 32
                terminal_route = "/pair/terminal/" + "a" * 32 + "/" + terminal
                self.assertEqual(api.post(terminal_route, headers=activity).status_code, 401)
                tokens = api.post(terminal_route, headers=admin).json()
                self.assertTrue(
                    valid_credential(
                        tokens["trading-events"],
                        pair.json()["trading-events"],
                        "mt5/trading-events",
                    )
                )
                self.assertFalse(
                    valid_credential(
                        tokens["account-state"], pair.json()["trading-events"], "mt5/trading-events"
                    )
                )
                route = "/resolve/trading-events"
                identity = {"server": "Broker-A", "login": "123456", "mode": "demo"}
                missing = api.post(route, json=identity, headers=activity)
                self.assertEqual(missing.status_code, 404)
                self.assertEqual(missing.headers["X-TradingLab-Reason"], "empty_catalog")
                account_ids = []
                for server in ("Broker-A", "Broker-B"):
                    observed = identity | {"server": server}
                    registration = observed | dict(
                        label=server, currency="USD", history_from=1, broker_offset=0
                    )
                    added = api.post("/catalog", json=registration, headers=admin)
                    self.assertEqual(added.status_code, 200)
                    account_id = added.json()["account_id"]
                    resolved = api.post(route, json=observed, headers=activity)
                    self.assertEqual(resolved.status_code, 200)
                    self.assertEqual(resolved.json()["account_id"], account_id)
                    account_ids.append(account_id)
                self.assertNotEqual(*account_ids)
                raw = api.post(route + "-raw", json=identity, headers=activity)
                self.assertEqual(raw.status_code, 200)
                self.assertEqual(raw.json()["account_id"], account_ids[0])
                self.assertEqual(
                    api.post(route, json=identity, headers=activity).json()["account_id"],
                    account_ids[0],
                )
                for changes, reason in (
                    ({"login": "123457"}, "identity_not_registered"),
                    ({"mode": "real"}, "mode_mismatch"),
                ):
                    missing = api.post(route, json=identity | changes, headers=activity)
                    self.assertEqual(missing.status_code, 404)
                    self.assertEqual(missing.headers["X-TradingLab-Reason"], reason)
                wrong_role = api.post("/resolve/account-state", json=identity, headers=activity)
                self.assertEqual(wrong_role.status_code, 401)

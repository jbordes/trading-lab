from __future__ import annotations

import runpy
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tradinglab.telemetry.central_api import CentralSettings, create_central_app

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_HOST = "mac.example.ts.net"
PUBLIC_ORIGIN = f"https://{PUBLIC_HOST}"


class CentralOriginPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = CentralSettings(
            Path("unused.sqlite3"),
            "snapshot",
            "account",
            *(f"synthetic-origin-credential-number-{index}" for index in range(5)),
            allowed_hosts=("localhost", "127.0.0.1", PUBLIC_HOST),
            public_origins=(PUBLIC_ORIGIN,),
        )
        # No context manager: no lifespan, SQLite, operational services or sockets.
        self.client = TestClient(
            create_central_app(self.settings), base_url=f"http://{PUBLIC_HOST}"
        )
        self.addCleanup(self.client.close)

    def test_public_https_origin_works_over_internal_http_without_enabling_cors(self) -> None:
        response = self.client.get("/docs", headers={"Origin": PUBLIC_ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_explicit_origin_also_works_when_proxy_rewrites_host_to_loopback(self) -> None:
        response = self.client.get(
            "/docs", headers={"Origin": PUBLIC_ORIGIN, "Host": "127.0.0.1:8781"}
        )
        self.assertEqual(response.status_code, 200)

    def test_loopback_requires_exact_scheme_host_and_port(self) -> None:
        for host in ("localhost:8781", "127.0.0.1:8781"):
            with self.subTest(host=host):
                headers = {"Host": host, "Origin": f"http://{host}"}
                self.assertEqual(self.client.get("/docs", headers=headers).status_code, 200)
                headers["Origin"] = headers["Origin"].replace(":8781", ":8782")
                self.assertEqual(self.client.get("/docs", headers=headers).status_code, 403)

    def test_public_host_does_not_implicitly_authorize_origin(self) -> None:
        client = TestClient(
            create_central_app(replace(self.settings, public_origins=())),
            base_url=f"http://{PUBLIC_HOST}",
        )
        self.addCleanup(client.close)
        self.assertEqual(client.get("/docs", headers={"Origin": PUBLIC_ORIGIN}).status_code, 403)
        self.assertEqual(client.get("/docs").status_code, 200)

    def test_https_default_port_is_equivalent_but_nondefault_ports_are_not(self) -> None:
        self.assertEqual(
            self.client.get("/docs", headers={"Origin": PUBLIC_ORIGIN + ":443"}).status_code, 200
        )
        self.assertEqual(
            self.client.get("/docs", headers={"Origin": PUBLIC_ORIGIN + ":8443"}).status_code, 403
        )
        client = TestClient(
            create_central_app(replace(self.settings, public_origins=(PUBLIC_ORIGIN + ":8443",))),
            base_url=f"http://{PUBLIC_HOST}",
        )
        self.addCleanup(client.close)
        self.assertEqual(
            client.get("/docs", headers={"Origin": PUBLIC_ORIGIN + ":8443"}).status_code, 200
        )
        self.assertEqual(client.get("/docs", headers={"Origin": PUBLIC_ORIGIN}).status_code, 403)

    def test_foreign_malformed_and_downgraded_origins_are_rejected(self) -> None:
        for origin in (
            "https://attacker.invalid",
            f"http://{PUBLIC_HOST}",
            "null",
            "",
            PUBLIC_ORIGIN + "/",
            PUBLIC_ORIGIN + "?x=1",
            PUBLIC_ORIGIN + "#fragment",
            PUBLIC_ORIGIN + ":0443",
            PUBLIC_ORIGIN + ":0",
            PUBLIC_ORIGIN + ":65536",
            PUBLIC_ORIGIN + ":",
            f"https://user@{PUBLIC_HOST}",
            PUBLIC_ORIGIN + ".attacker.invalid",
            PUBLIC_ORIGIN + ",https://attacker.invalid",
            PUBLIC_ORIGIN + " https://attacker.invalid",
            PUBLIC_ORIGIN + "\t",
            "https://mac%2eexample.ts.net",
            "https://MAC.example.ts.net",
        ):
            with self.subTest(origin=origin):
                response = self.client.get("/docs", headers={"Origin": origin})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"error": "origin_not_allowed"})
                self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_duplicate_origin_and_host_headers_are_rejected(self) -> None:
        self.assertEqual(
            self.client.get(
                "/docs", headers=[("Origin", PUBLIC_ORIGIN), ("Origin", PUBLIC_ORIGIN)]
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                "/docs", headers=[("Host", PUBLIC_HOST), ("Host", PUBLIC_HOST)]
            ).status_code,
            400,
        )

    def test_forwarded_headers_do_not_authorize_an_unconfigured_origin(self) -> None:
        response = self.client.get(
            "/docs",
            headers={
                "Origin": "https://attacker.invalid",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "attacker.invalid",
                "Forwarded": "host=attacker.invalid;proto=https",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_allowed_origin_does_not_bypass_host_or_bearer_authentication(self) -> None:
        self.assertEqual(
            self.client.get(
                "/docs", headers={"Origin": PUBLIC_ORIGIN, "Host": "attacker.invalid"}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/account-state", json={}, headers={"Origin": PUBLIC_ORIGIN}
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api/account-state",
                json={},
                headers={
                    "Origin": PUBLIC_ORIGIN,
                    "Authorization": "Bearer synthetic-wrong-credential",
                },
            ).status_code,
            401,
        )

    def test_invalid_public_origin_configuration_is_rejected(self) -> None:
        for origins in (
            ("http://mac.example.ts.net",),
            ("*",),
            ("https://*.example.ts.net",),
            ("https://attacker.invalid",),
            (PUBLIC_ORIGIN + "/",),
            ("null",),
            (PUBLIC_ORIGIN, PUBLIC_ORIGIN + ":443"),
            (PUBLIC_ORIGIN + ":0443",),
        ):
            with self.subTest(origins=origins), self.assertRaises(ValueError):
                replace(self.settings, public_origins=origins)

    def test_cli_passes_explicit_origin_without_trusting_proxy_headers(self) -> None:
        with patch.object(sys, "path", [str(ROOT / "scripts"), *sys.path]):
            main = runpy.run_path(str(ROOT / "scripts/central_api.py"))["main"]
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("pathlib.Path.is_file", return_value=True),
            patch("tradinglab.telemetry.operational_job.exclusive_job_lock"),
            patch(
                "tradinglab.telemetry.central_api.CentralSettings", return_value=self.settings
            ) as settings,
            patch("uvicorn.run") as run,
        ):
            result = main(
                [
                    "--db",
                    str(ROOT / "unused.sqlite3"),
                    "--source-id",
                    "snapshot",
                    "--account-id",
                    "account",
                    "--allowed-host",
                    PUBLIC_HOST,
                    "--public-origin",
                    PUBLIC_ORIGIN,
                ]
            )
        self.assertEqual(result, 0)
        self.assertEqual(settings.call_args.kwargs["public_origins"], (PUBLIC_ORIGIN,))
        self.assertEqual(run.call_args.kwargs["host"], "127.0.0.1")
        self.assertFalse(run.call_args.kwargs["proxy_headers"])


if __name__ == "__main__":
    unittest.main()

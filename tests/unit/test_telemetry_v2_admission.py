from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradinglab.telemetry.admission_v2 import (
    ProducerIdentity,
    ProducerRegistration,
    ProducerRole,
    V2AuthenticationError,
    V2AuthorizationError,
    V2ProducerDirectory,
)
from tradinglab.telemetry.contract import TelemetryValidationError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "telemetry_v2"
LIVE_TOKEN = "synthetic-live-token-with-safe-length"
ACTIVITY_TOKEN = "synthetic-activity-token-safe-length"
IDENTITY = ProducerIdentity("****1234", "DEMO-SERVER", "USD")


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def encoded(value: object) -> bytes:
    return json.dumps(value).encode()


def registration(
    role: ProducerRole,
    *,
    account_id: str = "account-demo",
    source_id: str | None = None,
    token: str | None = None,
    identity: ProducerIdentity = IDENTITY,
) -> ProducerRegistration:
    return ProducerRegistration(
        account_id=account_id,
        source_id=source_id or f"synthetic-{role.value}",
        role=role,
        identity=identity,
        token=token or (LIVE_TOKEN if role is ProducerRole.LIVE else ACTIVITY_TOKEN),
    )


def directory() -> V2ProducerDirectory:
    return V2ProducerDirectory(
        (registration(ProducerRole.LIVE), registration(ProducerRole.ACTIVITY))
    )


class ProducerDirectoryTest(unittest.TestCase):
    def test_authorizes_each_role_and_returns_internal_account(self) -> None:
        cases = (
            ("live-empty", LIVE_TOKEN, ProducerRole.LIVE),
            ("activity-canceled-order", ACTIVITY_TOKEN, ProducerRole.ACTIVITY),
            ("heartbeat", LIVE_TOKEN, ProducerRole.LIVE),
        )
        for name, token, role in cases:
            with self.subTest(name=name):
                result = directory().authorize(encoded(fixture(name)), f"Bearer {token}")
                self.assertEqual(result.account_id, "account-demo")
                self.assertEqual(result.role, role)

    def test_authenticates_before_parsing_and_never_echoes_token(self) -> None:
        secret = "secret-producer-token-safe-length"
        target = V2ProducerDirectory((registration(ProducerRole.LIVE, token=secret),))
        for authorization in (
            "",
            "Basic value",
            "Bearer wrong-token-with-safe-length",
            "Bearer é" + "x" * 24,
            "Bearer " + "x" * 513,
        ):
            with self.subTest(authorization=authorization):
                with self.assertRaises(V2AuthenticationError) as raised:
                    target.authorize(b"not json", authorization)
                self.assertNotIn(secret, str(raised.exception))
        with self.assertRaises(TelemetryValidationError):
            target.authorize(b"not json", f"Bearer {secret}")

    def test_rejects_crossed_source_role_and_identity(self) -> None:
        cases: list[tuple[str, str, tuple[str, ...], object]] = [
            ("live-empty", ACTIVITY_TOKEN, (), None),
            ("activity-canceled-order", LIVE_TOKEN, (), None),
            ("live-empty", LIVE_TOKEN, ("source_id",), "synthetic-activity"),
            ("live-empty", LIVE_TOKEN, ("payload", "identity", "server"), "OTHER"),
            ("live-empty", LIVE_TOKEN, ("payload", "identity", "currency"), "EUR"),
            ("live-empty", LIVE_TOKEN, ("payload", "identity", "login_masked"), "****9999"),
        ]
        for name, token, path, replacement in cases:
            value = fixture(name)
            if path:
                target = value
                for key in path[:-1]:
                    target = target[key]  # type: ignore[index]
                target[path[-1]] = replacement  # type: ignore[index]
            with self.subTest(name=name, path=path):
                with self.assertRaises(V2AuthorizationError):
                    directory().authorize(encoded(value), f"Bearer {token}")

    def test_activity_heartbeat_is_allowed_only_for_its_source(self) -> None:
        value = fixture("heartbeat")
        value["source_id"] = "synthetic-activity"
        result = directory().authorize(encoded(value), f"Bearer {ACTIVITY_TOKEN}")
        self.assertEqual(result.role, ProducerRole.ACTIVITY)
        with self.assertRaises(V2AuthorizationError):
            directory().authorize(encoded(value), f"Bearer {LIVE_TOKEN}")

    def test_registration_is_strict_unique_and_hides_secret(self) -> None:
        live = registration(ProducerRole.LIVE)
        self.assertNotIn(LIVE_TOKEN, repr(live))
        invalid = (
            (),
            (live, live),
            (live, registration(ProducerRole.ACTIVITY, source_id=live.source_id)),
            (live, registration(ProducerRole.ACTIVITY, token=LIVE_TOKEN)),
            (live, registration(ProducerRole.LIVE, source_id="other-live", token="y" * 24)),
        )
        for registrations in invalid:
            with self.subTest(registrations=len(registrations)), self.assertRaises(ValueError):
                V2ProducerDirectory(registrations)

    def test_registration_values_are_validated(self) -> None:
        for change in (
            {"account_id": "bad account"},
            {"source_id": "bad source"},
            {"role": "live"},
            {"token": "short"},
            {"token": "x" * 24 + " "},
            {"token": "é" * 24},
        ):
            values = {
                "account_id": "account-demo",
                "source_id": "synthetic-live",
                "role": ProducerRole.LIVE,
                "identity": IDENTITY,
                "token": LIVE_TOKEN,
            }
            values.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                ProducerRegistration(**values)  # type: ignore[arg-type]
        for values in (
            ("1234", "SERVER", "USD"),
            ("****1234", "", "USD"),
            ("****1234", "SERVER", ""),
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                ProducerIdentity(*values)


if __name__ == "__main__":
    unittest.main()

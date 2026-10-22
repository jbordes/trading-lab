from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tradinglab.telemetry.admission_v2 import (
    AdmissionDisposition,
    InMemoryV2Admission,
    ProducerIdentity,
    ProducerRegistration,
    ProducerRole,
    V2AuthenticationError,
    V2AuthorizationError,
    V2ConflictError,
    V2ProducerDirectory,
    V2StaleSequenceError,
)
from tradinglab.telemetry.contract import TelemetryValidationError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "telemetry_v2"
LIVE_CREDENTIAL = "synthetic-live-token-with-safe-length"
ACTIVITY_CREDENTIAL = "synthetic-activity-token-safe-length"
IDENTITY = ProducerIdentity("****1234", "DEMO-SERVER", "USD")


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def encoded(value: object) -> bytes:
    return json.dumps(value).encode()


def message(name: str, sequence: int, *, session_id: str = "synthetic-session-1") -> bytes:
    value = fixture(name)
    value["session_id"] = session_id
    value["sequence"] = sequence
    value["event_id"] = f"{session_id}:{sequence}"
    return encoded(value)


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
        token=token or (LIVE_CREDENTIAL if role is ProducerRole.LIVE else ACTIVITY_CREDENTIAL),
    )


def directory() -> V2ProducerDirectory:
    return V2ProducerDirectory(
        (registration(ProducerRole.LIVE), registration(ProducerRole.ACTIVITY))
    )


class ProducerDirectoryTest(unittest.TestCase):
    def test_authorizes_each_role_and_returns_internal_account(self) -> None:
        cases = (
            ("live-empty", LIVE_CREDENTIAL, ProducerRole.LIVE),
            ("activity-canceled-order", ACTIVITY_CREDENTIAL, ProducerRole.ACTIVITY),
            ("heartbeat", LIVE_CREDENTIAL, ProducerRole.LIVE),
        )
        for name, token, role in cases:
            with self.subTest(name=name):
                result = directory().authorize(encoded(fixture(name)), f"Bearer {token}")
                self.assertEqual(result.account_id, "account-demo")
                self.assertEqual(result.role, role)

    def test_authenticates_before_parsing_and_never_echoes_token(self) -> None:
        sample_credential = "synthetic-producer-token-safe-length"
        target = V2ProducerDirectory((registration(ProducerRole.LIVE, token=sample_credential),))
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
                self.assertNotIn(sample_credential, str(raised.exception))
        with self.assertRaises(TelemetryValidationError):
            target.authorize(b"not json", f"Bearer {sample_credential}")

    def test_rejects_crossed_source_role_and_identity(self) -> None:
        cases: list[tuple[str, str, tuple[str, ...], object]] = [
            ("live-empty", ACTIVITY_CREDENTIAL, (), None),
            ("activity-canceled-order", LIVE_CREDENTIAL, (), None),
            ("live-empty", LIVE_CREDENTIAL, ("source_id",), "synthetic-activity"),
            ("live-empty", LIVE_CREDENTIAL, ("payload", "identity", "server"), "OTHER"),
            ("live-empty", LIVE_CREDENTIAL, ("payload", "identity", "currency"), "EUR"),
            (
                "live-empty",
                LIVE_CREDENTIAL,
                ("payload", "identity", "login_masked"),
                "****9999",
            ),
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
        result = directory().authorize(encoded(value), f"Bearer {ACTIVITY_CREDENTIAL}")
        self.assertEqual(result.role, ProducerRole.ACTIVITY)
        with self.assertRaises(V2AuthorizationError):
            directory().authorize(encoded(value), f"Bearer {LIVE_CREDENTIAL}")

    def test_registration_is_strict_unique_and_hides_secret(self) -> None:
        live = registration(ProducerRole.LIVE)
        self.assertNotIn(LIVE_CREDENTIAL, repr(live))
        invalid = (
            (),
            (live, live),
            (live, registration(ProducerRole.ACTIVITY, source_id=live.source_id)),
            (live, registration(ProducerRole.ACTIVITY, token=LIVE_CREDENTIAL)),
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
            }
            values["token"] = LIVE_CREDENTIAL
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


class InMemoryAdmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.target = InMemoryV2Admission(directory())

    def test_exact_retry_is_duplicate_even_with_different_json_formatting(self) -> None:
        value = fixture("live-empty")
        compact = json.dumps(value, separators=(",", ":")).encode()
        pretty = json.dumps(value, indent=2).encode()

        accepted = self.target.admit(compact, f"Bearer {LIVE_CREDENTIAL}")
        duplicate = self.target.admit(pretty, f"Bearer {LIVE_CREDENTIAL}")

        self.assertEqual(accepted.disposition, AdmissionDisposition.ACCEPTED)
        self.assertEqual(duplicate.disposition, AdmissionDisposition.DUPLICATE)
        self.assertEqual(accepted.content_sha256, duplicate.content_sha256)

    def test_same_identity_with_different_content_is_conflict(self) -> None:
        self.target.admit(message("live-empty", 1), f"Bearer {LIVE_CREDENTIAL}")
        changed = fixture("live-empty")
        changed["captured_at"] = "2026-10-22T08:00:02Z"

        with self.assertRaises(V2ConflictError):
            self.target.admit(encoded(changed), f"Bearer {LIVE_CREDENTIAL}")

    def test_live_stream_rejects_unknown_older_sequence_and_reports_gap(self) -> None:
        accepted = self.target.admit(message("live-empty", 3), f"Bearer {LIVE_CREDENTIAL}")
        self.assertEqual(accepted.sequence_gap, 2)
        self.assertFalse(accepted.out_of_order)

        with self.assertRaises(V2StaleSequenceError):
            self.target.admit(message("live-empty", 1), f"Bearer {LIVE_CREDENTIAL}")

    def test_activity_accepts_unknown_older_sequence_without_lowering_watermark(self) -> None:
        newest = self.target.admit(
            message("activity-canceled-order", 3), f"Bearer {ACTIVITY_CREDENTIAL}"
        )
        recovered = self.target.admit(
            message("activity-canceled-order", 1), f"Bearer {ACTIVITY_CREDENTIAL}"
        )
        next_message = self.target.admit(
            message("activity-canceled-order", 4), f"Bearer {ACTIVITY_CREDENTIAL}"
        )

        self.assertEqual(newest.sequence_gap, 2)
        self.assertTrue(recovered.out_of_order)
        self.assertEqual(recovered.sequence_gap, 0)
        self.assertEqual(next_message.sequence_gap, 0)

    def test_heartbeat_remains_strict_for_both_roles(self) -> None:
        first = fixture("heartbeat")
        first["source_id"] = "synthetic-activity"
        first["sequence"] = 2
        first["event_id"] = "synthetic-session-1:2"
        self.target.admit(encoded(first), f"Bearer {ACTIVITY_CREDENTIAL}")
        older = first | {"sequence": 1, "event_id": "synthetic-session-1:1"}

        with self.assertRaises(V2StaleSequenceError):
            self.target.admit(encoded(older), f"Bearer {ACTIVITY_CREDENTIAL}")

    def test_identical_concurrent_requests_have_one_acceptance(self) -> None:
        body = message("activity-canceled-order", 1)

        def submit(_: int) -> AdmissionDisposition:
            return self.target.admit(body, f"Bearer {ACTIVITY_CREDENTIAL}").disposition

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(submit, range(16)))

        self.assertEqual(results.count(AdmissionDisposition.ACCEPTED), 1)
        self.assertEqual(results.count(AdmissionDisposition.DUPLICATE), 15)

    def test_bounded_retention_discards_in_memory_idempotency_by_session(self) -> None:
        target = InMemoryV2Admission(directory(), max_retained_messages=1)
        first = message("activity-canceled-order", 1, session_id="session-a")
        second = message("activity-canceled-order", 1, session_id="session-b")
        target.admit(first, f"Bearer {ACTIVITY_CREDENTIAL}")
        target.admit(second, f"Bearer {ACTIVITY_CREDENTIAL}")

        retried = target.admit(first, f"Bearer {ACTIVITY_CREDENTIAL}")

        self.assertEqual(retried.disposition, AdmissionDisposition.ACCEPTED)

    def test_configuration_and_rejected_auth_do_not_change_admission(self) -> None:
        for value in (0, True, 100_001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                InMemoryV2Admission(directory(), max_retained_messages=value)
        with self.assertRaises(V2AuthenticationError):
            self.target.admit(message("live-empty", 5), "Bearer invalid-safe-length-token")

        accepted = self.target.admit(message("live-empty", 1), f"Bearer {LIVE_CREDENTIAL}")
        self.assertEqual(accepted.sequence_gap, 0)


if __name__ == "__main__":
    unittest.main()

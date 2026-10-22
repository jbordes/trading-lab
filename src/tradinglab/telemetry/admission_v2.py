"""Explicit producer authorization and in-memory admission for telemetry v2."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from enum import StrEnum

from tradinglab.telemetry.contract import IDENTIFIER, MASKED_ACCOUNT, TelemetryEnvelope
from tradinglab.telemetry.contract_v2 import parse_envelope_v2

MIN_TOKEN_LENGTH = 24
MAX_TOKEN_LENGTH = 512


class ProducerRole(StrEnum):
    LIVE = "live"
    ACTIVITY = "activity"


class V2AdmissionError(RuntimeError):
    """Base error for authenticated telemetry admission."""


class V2AuthenticationError(V2AdmissionError):
    """The supplied credential does not identify a configured producer."""


class V2AuthorizationError(V2AdmissionError):
    """The authenticated producer cannot emit this message."""


@dataclass(frozen=True, slots=True)
class ProducerIdentity:
    login_masked: str
    server: str
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.login_masked, str) or not MASKED_ACCOUNT.fullmatch(
            self.login_masked
        ):
            raise ValueError("login_masked no está enmascarado")
        for value, limit, label in (
            (self.server, 128, "server"),
            (self.currency, 16, "currency"),
        ):
            if not isinstance(value, str) or not value or len(value) > limit:
                raise ValueError(f"{label} inválido")

    def matches(self, payload: object) -> bool:
        return payload == {
            "login_masked": self.login_masked,
            "server": self.server,
            "currency": self.currency,
        }


@dataclass(frozen=True, slots=True)
class ProducerRegistration:
    account_id: str
    source_id: str
    role: ProducerRole
    identity: ProducerIdentity
    token: str = field(repr=False)

    def __post_init__(self) -> None:
        for value, label in ((self.account_id, "account_id"), (self.source_id, "source_id")):
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise ValueError(f"{label} inválido")
        if not isinstance(self.role, ProducerRole):
            raise ValueError("role inválido")
        _validate_token(self.token)


@dataclass(frozen=True, slots=True)
class AuthorizedEnvelope:
    account_id: str
    role: ProducerRole
    envelope: TelemetryEnvelope


@dataclass(frozen=True, slots=True)
class _Producer:
    account_id: str
    source_id: str
    role: ProducerRole
    identity: ProducerIdentity
    authorization_digest: bytes


class V2ProducerDirectory:
    """Authenticate a configured producer and authorize its v2 message role."""

    def __init__(self, registrations: tuple[ProducerRegistration, ...]) -> None:
        if not registrations:
            raise ValueError("Se requiere al menos un productor")
        sources: set[str] = set()
        account_roles: set[tuple[str, ProducerRole]] = set()
        digests: set[bytes] = set()
        producers: list[_Producer] = []
        for registration in registrations:
            if not isinstance(registration, ProducerRegistration):
                raise ValueError("Registro de productor inválido")
            digest = _authorization_digest(registration.token)
            account_role = (registration.account_id, registration.role)
            if registration.source_id in sources:
                raise ValueError("source_id de productor duplicado")
            if account_role in account_roles:
                raise ValueError("Solo se admite un productor primario por cuenta y rol")
            if digest in digests:
                raise ValueError("Cada productor requiere una credencial distinta")
            sources.add(registration.source_id)
            account_roles.add(account_role)
            digests.add(digest)
            producers.append(
                _Producer(
                    account_id=registration.account_id,
                    source_id=registration.source_id,
                    role=registration.role,
                    identity=registration.identity,
                    authorization_digest=digest,
                )
            )
        self._producers = tuple(producers)

    def authorize(self, body: bytes, authorization: str) -> AuthorizedEnvelope:
        """Authenticate before parsing, then validate source, role and MT5 identity."""

        producer = self._authenticate(authorization)
        envelope = parse_envelope_v2(body)
        allowed_kind = {
            ProducerRole.LIVE: "live_snapshot",
            ProducerRole.ACTIVITY: "activity_batch",
        }[producer.role]
        if (
            envelope.source_id != producer.source_id
            or envelope.kind not in {allowed_kind, "heartbeat"}
            or not producer.identity.matches(envelope.payload.get("identity"))
        ):
            raise V2AuthorizationError("El productor no está autorizado para el mensaje")
        return AuthorizedEnvelope(
            account_id=producer.account_id,
            role=producer.role,
            envelope=envelope,
        )

    def _authenticate(self, authorization: str) -> _Producer:
        if (
            not isinstance(authorization, str)
            or not authorization.isascii()
            or not authorization.startswith("Bearer ")
            or len(authorization) > len("Bearer ") + MAX_TOKEN_LENGTH
        ):
            raise V2AuthenticationError("Credencial de productor inválida")
        candidate = hashlib.sha256(authorization.encode("ascii")).digest()
        match: _Producer | None = None
        for producer in self._producers:
            if hmac.compare_digest(candidate, producer.authorization_digest):
                match = producer
        if match is None:
            raise V2AuthenticationError("Credencial de productor inválida")
        return match


def _validate_token(token: object) -> None:
    if (
        not isinstance(token, str)
        or not MIN_TOKEN_LENGTH <= len(token) <= MAX_TOKEN_LENGTH
        or not token.isascii()
        or any(not 33 <= ord(character) <= 126 for character in token)
    ):
        raise ValueError("Token de productor inválido")


def _authorization_digest(token: str) -> bytes:
    return hashlib.sha256(f"Bearer {token}".encode("ascii")).digest()

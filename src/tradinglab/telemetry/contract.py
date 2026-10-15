"""Validation for the small, versioned MT5 telemetry wire contract."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "mt5-telemetry-v1"
MAX_BODY_BYTES = 256 * 1024
MAX_STRING_LENGTH = 512
MAX_COLLECTION_ITEMS = 1_000
MAX_NESTING_DEPTH = 6

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MASKED_ACCOUNT = re.compile(r"^\*{4}[0-9]{1,8}$")
ALLOWED_KINDS = {"heartbeat", "account_snapshot"}
ALLOWED_REASONS = {"startup", "timer", "trade_activity"}

ACCOUNT_FIELDS = {
    "login_masked",
    "server",
    "currency",
    "balance",
    "equity",
    "profit",
    "margin",
    "margin_free",
    "margin_level",
}


class TelemetryValidationError(ValueError):
    """Raised when untrusted telemetry does not satisfy the wire contract."""


@dataclass(frozen=True, slots=True)
class TelemetryEnvelope:
    """Validated telemetry message independent of transport and persistence."""

    schema_version: str
    collector_version: str
    source_id: str
    session_id: str
    sequence: int
    event_id: str
    captured_at: str
    kind: str
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "collector_version": self.collector_version,
            "source_id": self.source_id,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "event_id": self.event_id,
            "captured_at": self.captured_at,
            "kind": self.kind,
            "payload": self.payload,
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")


def parse_envelope(body: bytes) -> TelemetryEnvelope:
    """Decode and validate one untrusted telemetry body."""

    if not body:
        raise TelemetryValidationError("El cuerpo está vacío")
    if len(body) > MAX_BODY_BYTES:
        raise TelemetryValidationError("El cuerpo supera el límite permitido")
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TelemetryValidationError("El cuerpo no es JSON UTF-8 válido") from exc
    if not isinstance(document, dict):
        raise TelemetryValidationError("El mensaje debe ser un objeto JSON")

    expected = {
        "schema_version",
        "collector_version",
        "source_id",
        "session_id",
        "sequence",
        "event_id",
        "captured_at",
        "kind",
        "payload",
    }
    _require_exact_fields(document, expected, "mensaje")

    schema_version = _required_string(document, "schema_version")
    if schema_version != SCHEMA_VERSION:
        raise TelemetryValidationError(f"Schema no admitido: {schema_version}")

    collector_version = _identifier(document, "collector_version")
    source_id = _identifier(document, "source_id")
    session_id = _identifier(document, "session_id")
    event_id = _identifier(document, "event_id")
    sequence = document["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise TelemetryValidationError("sequence debe ser un entero positivo")

    captured_at = _utc_timestamp(document["captured_at"])
    kind = _required_string(document, "kind")
    if kind not in ALLOWED_KINDS:
        raise TelemetryValidationError(f"Tipo de mensaje no admitido: {kind}")

    payload = document["payload"]
    if not isinstance(payload, dict):
        raise TelemetryValidationError("payload debe ser un objeto")
    _validate_json_value(payload, "payload", depth=0)
    if kind == "heartbeat":
        _validate_heartbeat(payload)
    else:
        _validate_account_snapshot(payload)

    return TelemetryEnvelope(
        schema_version=schema_version,
        collector_version=collector_version,
        source_id=source_id,
        session_id=session_id,
        sequence=sequence,
        event_id=event_id,
        captured_at=captured_at,
        kind=kind,
        payload=payload,
    )


def _validate_heartbeat(payload: dict[str, Any]) -> None:
    _require_exact_fields(payload, {"status"}, "heartbeat")
    if payload["status"] != "ok":
        raise TelemetryValidationError("El heartbeat debe informar status=ok")


def _validate_account_snapshot(payload: dict[str, Any]) -> None:
    _require_exact_fields(
        payload,
        {"reason", "account", "positions_total", "orders_total", "positions", "orders"},
        "snapshot",
    )
    if payload["reason"] not in ALLOWED_REASONS:
        raise TelemetryValidationError("Motivo de snapshot no admitido")

    account = payload["account"]
    if not isinstance(account, dict):
        raise TelemetryValidationError("account debe ser un objeto")
    _require_exact_fields(account, ACCOUNT_FIELDS, "account")
    login_masked = _required_string(account, "login_masked")
    if not MASKED_ACCOUNT.fullmatch(login_masked):
        raise TelemetryValidationError("login_masked no está enmascarado")
    _bounded_string(account, "server", maximum=128)
    _bounded_string(account, "currency", maximum=16)
    for field in ACCOUNT_FIELDS - {"login_masked", "server", "currency"}:
        _finite_number(account[field], f"account.{field}")

    for total_field in ("positions_total", "orders_total"):
        total = payload[total_field]
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise TelemetryValidationError(f"{total_field} debe ser un entero no negativo")

    for collection in ("positions", "orders"):
        rows = payload[collection]
        if not isinstance(rows, list):
            raise TelemetryValidationError(f"{collection} debe ser una lista")
        if len(rows) > MAX_COLLECTION_ITEMS:
            raise TelemetryValidationError(f"{collection} supera el máximo de elementos")
        if len(rows) > payload[f"{collection}_total"]:
            raise TelemetryValidationError(f"{collection} supera el total declarado")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise TelemetryValidationError(f"{collection}[{index}] debe ser un objeto")
            for identifier in ("ticket", "magic_number"):
                if identifier not in row or not isinstance(row[identifier], str):
                    raise TelemetryValidationError(
                        f"{collection}[{index}].{identifier} debe ser texto"
                    )


def _validate_json_value(value: Any, path: str, *, depth: int) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise TelemetryValidationError(f"{path} supera la profundidad permitida")
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
            raise TelemetryValidationError(f"{path} contiene texto demasiado largo")
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        _finite_number(value, path)
        return
    if isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise TelemetryValidationError(f"{path} supera el máximo de elementos")
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]", depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise TelemetryValidationError(f"{path} supera el máximo de campos")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 64:
                raise TelemetryValidationError(f"{path} contiene una clave inválida")
            _validate_json_value(item, f"{path}.{key}", depth=depth + 1)
        return
    raise TelemetryValidationError(f"{path} contiene un tipo JSON no admitido")


def _require_exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing:
        raise TelemetryValidationError(f"Faltan campos en {label}: {', '.join(sorted(missing))}")
    if extra:
        raise TelemetryValidationError(
            f"Campos no admitidos en {label}: {', '.join(sorted(extra))}"
        )


def _required_string(value: dict[str, Any], field: str) -> str:
    item = value[field]
    if not isinstance(item, str) or not item:
        raise TelemetryValidationError(f"{field} debe ser texto no vacío")
    if len(item) > MAX_STRING_LENGTH:
        raise TelemetryValidationError(f"{field} es demasiado largo")
    return item


def _bounded_string(value: dict[str, Any], field: str, *, maximum: int) -> str:
    item = _required_string(value, field)
    if len(item) > maximum:
        raise TelemetryValidationError(f"{field} es demasiado largo")
    return item


def _identifier(value: dict[str, Any], field: str) -> str:
    item = _required_string(value, field)
    if not IDENTIFIER.fullmatch(item):
        raise TelemetryValidationError(f"{field} contiene caracteres no admitidos")
    return item


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TelemetryValidationError(f"{field} debe ser numérico")
    result = float(value)
    if not math.isfinite(result):
        raise TelemetryValidationError(f"{field} debe ser finito")
    return result


def _utc_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise TelemetryValidationError("captured_at debe ser UTC y terminar en Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise TelemetryValidationError("captured_at no es una fecha ISO válida") from exc
    if parsed.tzinfo != UTC:
        raise TelemetryValidationError("captured_at debe estar expresado en UTC")
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")

"""Read-only MT5 diagnostic capture with immutable local evidence."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

SCHEMA_VERSION = "mt5-diagnostic-v1"
MAX_CAPTURE_BYTES = 25 * 1024 * 1024


class DiagnosticError(RuntimeError):
    """Base error for an invalid or failed MT5 diagnostic capture."""


class Mt5InitializationError(DiagnosticError):
    """Raised when the local MT5 terminal cannot be initialized."""


class Mt5IdentityError(DiagnosticError):
    """Raised when MT5 does not match the explicitly authorized identity."""


class Mt5ReadError(DiagnosticError):
    """Raised when an MT5 read operation fails."""


class EvidenceConflictError(DiagnosticError):
    """Raised when an evidence path already contains different content."""


class CaptureValidationError(DiagnosticError):
    """Raised when a capture payload does not satisfy the v1 contract."""


class Mt5Client(Protocol):
    """Small read-only boundary implemented by the MetaTrader5 module."""

    def initialize(self, path: str, *, timeout: int) -> bool: ...

    def shutdown(self) -> None: ...

    def last_error(self) -> object: ...

    def account_info(self) -> object | None: ...

    def terminal_info(self) -> object | None: ...

    def history_orders_get(self, date_from: datetime, date_to: datetime) -> object | None: ...

    def history_deals_get(self, date_from: datetime, date_to: datetime) -> object | None: ...

    def positions_get(self) -> object | None: ...

    def orders_get(self) -> object | None: ...


@dataclass(frozen=True, slots=True)
class CaptureWindow:
    """Inclusive diagnostic window expressed with timezone-aware instants."""

    date_from: datetime
    date_to: datetime

    def __post_init__(self) -> None:
        _require_aware(self.date_from, "date_from")
        _require_aware(self.date_to, "date_to")
        if self.date_from >= self.date_to:
            raise ValueError("date_from debe ser anterior a date_to")


@dataclass(frozen=True, slots=True)
class Mt5TerminalIdentity:
    """Expected terminal and account identity for one isolated diagnostic."""

    terminal_path: Path
    data_path: Path
    account_login: int
    server: str

    def __post_init__(self) -> None:
        if not self.terminal_path.is_absolute() or not self.data_path.is_absolute():
            raise ValueError("Las rutas de identidad MT5 deben ser absolutas")
        if isinstance(self.account_login, bool) or self.account_login <= 0:
            raise ValueError("El login esperado debe ser un entero positivo")
        if not self.server.strip() or any(ord(char) < 32 for char in self.server):
            raise ValueError("El servidor esperado no es válido")


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    """Paths and digest for a completed evidence publication."""

    capture_path: Path
    manifest_path: Path
    sha256: str
    size_bytes: int
    already_existed: bool


def collect_mt5_diagnostic(
    client: Mt5Client,
    window: CaptureWindow,
    *,
    captured_at: datetime,
    identity: Mt5TerminalIdentity,
) -> dict[str, JsonValue]:
    """Collect every read-only MT5 dataset required by the discovery spike."""

    _require_aware(captured_at, "captured_at")
    if not client.initialize(str(identity.terminal_path), timeout=10_000):
        raise Mt5InitializationError(
            f"No se pudo inicializar MT5: {_safe_error(client.last_error())}"
        )

    try:
        account = _read_one(client, "account_info")
        terminal = _read_one(client, "terminal_info")
        _verify_terminal_identity(account, terminal, identity)
        payload: dict[str, JsonValue] = {
            "schema_version": SCHEMA_VERSION,
            "captured_at": _utc_iso(captured_at),
            "window": {
                "date_from": _utc_iso(window.date_from),
                "date_to": _utc_iso(window.date_to),
            },
            "account": account,
            "terminal": terminal,
            "history_orders": _read_many(
                client,
                "history_orders_get",
                window.date_from,
                window.date_to,
            ),
            "history_deals": _read_many(
                client,
                "history_deals_get",
                window.date_from,
                window.date_to,
            ),
            "open_positions": _read_many(client, "positions_get"),
            "active_orders": _read_many(client, "orders_get"),
        }
    finally:
        client.shutdown()

    validate_capture_payload(payload)
    return payload


def write_capture_evidence(
    payload: Mapping[str, JsonValue],
    capture_path: Path,
) -> EvidenceResult:
    """Publish a capture and manifest without overwriting different evidence."""

    validate_capture_payload(payload)
    if capture_path.suffix.lower() != ".json":
        raise ValueError("La captura debe usar extensión .json")
    if capture_path.name.endswith(".manifest.json"):
        raise ValueError("La ruta de captura no puede ser un manifest")

    capture_bytes = _json_bytes(payload)
    if len(capture_bytes) > MAX_CAPTURE_BYTES:
        raise CaptureValidationError(f"La captura supera el límite de {MAX_CAPTURE_BYTES} bytes")
    digest = hashlib.sha256(capture_bytes).hexdigest()
    manifest_path = capture_path.with_name(f"{capture_path.stem}.manifest.json")
    manifest: dict[str, JsonValue] = {
        "schema_version": "mt5-evidence-manifest-v1",
        "capture_file": capture_path.name,
        "capture_schema_version": str(payload["schema_version"]),
        "captured_at": str(payload["captured_at"]),
        "sha256": digest,
        "size_bytes": len(capture_bytes),
    }
    manifest_bytes = _json_bytes(manifest)

    capture_path.parent.mkdir(parents=True, exist_ok=True)
    capture_existed = _create_or_accept_identical(capture_path, capture_bytes)
    try:
        manifest_existed = _create_or_accept_identical(manifest_path, manifest_bytes)
    except Exception:
        if not capture_existed:
            capture_path.unlink(missing_ok=True)
        raise

    return EvidenceResult(
        capture_path=capture_path,
        manifest_path=manifest_path,
        sha256=digest,
        size_bytes=len(capture_bytes),
        already_existed=capture_existed and manifest_existed,
    )


def load_capture_evidence(path: Path) -> dict[str, JsonValue]:
    """Load and validate a bounded JSON capture from a trusted local path."""

    size = path.stat().st_size
    if size > MAX_CAPTURE_BYTES:
        raise CaptureValidationError(f"La captura supera el límite: {size} bytes")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CaptureValidationError(f"No se pudo leer la captura {path.name}") from exc
    if not isinstance(value, dict):
        raise CaptureValidationError("La raíz de la captura debe ser un objeto JSON")
    validate_capture_payload(value)
    return value


def validate_capture_payload(payload: Mapping[str, object]) -> None:
    """Validate the stable top-level contract without assuming broker-specific fields."""

    try:
        _to_json_value(payload)
    except Mt5ReadError as exc:
        raise CaptureValidationError("La captura contiene un valor no admitido") from exc

    required_objects = ("window", "account", "terminal")
    required_lists = ("history_orders", "history_deals", "open_positions", "active_orders")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CaptureValidationError("schema_version no admitido")
    _parse_aware_iso(payload.get("captured_at"), "captured_at")

    for name in required_objects:
        if not isinstance(payload.get(name), dict):
            raise CaptureValidationError(f"{name} debe ser un objeto")
    window = payload["window"]
    if not isinstance(window, dict):
        raise CaptureValidationError("window debe ser un objeto")
    date_from = _parse_aware_iso(window.get("date_from"), "window.date_from")
    date_to = _parse_aware_iso(window.get("date_to"), "window.date_to")
    if date_from >= date_to:
        raise CaptureValidationError("window.date_from debe ser anterior a window.date_to")

    for name in required_lists:
        records = payload.get(name)
        if not isinstance(records, list):
            raise CaptureValidationError(f"{name} debe ser una lista")
        if not all(isinstance(record, dict) for record in records):
            raise CaptureValidationError(f"{name} solo puede contener objetos")


def _read_one(client: Mt5Client, method_name: str) -> dict[str, JsonValue]:
    value = getattr(client, method_name)()
    if value is None:
        raise Mt5ReadError(f"Falló {method_name}: {_safe_error(client.last_error())}")
    converted = _to_json_value(value)
    if not isinstance(converted, dict):
        raise Mt5ReadError(f"{method_name} devolvió un tipo inesperado")
    return converted


def _read_many(client: Mt5Client, method_name: str, *args: datetime) -> list[JsonValue]:
    value = getattr(client, method_name)(*args)
    if value is None:
        raise Mt5ReadError(f"Falló {method_name}: {_safe_error(client.last_error())}")
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Iterable):
        raise Mt5ReadError(f"{method_name} devolvió un tipo inesperado")
    records = [_to_json_value(record) for record in value]
    if not all(isinstance(record, dict) for record in records):
        raise Mt5ReadError(f"{method_name} devolvió registros inesperados")
    return records


def _verify_terminal_identity(
    account: Mapping[str, JsonValue],
    terminal: Mapping[str, JsonValue],
    expected: Mt5TerminalIdentity,
) -> None:
    terminal_path = terminal.get("path")
    data_path = terminal.get("data_path")
    login = account.get("login")
    server = account.get("server")
    matches = (
        isinstance(terminal_path, str)
        and _same_path(Path(terminal_path), expected.terminal_path.parent)
        and isinstance(data_path, str)
        and _same_path(Path(data_path), expected.data_path)
        and isinstance(login, int)
        and not isinstance(login, bool)
        and login == expected.account_login
        and isinstance(server, str)
        and server == expected.server
    )
    if not matches:
        raise Mt5IdentityError("La terminal MT5 no coincide con la identidad esperada")


def _same_path(actual: Path, expected: Path) -> bool:
    return os.path.normcase(os.path.abspath(actual)) == os.path.normcase(os.path.abspath(expected))


def _to_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise Mt5ReadError("MT5 devolvió un número no finito")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        _require_aware(value, "datetime MT5")
        return _utc_iso(value)
    if hasattr(value, "_asdict"):
        return _to_json_value(value._asdict())
    if isinstance(value, Mapping):
        converted: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise Mt5ReadError("MT5 devolvió una clave que no es texto")
            converted[key] = _to_json_value(item)
        return converted
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    raise Mt5ReadError(f"MT5 devolvió un tipo no serializable: {type(value).__name__}")


def _create_or_accept_identical(path: Path, content: bytes) -> bool:
    if path.exists():
        if path.read_bytes() != content:
            raise EvidenceConflictError(f"Ya existe evidencia diferente en {path}")
        return True

    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != content:
            raise EvidenceConflictError(f"Ya existe evidencia diferente en {path}") from None
        return True
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    return False


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} debe incluir zona horaria")


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_aware_iso(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise CaptureValidationError(f"{name} debe ser una fecha ISO 8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CaptureValidationError(f"{name} no es una fecha ISO 8601 válida") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CaptureValidationError(f"{name} debe incluir zona horaria")
    return parsed


def _safe_error(value: object) -> str:
    if isinstance(value, tuple) and len(value) >= 2:
        return f"código={value[0]}, detalle={value[1]}"
    return str(value)

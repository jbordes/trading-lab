"""Generate private MT5 presets from an existing installation, without terminal access."""

from __future__ import annotations

import calendar
import os
import tempfile
from datetime import datetime
from pathlib import Path

from tradinglab.installation import private_directory, read_installation
from tradinglab.installation_backend import LAYOUT
from tradinglab.telemetry.local_secrets import load_local_secrets


class PresetConflict(ValueError):
    """Safe diagnostic containing only installer-owned names."""


def replace_preset(path: Path, encoded: bytes) -> None:
    """Publish the complete generated preset inside its private directory."""
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        except OSError:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def create_presets(
    directory: Path, login: str, history_start: str, *, resume: bool = False
) -> Path:
    config = read_installation(directory)
    if not login.isascii() or not login.isdecimal() or not 0 < int(login) <= 2**63 - 1:
        raise ValueError("Login de MT5 invalido")
    if config.login_masked != "****" + login[-4:]:
        raise ValueError("El login no coincide con la cuenta de la instalacion")
    parsed_start = datetime.strptime(history_start, "%Y.%m.%d %H:%M:%S")
    # MT5 presets store datetime as seconds. Encode broker wall-clock fields
    # without converting them through the OS timezone or the broker UTC offset.
    history_seconds = str(calendar.timegm(parsed_start.timetuple()))
    if history_start < "1970.01.02 00:00:00":
        raise ValueError("Fecha inicial invalida")
    if LAYOUT == "local-dual-v1":
        names = ("TRADINGLAB_TELEMETRY_TOKEN", "TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN")
        file = ".env.local"
        allowed = names + (
            "TRADINGLAB_TELEMETRY_LIVE_TOKEN",
            "TRADINGLAB_TELEMETRY_READ_TOKEN",
            "TRADINGLAB_DASHBOARD_TOKEN",
        )
        paths = ("/v1/telemetry", "/v2/telemetry")
    else:
        names = ("RELAY_LIVE_LOCAL_TOKEN", "RELAY_ACTIVITY_LOCAL_TOKEN")
        file, allowed = ".env.collectors", names
        paths = ("/api/account-state", "/api/trading-events")
    values = load_local_secrets(directory / file, allowed_names=allowed, environment={})
    common = dict(
        ExpectedDemoLogin=login,
        ExpectedDemoServer=config.server,
        AllowRealAccount=str(config.account_mode == "real").lower(),
    )
    presets = [
        dict(
            IngestUrl=f"http://127.0.0.1:{config.snapshot_port}{paths[0]}",
            Token=values[names[0]],
            SourceId=config.snapshot_source_id,
            **common,
        ),
        dict(
            IngestUrl=f"http://127.0.0.1:{config.activity_port}{paths[1]}",
            Token=values[names[1]],
            SourceId=config.activity_source_id,
            HistoryStartServerTime=history_seconds,
            **common,
        ),
    ]
    # Validate all lines before writing: no newline or optimization-delimiter injection.
    for preset in presets:
        for value in preset.values():
            if not value.isprintable() or "||" in value:
                raise ValueError("Valor no representable en un preset MT5")
    destination = directory / "collector-presets"
    if resume and destination.exists():
        if destination.is_symlink() or destination.is_junction() or not destination.is_dir():
            raise ValueError("Destino de presets invalido")
    else:
        private_directory(destination)
    for name, preset in zip(("TradingLabTelemetry", "TradingLabActivity"), presets, strict=True):
        body = "; TradingLab - privado, contiene token. Usar solo con collectors de esta rama.\r\n"
        body += "".join(f"{key}={value}\r\n" for key, value in preset.items())
        path = destination / f"{name}.set"
        encoded = body.encode("utf-16")
        if resume and (path.exists() or path.is_symlink()):
            if path.is_symlink():
                raise PresetConflict(f"{path.name} es un enlace. Revise el destino de presets.")
            existing = path.read_bytes()
            if existing != encoded:
                replace_preset(path, encoded)
            continue
        descriptor = os.open(
            destination / f"{name}.set", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body.encode("utf-16"))
            stream.flush()
            os.fsync(stream.fileno())
    return destination

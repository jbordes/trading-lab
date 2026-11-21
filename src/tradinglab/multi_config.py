"""Versioned host settings and authenticated calls to the configured central API."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal
from urllib import request
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradinglab.telemetry.relay_delivery import unique_json_fields


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api_request(url: str, key: str, payload: dict | None = None):
    opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
    data = json.dumps(payload).encode() if payload is not None else None
    req = request.Request(
        url,
        data=data,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    with opener.open(req, timeout=4) as response:
        body = response.read(65537)
    if len(body) > 65536:
        raise ValueError("Respuesta de API demasiado grande")
    return json.loads(body, object_pairs_hook=unique_json_fields)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[2] = 2
    components: list[Literal["api", "relay", "dashboard"]] = Field(
        default_factory=lambda: ["api", "relay", "dashboard"]
    )
    api_base_url: str = "http://127.0.0.1:8782"
    dashboard_url: str = "http://127.0.0.1:8775/dashboard"
    snapshot_ingest_url: str = "http://127.0.0.1:8776/account-state"
    activity_ingest_url: str = "http://127.0.0.1:8777/trading-events"
    api_listen_port: int | None = Field(default=None, ge=1024, le=65535)
    dashboard_listen_port: int | None = Field(default=None, ge=1024, le=65535)
    data_dir: str
    mt5_data_dir: str = ""

    @field_validator("snapshot_ingest_url", "activity_ingest_url")
    @classmethod
    def normalize_relay_path(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.path in {"/api/account-state", "/api/trading-events"}:
            return value.replace(parts.path, parts.path.removeprefix("/api"), 1)
        return value

    @model_validator(mode="after")
    def check(self):
        if not Path(self.data_dir).is_absolute() or (
            self.mt5_data_dir and not Path(self.mt5_data_dir).is_absolute()
        ):
            raise ValueError("Seleccione carpetas absolutas")
        ports = []
        for role, url, suffix in (
            ("api", self.api_base_url, None),
            ("dashboard", self.dashboard_url, "/dashboard"),
            ("relay", self.snapshot_ingest_url, "/account-state"),
            ("relay", self.activity_ingest_url, "/trading-events"),
        ):
            parts = urlsplit(url)
            if (
                not parts.hostname
                or not url.isascii()
                or any(ord(c) < 33 for c in url)
                or parts.username is not None
                or parts.password is not None
                or parts.query
                or parts.fragment
                or parts.scheme not in ("https", "http")
                or "\\" in url
                or ".." in parts.path.split("/")
                or (suffix and parts.path != suffix)
                or (role == "api" and parts.path.endswith("/"))
                or (parts.scheme == "http" and parts.hostname not in ("127.0.0.1", "localhost"))
            ):
                raise ValueError("URL de servicio inválida: " + role)
            if role == "relay" and (
                parts.scheme != "http" or parts.hostname != "127.0.0.1" or not parts.port
            ):
                raise ValueError("El collector requiere HTTP y 127.0.0.1 con puerto explícito")
            if role in self.components:
                port = parts.port if role == "relay" else self.port(role)
                if port < 1024 or port in ports:
                    raise ValueError("Revise los puertos locales de escucha y del proxy HTTPS")
                ports.append(port)
        if len(set(self.components)) != len(self.components):
            raise ValueError("Componente duplicado")
        return self

    def port(self, role: str) -> int:
        if role == "api":
            url, override, backend = self.api_base_url, self.api_listen_port, 8782
        else:
            url, override, backend = self.dashboard_url, self.dashboard_listen_port, 8775
        parsed = urlsplit(url)
        return override or (backend if parsed.scheme == "https" else parsed.port or 80)


def save_json(path: Path, values: dict) -> None:
    with tempfile.NamedTemporaryFile(
        dir=path.parent, mode="w", encoding="utf-8", delete=False
    ) as stream:
        temp = Path(stream.name)
        try:
            json.dump(values, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

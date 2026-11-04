"""Non-secret relay topology; tokens are referenced by environment variable name."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from tradinglab.telemetry.admission_v2 import ProducerIdentity, ProducerRole
from tradinglab.telemetry.relay import RelayProducer
from tradinglab.telemetry.relay_delivery import unique_json_fields


def relay_rows(path: Path) -> list[dict[str, str]]:
    with path.open("rb") as stream:
        body = stream.read(65_537)
    if len(body) > 65_536:
        raise ValueError("Configuración relay demasiado grande")
    try:
        config = json.loads(body, object_pairs_hook=unique_json_fields)
    except RecursionError as exc:
        raise ValueError("Configuración demasiado anidada") from exc
    if not isinstance(config, list) or not 1 <= len(config) <= 16:
        raise ValueError("Configure una lista de 1..16 productores")
    fields = {
        "version",
        "source_id",
        "account_id",
        "role",
        "login_masked",
        "server",
        "currency",
        "target",
        "local_token_env",
        "central_token_env",
    }
    for row in config:
        if (
            not isinstance(row, dict)
            or set(row) != fields
            or any(not isinstance(value, str) for value in row.values())
        ):
            raise ValueError("Campos de configuración relay inválidos")
        for key in ("local_token_env", "central_token_env"):
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", row[key]):
                raise ValueError("Use nombres de variables, no tokens, en la configuración")
    return config


def relay_token_names(path: Path) -> tuple[str, ...]:
    return tuple(
        row[key] for row in relay_rows(path) for key in ("local_token_env", "central_token_env")
    )


def load_relay_producers(path: Path, environment: Mapping[str, str]) -> tuple[RelayProducer, ...]:
    producers = []
    for row in relay_rows(path):
        local_key = environment.get(row["local_token_env"], "")
        central_key = environment.get(row["central_token_env"], "")
        producers.append(
            RelayProducer(
                version=row["version"],
                source_id=row["source_id"],
                account_id=row["account_id"],
                role=ProducerRole(row["role"]),
                identity=ProducerIdentity(row["login_masked"], row["server"], row["currency"]),
                target=row["target"],
                local_token=local_key,
                central_token=central_key,
            )
        )
    return tuple(producers)

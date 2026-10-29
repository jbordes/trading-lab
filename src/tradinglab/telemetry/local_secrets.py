"""Load an explicitly bounded set of local runtime secrets."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def load_local_secrets(
    path: Path,
    *,
    allowed_names: Iterable[str],
    environment: Mapping[str, str],
) -> dict[str, str]:
    """Merge an optional ignored secrets file without overriding process values."""

    merged = dict(environment)
    if not path.exists():
        return merged
    if not path.is_file():
        raise ValueError(f"El archivo local de secretos no es un archivo: {path}")

    allowed = frozenset(allowed_names)
    loaded: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeError as exc:
        raise ValueError("El archivo local de secretos debe usar UTF-8") from exc

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.fullmatch(line)
        if match is None:
            raise ValueError(f"Línea {line_number} inválida en {path.name}; use NOMBRE=valor")
        name, value = match.groups()
        if name not in allowed:
            raise ValueError(f"Variable no permitida en {path.name}: {name}")
        if name in loaded:
            raise ValueError(f"Variable duplicada en {path.name}: {name}")
        if not value:
            raise ValueError(f"El valor de {name} está vacío en {path.name}")
        loaded.add(name)
        if not merged.get(name):
            merged[name] = value
    return merged

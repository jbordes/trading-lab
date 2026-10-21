"""Safe, explicit first-time provisioning for one local demo telemetry source."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tradinglab.telemetry.contract import IDENTIFIER
from tradinglab.telemetry.sqlite_store import create_database, open_registry

DATABASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.sqlite3\Z")


@dataclass(frozen=True, slots=True)
class ProvisionPlan:
    root: Path
    filename: str
    account_id: str
    label: str
    server: str
    currency: str
    source_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.filename, str) or not DATABASE_NAME.fullmatch(self.filename):
            raise ValueError("Nombre de base inválido; use solo un archivo .sqlite3")
        for value in (self.account_id, self.source_id):
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise ValueError("Identificador de cuenta o fuente inválido")
        for value, limit in ((self.label, 128), (self.server, 128), (self.currency, 16)):
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > limit
                or any(not char.isprintable() for char in value)
            ):
                raise ValueError("Metadatos de cuenta inválidos")

    @property
    def database(self) -> Path:
        storage = self.root.resolve() / "_storage"
        if not storage.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("_storage debe permanecer dentro del checkout")
        return storage / self.filename

    def apply(self, *, clock: datetime | None = None) -> Path:
        """Create one new database and register identities; never replace a file."""
        database = self.database
        stamp = clock or datetime.now(UTC)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("La hora del alta debe incluir zona horaria")
        if database.exists() or database.is_symlink():
            raise FileExistsError("La base ya existe; no se reemplazó ni modificó")
        database.parent.mkdir(exist_ok=True)
        create_database(database)
        with open_registry(database) as registry:
            registry.register_account(
                self.account_id, self.label, self.server, self.currency, created_at=stamp
            )
            registry.register_source(self.source_id, self.account_id, created_at=stamp)
        return database

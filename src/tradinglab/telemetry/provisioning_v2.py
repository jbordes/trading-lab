"""Safe, explicit provisioning for an isolated telemetry v2 pilot database."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tradinglab.telemetry.admission_v2 import ProducerIdentity, ProducerRole
from tradinglab.telemetry.contract import IDENTIFIER
from tradinglab.telemetry.sqlite_store_v2 import create_v2_database, open_v2_registry

DATABASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.sqlite3\Z")


@dataclass(frozen=True, slots=True)
class V2ProvisionPlan:
    root: Path
    filename: str
    account_id: str
    label: str
    identity: ProducerIdentity
    live_source_id: str
    activity_source_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.filename, str) or not DATABASE_NAME.fullmatch(self.filename):
            raise ValueError("Nombre de base inválido; use solo un archivo .sqlite3")
        for value, label in (
            (self.account_id, "account_id"),
            (self.live_source_id, "live_source_id"),
            (self.activity_source_id, "activity_source_id"),
        ):
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise ValueError(f"{label} inválido")
        if self.live_source_id == self.activity_source_id:
            raise ValueError("Cada rol requiere un source_id diferente")
        if not isinstance(self.identity, ProducerIdentity):
            raise ValueError("Identidad MT5 inválida")
        if (
            not isinstance(self.label, str)
            or not self.label.strip()
            or len(self.label) > 128
            or any(not character.isprintable() for character in self.label)
        ):
            raise ValueError("label inválido")

    @property
    def database(self) -> Path:
        root = self.root.resolve()
        storage = root / "_storage"
        if not storage.resolve().is_relative_to(root):
            raise ValueError("_storage debe permanecer dentro del checkout")
        return storage / self.filename

    def apply(self, *, clock: datetime | None = None) -> Path:
        """Create and verify a new database; never replace or migrate a file."""
        database = self.database
        stamp = clock or datetime.now(UTC)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("La hora del alta debe incluir zona horaria")
        if database.exists() or database.is_symlink():
            raise FileExistsError("La base ya existe; no se reemplazó ni modificó")
        database.parent.mkdir(exist_ok=True)
        created = False
        try:
            create_v2_database(database)
            created = True
            with open_v2_registry(database) as registry:
                registry.register_account(
                    self.account_id,
                    self.label,
                    self.identity,
                    created_at=stamp,
                )
                registry.register_source(
                    self.live_source_id,
                    self.account_id,
                    ProducerRole.LIVE,
                    created_at=stamp,
                )
                registry.register_source(
                    self.activity_source_id,
                    self.account_id,
                    ProducerRole.ACTIVITY,
                    created_at=stamp,
                )
            with open_v2_registry(database) as registry:
                evidence = registry.account_evidence(self.account_id)
                expected = {
                    (self.live_source_id, ProducerRole.LIVE),
                    (self.activity_source_id, ProducerRole.ACTIVITY),
                }
                actual = {(source.source_id, source.role) for source in evidence.sources}
                if evidence.identity != self.identity or actual != expected:
                    raise RuntimeError("La base creada no coincide con el plan")
        except BaseException:
            if created and database.exists():
                database.unlink()
            raise
        return database

"""Explicit, non-destructive SQLite online backup for the local telemetry pilot."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tradinglab.telemetry.provisioning import DATABASE_NAME
from tradinglab.telemetry.sqlite_store import SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class BackupResult:
    directory: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class BackupPlan:
    root: Path
    filename: str

    def __post_init__(self) -> None:
        if not isinstance(self.filename, str) or not DATABASE_NAME.fullmatch(self.filename):
            raise ValueError("Nombre de base SQLite inválido")

    @property
    def storage(self) -> Path:
        root = self.root.resolve()
        storage = root / "_storage"
        if not storage.resolve().is_relative_to(root):
            raise ValueError("_storage debe permanecer dentro del checkout")
        return storage

    @property
    def source(self) -> Path:
        path = self.storage / self.filename
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError("La base local no existe o es un enlace")
        return path

    def apply(self, *, clock: datetime | None = None) -> BackupResult:
        """Publish one verified backup package; never overwrite or prune copies.

        A failure can leave a visibly named .tmp-* directory for manual review.
        The source is accessed read-only and may remain open by the receiver.
        """
        source = self.source
        stamp = clock or datetime.now(UTC)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("La hora de la copia debe incluir zona horaria")
        stamp_utc = stamp.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backups = self.storage / "backups"
        if not backups.resolve().is_relative_to(self.storage):
            raise ValueError("El directorio de copias sale de _storage")
        backups.mkdir(exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".tmp-telemetry-", dir=backups))
        copied = temporary / "data.sqlite3"
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as reader:
            if reader.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise ValueError("Versión SQLite de TradingLab no admitida")
            with closing(sqlite3.connect(copied)) as writer:
                writer.execute("PRAGMA synchronous = FULL")
                reader.backup(writer)
                if writer.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("La copia no pasó la comprobación SQLite")
                if writer.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise ValueError("La copia contiene relaciones inválidas")
        digest = hashlib.sha256()
        with copied.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        size = copied.stat().st_size
        manifest = {
            "format": "tradinglab-sqlite-backup-v1",
            "source_file": self.filename,
            "created_at_utc": stamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "database_file": "data.sqlite3",
            "size_bytes": size,
            "sha256": digest.hexdigest(),
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        destination = backups / f"{source.stem}-{stamp_utc}-{digest.hexdigest()[:12]}"
        destination.mkdir()
        copied.rename(destination / "data.sqlite3")
        (temporary / "manifest.json").rename(destination / "manifest.json")
        temporary.rmdir()
        return BackupResult(destination, digest.hexdigest(), size)

"""Small test builders for subsets of the one production central schema."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tradinglab.telemetry.admission_v2 import ProducerIdentity, ProducerRole
from tradinglab.telemetry.central_schema import create_central_database
from tradinglab.telemetry.sqlite_store import open_registry
from tradinglab.telemetry.sqlite_store_v2 import open_v2_registry


@dataclass
class SnapshotTestPlan:
    root: Path
    filename: str
    account_id: str
    label: str
    server: str
    currency: str
    source_id: str

    def apply(self, *, clock: datetime | None = None) -> Path:
        path = self.root / "_storage" / self.filename
        path.parent.mkdir(exist_ok=True)
        create_central_database(path)
        with open_registry(path) as registry:
            stamp = clock or datetime.now(UTC)
            registry.register_account(
                self.account_id,
                self.label,
                self.server,
                self.currency,
                login_masked="****1234",
                created_at=stamp,
            )
            registry.register_source(self.source_id, self.account_id, created_at=stamp)
        return path


@dataclass
class TradingTestPlan:
    root: Path
    filename: str
    account_id: str
    label: str
    identity: ProducerIdentity
    live_source_id: str
    activity_source_id: str
    storage_root: Path | None = None

    def apply(self, *, clock: datetime | None = None) -> Path:
        path = (self.storage_root or self.root / "_storage") / self.filename
        path.parent.mkdir(exist_ok=True)
        create_central_database(path)
        with open_v2_registry(path) as registry:
            stamp = clock or datetime.now(UTC)
            registry.register_account(self.account_id, self.label, self.identity, created_at=stamp)
            for source, role in (
                (self.live_source_id, ProducerRole.LIVE),
                (self.activity_source_id, ProducerRole.ACTIVITY),
            ):
                registry.register_source(source, self.account_id, role, created_at=stamp)
        return path

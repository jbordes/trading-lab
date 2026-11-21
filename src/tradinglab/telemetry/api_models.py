"""Wire schemas for OpenAPI. Domain validators remain authoritative for cross-field rules."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic.json_schema import SkipJsonSchema

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
DecimalText = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,19})$")]
Magic = Annotated[str, Field(pattern=r"^-?(0|[1-9][0-9]{0,18})$")]
Counter = Annotated[int, Field(ge=0, le=2**63 - 1)]
Stamp = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*Z$")]


class WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class Identity(WireModel):
    login_masked: Annotated[str, Field(pattern=r"^\*{4}[0-9]{1,8}$")]
    server: Annotated[str, Field(min_length=1, max_length=128)]
    currency: Annotated[str, Field(min_length=1, max_length=16)]


class Account(WireModel):
    balance: float
    equity: float
    profit: float
    margin: float
    margin_free: float
    margin_level: float


class SnapshotAccount(Account, Identity):
    pass


class LiveRow(WireModel):
    ticket: DecimalText
    magic_number: Magic
    symbol: Annotated[str, Field(min_length=1, max_length=128)]
    comment: Annotated[str, Field(max_length=256)]
    volume: Annotated[float, Field(ge=0)]
    price_open: float
    price_current: float
    stop_loss: float
    take_profit: float


class Position(LiveRow):
    position_id: DecimalText
    operation_type: Annotated[int, Field(ge=0, le=1)]
    profit: float
    swap: float
    opened_at_msc: DecimalText


class LiveOrder(LiveRow):
    order_type: Annotated[int, Field(ge=0, le=8)]
    created_at_msc: DecimalText


class DealValues(WireModel):
    ticket: DecimalText
    order_id: DecimalText
    position_id: DecimalText
    magic_number: Magic
    deal_type: Annotated[int, Field(ge=0, le=17)]
    entry: Annotated[int, Field(ge=0, le=3)]
    symbol: Annotated[str, Field(max_length=128)]
    volume: Annotated[float, Field(ge=0)]
    price: float
    profit: float
    commission: float
    swap: float
    fee: float


class Deal(DealValues):
    time_msc: DecimalText


class HistoryOrder(WireModel):
    ticket: DecimalText
    magic_number: Magic
    symbol: Annotated[str, Field(min_length=1, max_length=128)]
    order_type: Annotated[int, Field(ge=0, le=8)]
    state: Annotated[int, Field(ge=0, le=9)]
    volume_initial: Annotated[float, Field(ge=0)]
    volume_current: Annotated[float, Field(ge=0)]
    price_open: float
    stop_loss: float
    take_profit: float
    setup_time_msc: DecimalText
    done_time_msc: DecimalText
    position_id: DecimalText
    position_by_id: DecimalText
    comment: Annotated[str, Field(max_length=256)]


class SnapshotDealHistory(WireModel):
    status: Literal["complete", "truncated", "error"]
    from_server_seconds: DecimalText
    to_server_seconds: DecimalText
    total: Counter
    deals: Annotated[list[Deal], Field(max_length=200)]


class AccountStateSnapshotPayload(WireModel):
    server_time_msc: DecimalText | SkipJsonSchema[None] = None
    reason: Literal["startup", "timer", "trade_activity"]
    account: SnapshotAccount
    positions_total: Counter
    orders_total: Counter
    positions: Annotated[list[Position], Field(max_length=1000)]
    orders: Annotated[list[LiveOrder], Field(max_length=1000)]
    history: SnapshotDealHistory | SkipJsonSchema[None] = None


class Envelope(WireModel):
    collector_version: Identifier
    source_id: Identifier
    session_id: Identifier
    sequence: Annotated[int, Field(ge=1, le=2**63 - 1)]
    event_id: Identifier
    captured_at: Stamp


class AccountHeartbeatPayload(WireModel):
    status: Literal["ok"]


class AccountHeartbeat(Envelope):
    schema_version: Literal["mt5-account-state-v1"]
    kind: Literal["heartbeat"]
    payload: AccountHeartbeatPayload


class AccountStateSnapshot(Envelope):
    schema_version: Literal["mt5-account-state-v1"]
    kind: Literal["account_snapshot"]
    payload: AccountStateSnapshotPayload


class LivePayload(WireModel):
    reason: Literal["startup", "timer", "trade_activity"]
    identity: Identity
    account: Account
    positions_total: Counter
    orders_total: Counter
    positions: Annotated[list[Position], Field(max_length=1000)]
    orders: Annotated[list[LiveOrder], Field(max_length=1000)]


class Window(WireModel):
    from_server_msc: DecimalText
    to_server_msc: DecimalText


class Collection[T](WireModel):
    status: Literal["complete", "truncated", "error", "partial", "paged_complete"]
    total: Annotated[int, Field(ge=0, le=2**31 - 1)] | None
    items: Annotated[list[T], Field(max_length=200)]


class PageKey(WireModel):
    time_msc: DecimalText
    entity_type: Literal["deal", "order"]
    ticket: DecimalText


class Pagination(WireModel):
    snapshot_id: Identifier
    after: PageKey
    through: PageKey
    has_more: bool


class ActivityPayload(WireModel):
    reason: Literal["startup", "trade_activity", "reconcile", "recovery", "position_reconcile"]
    identity: Identity
    window: Window
    deals: Collection[Deal]
    orders: Collection[HistoryOrder]
    pagination: Pagination | SkipJsonSchema[None] = None


class ActivityProgress(WireModel):
    recent_cursor_msc: DecimalText
    deep_cursor_msc: DecimalText
    backlog_msc: DecimalText
    recent_blocked: bool
    deep_blocked: bool
    deep_paused: bool | SkipJsonSchema[None] = None
    queued_hints: Counter
    dropped_hints: Counter
    last_transaction_age_ms: DecimalText
    latest_deal_ticket: DecimalText
    latest_order_ticket: DecimalText
    latest_position_id: DecimalText


class HeartbeatPayload(WireModel):
    identity: Identity
    status: Literal["ok", "degraded"]
    queued_messages: Counter
    dropped_messages: Counter
    activity_progress: ActivityProgress | SkipJsonSchema[None] = None


class TradingLiveSnapshot(Envelope):
    schema_version: Literal["mt5-trading-events-v1"]
    kind: Literal["live_snapshot"]
    payload: LivePayload


class TradingActivityBatch(Envelope):
    schema_version: Literal["mt5-trading-events-v1"]
    kind: Literal["activity_batch"]
    payload: ActivityPayload


class TradingHeartbeat(Envelope):
    schema_version: Literal["mt5-trading-events-v1"]
    kind: Literal["heartbeat"]
    payload: HeartbeatPayload


ACCOUNT_STATE_REQUEST = TypeAdapter(
    Annotated[AccountHeartbeat | AccountStateSnapshot, Field(discriminator="kind")]
)
TRADING_EVENTS_REQUEST = TypeAdapter(
    Annotated[
        TradingLiveSnapshot | TradingActivityBatch | TradingHeartbeat, Field(discriminator="kind")
    ]
)

EXAMPLE_ACCOUNT_STATE = {
    "schema_version": "mt5-account-state-v1",
    "collector_version": "example-1",
    "source_id": "example-live",
    "session_id": "example-session",
    "sequence": 1,
    "event_id": "example-session:1",
    "captured_at": "2026-11-04T12:00:00Z",
    "kind": "heartbeat",
    "payload": {"status": "ok"},
}
EXAMPLE_TRADING_EVENTS = {
    **EXAMPLE_ACCOUNT_STATE,
    "schema_version": "mt5-trading-events-v1",
    "source_id": "example-activity",
    "payload": {
        "status": "ok",
        "identity": {"login_masked": "****1234", "server": "DEMO-SERVER", "currency": "USD"},
        "queued_messages": 0,
        "dropped_messages": 0,
    },
}


class AccountStateAck(WireModel):
    status: Literal["accepted", "duplicate"]
    sequence_gap: Counter


class TradingEventsAck(AccountStateAck):
    out_of_order: bool


class ApiError(WireModel):
    error: str


class Health(WireModel):
    status: Literal["ready"]
    storage: Literal["sqlite"]
    services: dict[str, str]


class AccountStateHealth(WireModel):
    status: Literal["ready"]
    storage: Literal["sqlite"]
    accepted: Counter
    duplicates: Counter
    missing_sequences: Counter
    retained: Counter
    retained_sessions: Counter
    history_status: Literal["complete", "truncated", "error", "unavailable"]
    history_retained: Counter


class HistoricalDeal(DealValues):
    account_id: str
    source_id: str
    message_id: int
    captured_at: str
    time_msc: int


class DealPage(WireModel):
    account_id: str
    source_id: str
    from_msc: int
    to_msc: int
    magic_number: str | None
    deals: list[HistoricalDeal]
    next_cursor: str | None


class AccountPoint(WireModel):
    observed_at: str
    balance: float
    equity: float


class AccountHistory(WireModel):
    account_id: str
    source_id: str
    from_msc: int
    to_msc: int
    bucket_msc: int
    sampling: Literal["last_observation_per_bucket"]
    points: list[AccountPoint]


class EvolutionPoint(AccountPoint):
    resolution: Literal["daily", "recent"]
    broker_day: str | None
    broker_time: str | None


class AccountEvolution(WireModel):
    account_id: str
    source_id: str
    from_msc: int
    to_msc: int
    sampling: Literal["daily_close_and_recent"]
    time_basis: Literal["utc"]
    bucket_msc: int
    recent_basis: Literal["none", "broker_day", "last_24h_unassigned"]
    recent_from_msc: int | None
    unconsolidated_history: bool
    points: list[EvolutionPoint] = Field(max_length=480)


class ActivityItem(WireModel):
    message_id: int
    ticket: str
    values: Deal | HistoryOrder
    observed_at: str
    received_at: str
    source_id: str
    session_id: str
    sequence: int
    conflict_at: str | None


class CoverageRange(WireModel):
    from_msc: str
    to_msc: str


class Coverage(WireModel):
    complete_ranges: list[CoverageRange]
    incomplete_batches: int


class AccountProgressionPoint(WireModel):
    time_msc: DecimalText
    balance: float | None
    realized_pnl: float | None
    net_cash_flow: float | None
    adjustments: float | None


class AccountProgression(WireModel):
    calculation_version: Literal["account-ledger-v1"]
    account_id: str
    source_id: str
    from_server_msc: int
    to_server_msc: int
    time_basis: Literal["broker_wall_clock"]
    bucket_msc: int
    status: Literal["complete", "partial"]
    balance_status: Literal["available", "missing_anchor", "ambiguous_anchor", "incomplete_ledger"]
    pnl_from_server_msc: DecimalText | None
    anchor_server_msc: DecimalText | None
    points: Annotated[list[AccountProgressionPoint], Field(max_length=480)]


class ActivityPage(WireModel):
    account_id: str
    entity_type: Literal["deal", "order"]
    from_msc: int
    to_msc: int
    magic_number: str | None
    items: list[ActivityItem]
    next_cursor: str | None
    coverage: Coverage


class ProgressObservation(WireModel):
    account_id: str
    source_id: str
    session_id: str
    sequence: int
    collector_version: str
    captured_at: str
    received_at: str
    status: Literal["ok", "degraded"]
    values: ActivityProgress


class ProgressResponse(WireModel):
    activity_progress: ProgressObservation | None


class Magics(WireModel):
    magics: list[str]


class CycleDetails(WireModel):
    side: Literal["long", "short"] | None
    symbol: str | None
    opening_tickets: list[str]
    volume: float | None
    open_price: float | None
    close_price: float | None
    gross_profit: float
    swap: float
    commission: float
    fee: float
    take_profit: float | None
    stop_loss: float | None
    levels_basis: Literal["exit_order", "initial_order", "unknown"]
    pips: float | None
    duration_hours: float


class Cycle(WireModel):
    account_id: str
    position_id: str
    owner_magic: str | None
    observed_magics: list[str]
    started_at_msc: int
    last_event_at_msc: int
    lifecycle: Literal["closed", "open", "incomplete", "inconsistent"]
    remaining_signed_volume: str
    observed_net_result: str
    deal_tickets: list[str]
    exclusions: list[str]
    eligible_for_autonomous_metrics: bool


class CycleItem(WireModel):
    message_id: int
    source_id: str
    captured_at: str
    details: CycleDetails | None
    cycle: Cycle


class CyclePage(WireModel):
    account_id: str
    owner_magic: str | None
    items: list[CycleItem]
    next_cursor: str | None

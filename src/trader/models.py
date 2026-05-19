"""Typed domain models for the trading workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trader.config import mask_account_id


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class SerializableModel(BaseModel):
    """Base model configured for stable JSON serialization."""

    model_config = ConfigDict(frozen=True, use_enum_values=True)


class AssetType(StrEnum):
    EQUITY = "equity"


class SignalDirection(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class TradeAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    LIMIT = "LIMIT"


class ExecutionStatus(StrEnum):
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class MarketDataRequestType(StrEnum):
    """IBKR market-data type names supported by read-only diagnostics."""

    LIVE = "live"
    FROZEN = "frozen"
    DELAYED = "delayed"
    DELAYED_FROZEN = "delayed_frozen"


class HistoricalReadinessStatus(StrEnum):
    """Historical snapshot readiness states for future simulation inputs."""

    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"


class HistoricalLoadStatus(StrEnum):
    """Offline historical snapshot load states."""

    LOADED = "loaded"
    PARTIAL = "partial"
    FAILED = "failed"


class BacktestAlignmentMode(StrEnum):
    """Timestamp alignment modes for offline backtest data feeds."""

    UNION = "union"
    INTERSECTION = "intersection"


class BacktestFeedStatus(StrEnum):
    """Offline backtest feed readiness states."""

    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"


class BacktestRunStatus(StrEnum):
    """Offline backtest run states for frame replay diagnostics."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class InertStrategyRunnerStatus(StrEnum):
    """Offline inert strategy runner states for no-op diagnostics."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class Instrument(SerializableModel):
    """Tradable instrument descriptor."""

    symbol: str
    asset_type: AssetType = AssetType.EQUITY
    exchange: str = "SMART"
    currency: str = "USD"

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized


class MarketQuote(SerializableModel):
    """Market data snapshot for one instrument."""

    symbol: str
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    timestamp: datetime = Field(default_factory=utc_now)
    source: str = "mock"
    is_mock: bool = True

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_prices(self) -> MarketQuote:
        for field_name in ("bid", "ask", "last"):
            value = getattr(self, field_name)
            if value is not None and value <= 0:
                raise ValueError(f"{field_name} must be positive when provided")
        if self.bid is not None and self.ask is not None and self.ask < self.bid:
            raise ValueError("ask must be greater than or equal to bid")
        return self

    @property
    def has_bid_ask(self) -> bool:
        return self.bid is not None and self.ask is not None

    @property
    def mid(self) -> Decimal | None:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / Decimal("2")
        return self.last

    def age_seconds(self, now: datetime | None = None) -> float:
        reference = now or utc_now()
        return (reference - self.timestamp).total_seconds()

    def is_stale(self, *, max_age_seconds: int, now: datetime | None = None) -> bool:
        return self.age_seconds(now) > max_age_seconds


class Signal(SerializableModel):
    """Strategy output. Signals are proposals only, not orders."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    direction: SignalDirection
    strength: Decimal = Decimal("0")
    confidence: Decimal = Decimal("0")
    strategy: str
    reason: str
    generated_at: datetime = Field(default_factory=utc_now)
    horizon_minutes: int = 60

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("strength", "confidence")
    @classmethod
    def validate_score(cls, value: Decimal) -> Decimal:
        if value < 0 or value > 1:
            raise ValueError("signal scores must be between 0 and 1")
        return value


class TradePlan(SerializableModel):
    """Risk-reviewable proposal derived from a signal."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    action: TradeAction
    quantity: int
    limit_price: Decimal
    notional: Decimal
    source_signal_id: str
    strategy: str
    reason_codes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    dry_run: bool = True

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("quantity must be positive")
        return value

    @field_validator("limit_price", "notional")
    @classmethod
    def validate_money(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("money fields must be positive")
        return value


class RiskDecision(SerializableModel):
    """Explicit risk verdict for a proposed trade plan."""

    plan_id: str
    symbol: str
    approved: bool
    blocked_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    adjusted_plan: TradePlan | None = None
    checked_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_decision(self) -> RiskDecision:
        if not self.approved and not self.blocked_reason:
            raise ValueError("blocked risk decisions need a blocked_reason")
        if self.approved and self.blocked_reason:
            raise ValueError("approved risk decisions cannot have a blocked_reason")
        return self


class OrderIntent(SerializableModel):
    """Execution-layer order intent. Market orders are intentionally unsupported."""

    plan_id: str
    symbol: str
    action: TradeAction
    quantity: int
    order_type: OrderType = OrderType.LIMIT
    limit_price: Decimal
    created_at: datetime = Field(default_factory=utc_now)


class SimulatedFill(SerializableModel):
    """Simulator fill event."""

    plan_id: str
    symbol: str
    action: TradeAction
    quantity: int
    fill_price: Decimal
    filled_at: datetime = Field(default_factory=utc_now)
    liquidity_flag: str = "simulated"


class ExecutionResult(SerializableModel):
    """Execution outcome from simulator or future paper executor."""

    plan_id: str
    symbol: str
    status: ExecutionStatus
    message: str
    fills: list[SimulatedFill] = Field(default_factory=list)
    submitted_to_broker: bool = False
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class PositionSnapshot(SerializableModel):
    """Current position view used by risk checks."""

    symbol: str
    quantity: int
    market_value: Decimal
    average_cost: Decimal | None = None
    unrealized_pnl: Decimal = Decimal("0")


class AccountSnapshot(SerializableModel):
    """Masked account and equity view used by risk checks and reports."""

    account_id: str | None = None
    equity: Decimal
    cash: Decimal
    buying_power: Decimal
    daily_pnl: Decimal = Decimal("0")
    currency: str = "USD"
    timestamp: datetime = Field(default_factory=utc_now)
    is_mock: bool = True

    def masked_account_id(self) -> str | None:
        return mask_account_id(self.account_id)


class BrokerErrorEvent(SerializableModel):
    """Read-only broker diagnostic error or API warning callback."""

    message: str
    req_id: int | None = None
    code: int | None = None
    source: str = "ibkr"
    timestamp: datetime = Field(default_factory=utc_now)


class ManagedAccountInfo(SerializableModel):
    """Masked managed-account identifier returned by the broker API."""

    account_id_masked: str


class BrokerTimeProbe(SerializableModel):
    """Result of a harmless current-time request to TWS or IB Gateway."""

    ok: bool
    server_time: datetime | None = None
    raw_server_time: int | None = None
    latency_ms: float | None = None
    error: str | None = None


class BrokerConnectionStatus(SerializableModel):
    """Connection status for the read-only IBKR socket probe."""

    ok: bool
    mode: str
    host: str
    port: int
    client_id: int
    broker_kind: str
    connected: bool
    ibapi_available: bool
    ibapi_import_error: str | None = None
    connection_attempted: bool = False
    failure_stage: str | None = None
    errors: list[BrokerErrorEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    read_only_assumed_or_detected: bool | None = True
    order_routing_enabled: bool = False
    checked_at: datetime = Field(default_factory=utc_now)


class BrokerDiagnosticReport(SerializableModel):
    """Full read-only IBKR broker probe report."""

    title: str = "Read-only Broker Probe"
    report_type: str = "broker_probe"
    ok: bool
    mode: str
    host: str
    port: int
    client_id: int
    broker_kind: str
    connected: bool
    ibapi_available: bool
    ibapi_import_error: str | None = None
    connection_attempted: bool = False
    failure_stage: str | None = None
    server_time: datetime | None = None
    time_probe: BrokerTimeProbe | None = None
    managed_accounts_masked: list[ManagedAccountInfo] = Field(default_factory=list)
    account_snapshot: dict[str, Any] | None = None
    positions_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[BrokerErrorEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    read_only_assumed_or_detected: bool | None = True
    order_routing_enabled: bool = False
    final_status: str = "unknown"
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This broker probe uses read-only requests only and order routing is disabled."
    )
    timestamp: datetime = Field(default_factory=utc_now)


class ContractResolutionResult(SerializableModel):
    """Result of resolving a read-only IBKR contract for market-data diagnostics."""

    symbol: str
    sec_type: str = "STK"
    exchange: str = "SMART"
    currency: str = "USD"
    primary_exchange: str | None = None
    contract_id: int | None = None
    resolved: bool = False
    ambiguous: bool = False
    matching_contracts: int = 0
    selected_contract_description: str | None = None
    errors: list[BrokerErrorEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MarketDataTick(SerializableModel):
    """Captured IBKR market-data tick used to build a quote snapshot."""

    symbol: str
    req_id: int
    tick_type: int
    field: str
    value: Decimal | str
    timestamp: datetime = Field(default_factory=utc_now)


class MarketDataTypeInfo(SerializableModel):
    """Requested and callback-confirmed IBKR market-data type."""

    requested: MarketDataRequestType
    requested_code: int
    received: MarketDataRequestType | None = None
    received_code: int | None = None


class QuoteSnapshot(SerializableModel):
    """Read-only quote snapshot captured from IBKR market data callbacks."""

    symbol: str
    market_data_type: MarketDataTypeInfo
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    close: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    last_size: Decimal | None = None
    quote_timestamp: datetime | None = None
    quote_age_seconds: float | None = None
    stale: bool = True
    ticks: list[MarketDataTick] = Field(default_factory=list)
    errors: list[BrokerErrorEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SpreadDiagnostic(SerializableModel):
    """Bid/ask spread and spread-bps diagnostics for a quote snapshot."""

    symbol: str
    has_bid_ask: bool = False
    spread: Decimal | None = None
    spread_bps: Decimal | None = None
    warnings: list[str] = Field(default_factory=list)


class HistoricalBar(SerializableModel):
    """Small historical bar returned by a read-only IBKR request."""

    symbol: str
    timestamp: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    wap: Decimal | None = None
    bar_count: int | None = None


class HistoricalDataDiagnostic(SerializableModel):
    """Historical-data request diagnostic for one symbol."""

    symbol: str
    requested: bool = False
    ok: bool = False
    bars: list[HistoricalBar] = Field(default_factory=list)
    historical_bars_count: int = 0
    historical_start: str | None = None
    historical_end: str | None = None
    errors: list[BrokerErrorEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class HistoricalSnapshotRequest(SerializableModel):
    """Bounded read-only historical-data request parameters."""

    symbols: list[str]
    duration: str = "1 D"
    bar_size: str = "5 mins"
    what_to_show: str = "TRADES"
    use_rth: int = 1
    timeout_seconds: float = 30

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        symbols = [symbol.strip().upper() for symbol in value if symbol.strip()]
        if not symbols:
            raise ValueError("at least one symbol is required")
        return symbols

    @field_validator("duration", "bar_size", "what_to_show")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("historical request fields cannot be empty")
        return normalized

    @field_validator("what_to_show")
    @classmethod
    def normalize_what_to_show(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("use_rth")
    @classmethod
    def validate_use_rth(cls, value: int) -> int:
        if value not in {0, 1}:
            raise ValueError("use_rth must be 0 or 1")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout_seconds(cls, value: float) -> float:
        if value <= 0 or value > 120:
            raise ValueError("timeout_seconds must be greater than 0 and no more than 120")
        return value


class HistoricalSnapshotBar(SerializableModel):
    """Persisted historical bar from a read-only IBKR snapshot."""

    symbol: str
    contract_id: int | None = None
    timestamp: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    wap: Decimal | None = None
    bar_count: int | None = None
    source: str = "ibkr"
    duration: str
    bar_size: str
    what_to_show: str
    use_rth: int


class HistoricalSnapshotManifest(SerializableModel):
    """Metadata for a stored historical snapshot file."""

    generated_at: datetime = Field(default_factory=utc_now)
    symbol: str
    contract_id: int | None = None
    exchange: str = "SMART"
    currency: str = "USD"
    duration: str
    bar_size: str
    what_to_show: str
    use_rth: int
    bar_count: int = 0
    first_bar_time: str | None = None
    last_bar_time: str | None = None
    request_timeout: float
    snapshot_path: str | None = None
    manifest_path: str | None = None
    ibkr_messages: list[BrokerErrorEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[BrokerErrorEvent] = Field(default_factory=list)
    no_order_guarantee: bool = True
    order_routing_enabled: bool = False


class HistoricalSnapshotResult(SerializableModel):
    """Per-symbol historical snapshot request result."""

    symbol: str
    request: HistoricalSnapshotRequest
    contract_resolution: ContractResolutionResult | None = None
    ok: bool = False
    bars: list[HistoricalSnapshotBar] = Field(default_factory=list)
    manifest: HistoricalSnapshotManifest | None = None
    snapshot_path: str | None = None
    manifest_path: str | None = None
    historical_start: str | None = None
    historical_end: str | None = None
    errors: list[BrokerErrorEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class HistoricalSnapshotReport(SerializableModel):
    """Batch report for read-only historical snapshot ingestion."""

    title: str = "Read-only Historical Snapshot"
    report_type: str = "history_snapshot"
    ok: bool
    mode: str
    host: str
    port: int
    client_id: int
    broker_kind: str
    connected: bool
    ibapi_available: bool
    ibapi_import_error: str | None = None
    connection_attempted: bool = False
    failure_stage: str | None = None
    request: HistoricalSnapshotRequest
    symbols_requested: list[str] = Field(default_factory=list)
    results: list[HistoricalSnapshotResult] = Field(default_factory=list)
    snapshot_paths: list[str] = Field(default_factory=list)
    manifest_paths: list[str] = Field(default_factory=list)
    ibkr_messages: list[BrokerErrorEvent] = Field(default_factory=list)
    errors: list[BrokerErrorEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    order_routing_enabled: bool = False
    final_status: str = "unknown"
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This historical snapshot uses read-only data requests only and order routing is disabled."
    )
    timestamp: datetime = Field(default_factory=utc_now)


class HistoricalDataQualityIssue(SerializableModel):
    """One validation issue found in a historical snapshot."""

    symbol: str
    severity: str
    code: str
    message: str
    timestamp: str | None = None


class HistoricalReadinessSummary(SerializableModel):
    """Per-symbol historical data readiness summary."""

    symbol: str
    resolved_contract_id: int | None = None
    requested_duration: str
    requested_bar_size: str
    requested_what_to_show: str
    use_rth: int
    bars_count: int = 0
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    sorted_timestamps: bool = False
    duplicate_timestamps_count: int = 0
    missing_timestamp_gaps: list[str] = Field(default_factory=list)
    largest_gap_seconds: float | None = None
    zero_volume_bars: int = 0
    negative_volume_bars: int = 0
    invalid_ohlc_bars: int = 0
    stale_snapshot: bool = False
    readiness_status: HistoricalReadinessStatus = HistoricalReadinessStatus.FAILED
    snapshot_path: str | None = None
    manifest_path: str | None = None
    issues: list[HistoricalDataQualityIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    no_order_guarantee: bool = True
    order_routing_enabled: bool = False


class HistoricalReadinessReport(SerializableModel):
    """Readiness report for stored historical snapshots."""

    title: str = "Historical Snapshot Readiness"
    report_type: str = "history_readiness"
    ok: bool
    mode: str
    host: str
    port: int
    client_id: int
    broker_kind: str
    requests: list[HistoricalSnapshotRequest] = Field(default_factory=list)
    symbols_requested: list[str] = Field(default_factory=list)
    snapshot_paths: list[str] = Field(default_factory=list)
    manifest_paths: list[str] = Field(default_factory=list)
    summaries: list[HistoricalReadinessSummary] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    order_routing_enabled: bool = False
    final_status: str = "unknown"
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This readiness report reads local historical snapshots only and order routing is disabled."
    )
    timestamp: datetime = Field(default_factory=utc_now)


class HistoricalSnapshotIndexEntry(SerializableModel):
    """Discovered offline historical snapshot file pair."""

    symbol: str
    bar_size: str
    what_to_show: str
    snapshot_timestamp: str
    bars_path: str
    manifest_path: str
    generated_at: datetime | None = None
    bars_count: int | None = None
    manifest_bar_count: int | None = None
    source: str = "offline_snapshot"


class HistoricalSnapshotLoadRequest(SerializableModel):
    """Offline historical snapshot load request."""

    symbols: list[str] = Field(default_factory=list)
    bar_size: str | None = None
    what_to_show: str | None = None
    latest: bool = True
    snapshot_timestamp: str | None = None
    strict: bool = False
    base_data_path: str = "data/historical"

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol.strip()]

    @field_validator("bar_size", "what_to_show", "snapshot_timestamp")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("what_to_show")
    @classmethod
    def normalize_optional_what_to_show(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class HistoricalLoadIssue(SerializableModel):
    """One issue found while loading offline historical snapshots."""

    symbol: str | None = None
    severity: str
    code: str
    message: str
    path: str | None = None
    line_number: int | None = None
    timestamp: str | None = None


class HistoricalLoadedBar(SerializableModel):
    """Normalized in-memory bar loaded from an offline snapshot."""

    symbol: str
    contract_id: int | None = None
    timestamp: datetime
    raw_timestamp: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    wap: Decimal | None = None
    bar_count: int | None = None
    typical_price: Decimal
    dollar_volume: Decimal | None = None
    interval_seconds: float | None = None
    source: str = "offline_snapshot"
    duration: str
    bar_size: str
    what_to_show: str
    use_rth: int


class HistoricalDatasetSummary(SerializableModel):
    """Quality summary for one loaded offline historical dataset."""

    symbol: str
    bar_size: str
    what_to_show: str
    snapshot_timestamp: str | None = None
    bars_path: str | None = None
    manifest_path: str | None = None
    bars_count: int = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    duplicate_timestamps_count: int = 0
    missing_gap_count: int = 0
    largest_gap_seconds: float | None = None
    malformed_line_count: int = 0
    invalid_ohlc_count: int = 0
    negative_volume_count: int = 0
    stale_snapshot: bool = False
    manifest_bar_count: int | None = None
    manifest_matches_bars: bool = False
    load_status: HistoricalLoadStatus = HistoricalLoadStatus.FAILED
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    source: str = "offline_snapshot"
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True


class HistoricalLoadedDataset(SerializableModel):
    """Loaded offline historical dataset for future simulation inputs."""

    symbol: str
    bar_size: str
    what_to_show: str
    snapshot_timestamp: str
    bars_path: str
    manifest_path: str
    bars: list[HistoricalLoadedBar] = Field(default_factory=list)
    summary: HistoricalDatasetSummary
    issues: list[HistoricalLoadIssue] = Field(default_factory=list)
    source: str = "offline_snapshot"
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True


class HistoricalLoadResult(SerializableModel):
    """Per-symbol offline historical snapshot load result."""

    symbol: str
    request: HistoricalSnapshotLoadRequest
    index_entry: HistoricalSnapshotIndexEntry | None = None
    dataset: HistoricalLoadedDataset | None = None
    summary: HistoricalDatasetSummary | None = None
    issues: list[HistoricalLoadIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    load_status: HistoricalLoadStatus = HistoricalLoadStatus.FAILED
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True


class HistoricalLoaderReport(SerializableModel):
    """Offline historical loader report for index and load commands."""

    title: str = "Offline Historical Snapshot Loader"
    report_type: str = "history_load"
    command: str
    ok: bool
    request: HistoricalSnapshotLoadRequest
    base_data_path: str
    symbols_requested: list[str] = Field(default_factory=list)
    snapshots_discovered: list[HistoricalSnapshotIndexEntry] = Field(default_factory=list)
    results: list[HistoricalLoadResult] = Field(default_factory=list)
    summaries: list[HistoricalDatasetSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This offline loader reads local historical snapshot files only and does not "
        "contact a broker."
    )
    final_status: str = "unknown"
    timestamp: datetime = Field(default_factory=utc_now)


class BacktestBar(SerializableModel):
    """Normalized bar prepared for future backtest data feeds."""

    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    source_snapshot_timestamp: str | None = None
    source_bars_path: str | None = None
    source_manifest_path: str | None = None
    source: str = "offline_snapshot"

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized


class BacktestFeedPoint(SerializableModel):
    """One symbol's optional bar inside an aligned feed frame."""

    symbol: str
    bar: BacktestBar | None = None
    missing: bool = False


class BacktestFeedFrame(SerializableModel):
    """All symbol bars aligned to one timestamp."""

    timestamp: datetime
    bars_by_symbol: dict[str, BacktestBar | None] = Field(default_factory=dict)
    points: list[BacktestFeedPoint] = Field(default_factory=list)
    missing_symbols: list[str] = Field(default_factory=list)


class BacktestDataAdapterIssue(SerializableModel):
    """Structured issue found while adapting offline datasets into a feed."""

    symbol: str | None = None
    severity: str
    code: str
    message: str
    timestamp: datetime | None = None


class BacktestDataFeedSummary(SerializableModel):
    """Compact summary of an offline backtest data feed."""

    symbols: list[str] = Field(default_factory=list)
    total_bars: int = 0
    frame_count: int = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    missing_bars_by_symbol: dict[str, int] = Field(default_factory=dict)
    duplicate_timestamps_by_symbol: dict[str, int] = Field(default_factory=dict)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    feed_status: BacktestFeedStatus = BacktestFeedStatus.FAILED
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True


class BacktestDataFeed(SerializableModel):
    """Deterministic offline bar feed for future backtesting."""

    symbols: list[str] = Field(default_factory=list)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    frames: list[BacktestFeedFrame] = Field(default_factory=list)
    source_summaries: list[HistoricalDatasetSummary] = Field(default_factory=list)
    total_bars: int = 0
    frame_count: int = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    missing_bars_by_symbol: dict[str, int] = Field(default_factory=dict)
    duplicate_timestamps_by_symbol: dict[str, int] = Field(default_factory=dict)
    feed_status: BacktestFeedStatus = BacktestFeedStatus.FAILED
    issues: list[BacktestDataAdapterIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True


class BacktestDataAdapterRequest(SerializableModel):
    """Offline backtest feed build request."""

    symbols: list[str] = Field(default_factory=list)
    bar_size: str | None = None
    what_to_show: str | None = None
    latest: bool = True
    snapshot_timestamp: str | None = None
    strict: bool = False
    base_data_path: str = "data/historical"
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol.strip()]

    @field_validator("bar_size", "what_to_show", "snapshot_timestamp")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("what_to_show")
    @classmethod
    def normalize_optional_what_to_show(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class BacktestDataAdapterReport(SerializableModel):
    """Report for a broker-free backtest feed build."""

    title: str = "Broker-free Backtest Data Feed"
    report_type: str = "backtest_feed"
    command: str = "backtest-feed"
    ok: bool
    request: BacktestDataAdapterRequest
    symbols_requested: list[str] = Field(default_factory=list)
    source_datasets: list[HistoricalDatasetSummary] = Field(default_factory=list)
    summary: BacktestDataFeedSummary | None = None
    issues: list[BacktestDataAdapterIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This backtest feed adapter reads local historical snapshots only and does not "
        "contact a broker."
    )
    no_strategy_execution_statement: str = (
        "No strategy evaluation, order simulation, or P&L calculation was performed."
    )
    final_status: str = "unknown"
    timestamp: datetime = Field(default_factory=utc_now)


class BacktestRunRequest(SerializableModel):
    """Offline backtest engine skeleton request."""

    symbols: list[str] = Field(default_factory=list)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    requested_bar_size: str | None = None
    requested_what_to_show: str | None = None
    latest: bool = True
    snapshot_timestamp: str | None = None
    strict: bool = False
    base_data_path: str = "data/historical"

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol.strip()]

    @field_validator("requested_bar_size", "requested_what_to_show", "snapshot_timestamp")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("requested_what_to_show")
    @classmethod
    def normalize_optional_what_to_show(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class BacktestFrameObservation(SerializableModel):
    """One replayed data-frame observation from the offline engine skeleton."""

    timestamp: datetime
    frame_index: int
    symbols_present: list[str] = Field(default_factory=list)
    symbols_missing: list[str] = Field(default_factory=list)
    bar_count: int = 0
    missing_bar_count: int = 0


class BacktestRunDiagnostics(SerializableModel):
    """Run-level diagnostics from replaying an offline data feed."""

    symbols: list[str] = Field(default_factory=list)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    requested_bar_size: str | None = None
    requested_what_to_show: str | None = None
    feed_status: BacktestFeedStatus = BacktestFeedStatus.FAILED
    run_status: BacktestRunStatus = BacktestRunStatus.FAILED
    frame_count: int = 0
    total_bars_observed: int = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    observations_count: int = 0
    missing_bars_by_symbol: dict[str, int] = Field(default_factory=dict)
    frames_with_missing_bars: int = 0
    elapsed_seconds: float | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    strategy_evaluated: bool = False
    orders_simulated: bool = False
    pnl_calculated: bool = False


class BacktestRunResult(SerializableModel):
    """Result of an offline backtest engine skeleton replay."""

    ok: bool
    request: BacktestRunRequest
    diagnostics: BacktestRunDiagnostics
    observations: list[BacktestFrameObservation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    strategy_evaluated: bool = False
    orders_simulated: bool = False
    pnl_calculated: bool = False
    timestamp: datetime = Field(default_factory=utc_now)


class BacktestRunReport(SerializableModel):
    """Report for an offline backtest engine skeleton run."""

    title: str = "Broker-free Backtest Run"
    report_type: str = "backtest_run"
    command: str = "backtest-run"
    ok: bool
    request: BacktestRunRequest
    symbols_requested: list[str] = Field(default_factory=list)
    feed_summary: BacktestDataFeedSummary | None = None
    result: BacktestRunResult
    diagnostics: BacktestRunDiagnostics
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    strategy_evaluated: bool = False
    orders_simulated: bool = False
    pnl_calculated: bool = False
    no_order_guarantee_statement: str = (
        "This backtest run reads local historical snapshots only and does not "
        "contact a broker."
    )
    no_execution_statement: str = (
        "This run replayed data frames only. No strategy evaluation, order "
        "simulation, broker routing, or P&L calculation was performed."
    )
    final_status: str = "unknown"
    timestamp: datetime = Field(default_factory=utc_now)


class StrategyParameterSpec(SerializableModel):
    """Parameter metadata for future broker-free strategy contracts."""

    name: str
    parameter_type: str = "string"
    description: str = ""
    default_value: Any | None = None
    required: bool = False

    @field_validator("name", "parameter_type")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("strategy parameter text fields cannot be empty")
        return normalized


class StrategyMetadata(SerializableModel):
    """Metadata contract for a future strategy implementation."""

    strategy_name: str
    strategy_version: str = "0.0.0"
    description: str = ""
    parameters: list[StrategyParameterSpec] = Field(default_factory=list)
    supported_bar_sizes: list[str] = Field(default_factory=lambda: ["5 mins"])
    required_fields: list[str] = Field(
        default_factory=lambda: ["open", "high", "low", "close", "volume"]
    )
    broker_required: bool = False

    @field_validator("strategy_name", "strategy_version")
    @classmethod
    def normalize_metadata_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("strategy metadata text fields cannot be empty")
        return normalized

    @field_validator("supported_bar_sizes", "required_fields")
    @classmethod
    def normalize_text_lists(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class StrategyFrameContext(SerializableModel):
    """Read-only frame context offered to future strategy contracts."""

    timestamp: datetime
    frame_index: int
    available_symbols: list[str] = Field(default_factory=list)
    missing_symbols: list[str] = Field(default_factory=list)
    bars_by_symbol: dict[str, BacktestBar | None] = Field(default_factory=dict)
    feed_symbols: list[str] = Field(default_factory=list)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    feed_status: BacktestFeedStatus = BacktestFeedStatus.FAILED
    feed_frame_count: int = 0
    feed_summary: BacktestDataFeedSummary | None = None
    source: str = "backtest_feed"


class StrategyContractDiagnostic(SerializableModel):
    """Per-frame diagnostics from the no-op strategy contract scaffold."""

    strategy_name: str
    strategy_version: str
    timestamp: datetime
    frame_index: int
    available_symbols: list[str] = Field(default_factory=list)
    missing_symbols: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    evaluated: bool = False
    generated_signals: bool = False
    generated_orders: bool = False
    orders_simulated: bool = False
    pnl_calculated: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True


class StrategyContractValidationRequest(SerializableModel):
    """Offline no-op strategy contract validation request."""

    symbols: list[str] = Field(default_factory=list)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    requested_bar_size: str | None = None
    requested_what_to_show: str | None = None
    latest: bool = True
    snapshot_timestamp: str | None = None
    strict: bool = False
    base_data_path: str = "data/historical"

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol.strip()]

    @field_validator("requested_bar_size", "requested_what_to_show", "snapshot_timestamp")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("requested_what_to_show")
    @classmethod
    def normalize_optional_what_to_show(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class StrategyContractValidationResult(SerializableModel):
    """Result of an offline strategy contract validation run."""

    ok: bool
    request: StrategyContractValidationRequest
    metadata: StrategyMetadata
    feed_summary: BacktestDataFeedSummary | None = None
    frame_context_sample: StrategyFrameContext | None = None
    diagnostics: list[StrategyContractDiagnostic] = Field(default_factory=list)
    contexts_observed: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    final_status: str = "unknown"
    evaluated: bool = False
    generated_signals: bool = False
    generated_orders: bool = False
    orders_simulated: bool = False
    pnl_calculated: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    timestamp: datetime = Field(default_factory=utc_now)


class StrategyContractReport(SerializableModel):
    """Report for the broker-free strategy interface contract scaffold."""

    title: str = "Broker-free Strategy Contract"
    report_type: str = "strategy_contract"
    command: str = "strategy-contract"
    ok: bool
    request: StrategyContractValidationRequest
    metadata: StrategyMetadata
    symbols_requested: list[str] = Field(default_factory=list)
    feed_summary: BacktestDataFeedSummary | None = None
    frame_context_sample: StrategyFrameContext | None = None
    result: StrategyContractValidationResult
    diagnostics: list[StrategyContractDiagnostic] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    evaluated: bool = False
    generated_signals: bool = False
    generated_orders: bool = False
    orders_simulated: bool = False
    pnl_calculated: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This strategy contract report reads local historical snapshots only and "
        "does not contact a broker."
    )
    no_execution_statement: str = (
        "This command validates the strategy interface contract only. No real "
        "strategy evaluation, signal generation, order simulation, broker routing, "
        "or P&L calculation was performed."
    )
    final_status: str = "unknown"
    timestamp: datetime = Field(default_factory=utc_now)


class SignalFieldRequirement(SerializableModel):
    """Required bar field metadata for a disabled signal contract."""

    name: str
    description: str = ""
    required: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("signal field requirement name is required")
        return normalized


class SignalContractMetadata(SerializableModel):
    """Metadata for the disabled broker-free signal contract scaffold."""

    signal_contract_name: str
    signal_contract_version: str = "0.0.0"
    description: str = ""
    supported_symbols: list[str] = Field(default_factory=list)
    supported_bar_sizes: list[str] = Field(default_factory=lambda: ["5 mins"])
    required_fields: list[SignalFieldRequirement] = Field(
        default_factory=lambda: [
            SignalFieldRequirement(name="open"),
            SignalFieldRequirement(name="high"),
            SignalFieldRequirement(name="low"),
            SignalFieldRequirement(name="close"),
            SignalFieldRequirement(name="volume"),
        ]
    )
    broker_required: bool = False
    enabled: bool = False

    @field_validator("signal_contract_name", "signal_contract_version")
    @classmethod
    def normalize_metadata_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("signal contract metadata text fields cannot be empty")
        return normalized

    @field_validator("supported_symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol.strip()]

    @field_validator("supported_bar_sizes")
    @classmethod
    def normalize_text_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class SignalEvaluationContext(SerializableModel):
    """Read-only frame context offered to the disabled signal contract."""

    timestamp: datetime
    frame_index: int
    available_symbols: list[str] = Field(default_factory=list)
    missing_symbols: list[str] = Field(default_factory=list)
    bars_by_symbol: dict[str, BacktestBar | None] = Field(default_factory=dict)
    feed_symbols: list[str] = Field(default_factory=list)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    feed_status: BacktestFeedStatus = BacktestFeedStatus.FAILED
    feed_frame_count: int = 0
    feed_summary: BacktestDataFeedSummary | None = None
    strategy_metadata: StrategyMetadata | None = None
    signal_contract_metadata: SignalContractMetadata | None = None
    source: str = "backtest_feed"


class SignalContractDiagnostic(SerializableModel):
    """Per-frame diagnostics from the disabled signal contract scaffold."""

    signal_contract_name: str
    signal_contract_version: str
    timestamp: datetime
    frame_index: int
    available_symbols: list[str] = Field(default_factory=list)
    missing_symbols: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    signal_contract_validated: bool = True
    signal_evaluation_enabled: bool = False
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True


class SignalContractValidationRequest(SerializableModel):
    """Offline disabled signal contract validation request."""

    symbols: list[str] = Field(default_factory=list)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    requested_bar_size: str | None = None
    requested_what_to_show: str | None = None
    latest: bool = True
    snapshot_timestamp: str | None = None
    strict: bool = False
    base_data_path: str = "data/historical"

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol.strip()]

    @field_validator("requested_bar_size", "requested_what_to_show", "snapshot_timestamp")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("requested_what_to_show")
    @classmethod
    def normalize_optional_what_to_show(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class SignalContractValidationResult(SerializableModel):
    """Result of an offline disabled signal contract validation run."""

    ok: bool
    request: SignalContractValidationRequest
    metadata: SignalContractMetadata
    feed_summary: BacktestDataFeedSummary | None = None
    frame_context_sample: SignalEvaluationContext | None = None
    diagnostics: list[SignalContractDiagnostic] = Field(default_factory=list)
    contexts_observed: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    final_status: str = "unknown"
    signal_contract_validated: bool = True
    signal_evaluation_enabled: bool = False
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    timestamp: datetime = Field(default_factory=utc_now)


class SignalContractReport(SerializableModel):
    """Report for the broker-free disabled signal contract scaffold."""

    title: str = "Broker-free Signal Contract"
    report_type: str = "signal_contract"
    command: str = "signal-contract"
    ok: bool
    request: SignalContractValidationRequest
    metadata: SignalContractMetadata
    symbols_requested: list[str] = Field(default_factory=list)
    feed_summary: BacktestDataFeedSummary | None = None
    frame_context_sample: SignalEvaluationContext | None = None
    result: SignalContractValidationResult
    diagnostics: list[SignalContractDiagnostic] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    signal_contract_validated: bool = True
    signal_evaluation_enabled: bool = False
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This signal contract report reads local historical snapshots only and "
        "does not contact a broker."
    )
    no_execution_statement: str = (
        "This command validates the signal contract only. Signal evaluation is "
        "disabled. No trading signals, order intents, order simulation, broker "
        "routing, fills, portfolio accounting, or P&L calculation were produced."
    )
    final_status: str = "unknown"
    timestamp: datetime = Field(default_factory=utc_now)


class InertStrategyRunnerRequest(SerializableModel):
    """Offline inert no-op strategy runner request."""

    symbols: list[str] = Field(default_factory=list)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    requested_bar_size: str | None = None
    requested_what_to_show: str | None = None
    latest: bool = True
    snapshot_timestamp: str | None = None
    strict: bool = False
    base_data_path: str = "data/historical"

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol.strip()]

    @field_validator("requested_bar_size", "requested_what_to_show", "snapshot_timestamp")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("requested_what_to_show")
    @classmethod
    def normalize_optional_what_to_show(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class InertStrategyFrameResult(SerializableModel):
    """Per-frame no-op strategy runner diagnostic result."""

    strategy_name: str
    strategy_version: str
    timestamp: datetime
    frame_index: int
    available_symbols: list[str] = Field(default_factory=list)
    missing_symbols: list[str] = Field(default_factory=list)
    diagnostic: StrategyContractDiagnostic
    diagnostic_only: bool = True
    noop_strategy_observed: bool = True
    real_strategy_evaluated: bool = False
    generated_signals: bool = False
    generated_orders: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True


class InertStrategyRunnerDiagnostics(SerializableModel):
    """Run-level diagnostics from the inert no-op strategy runner."""

    strategy_name: str = "noop_contract"
    strategy_version: str = "0.1.0"
    symbols: list[str] = Field(default_factory=list)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    feed_status: BacktestFeedStatus = BacktestFeedStatus.FAILED
    runner_status: InertStrategyRunnerStatus = InertStrategyRunnerStatus.FAILED
    frame_count: int = 0
    contexts_built: int = 0
    diagnostics_emitted: int = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    missing_symbols_by_frame_count: int = 0
    missing_symbols_by_symbol: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    diagnostic_only: bool = True
    noop_strategy_observed: bool = True
    real_strategy_evaluated: bool = False
    generated_signals: bool = False
    generated_orders: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True


class InertStrategyRunnerResult(SerializableModel):
    """Result of replaying feed frames through the no-op strategy contract."""

    ok: bool
    request: InertStrategyRunnerRequest
    metadata: StrategyMetadata
    feed_summary: BacktestDataFeedSummary | None = None
    diagnostics: InertStrategyRunnerDiagnostics
    frame_results: list[InertStrategyFrameResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    diagnostic_only: bool = True
    noop_strategy_observed: bool = True
    real_strategy_evaluated: bool = False
    generated_signals: bool = False
    generated_orders: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    timestamp: datetime = Field(default_factory=utc_now)


class InertStrategyRunnerReport(SerializableModel):
    """Report for the broker-free inert strategy runner scaffold."""

    title: str = "Broker-free Inert Strategy Runner"
    report_type: str = "strategy_runner"
    command: str = "strategy-runner"
    ok: bool
    request: InertStrategyRunnerRequest
    metadata: StrategyMetadata
    symbols_requested: list[str] = Field(default_factory=list)
    feed_summary: BacktestDataFeedSummary | None = None
    result: InertStrategyRunnerResult
    diagnostics: InertStrategyRunnerDiagnostics
    frame_results: list[InertStrategyFrameResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    diagnostic_only: bool = True
    noop_strategy_observed: bool = True
    real_strategy_evaluated: bool = False
    generated_signals: bool = False
    generated_orders: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This inert strategy runner report reads local historical snapshots only "
        "and does not contact a broker."
    )
    no_execution_statement: str = (
        "This run exercised the no-op strategy contract only. No real strategy "
        "evaluation, signal generation, order simulation, broker routing, "
        "portfolio accounting, or P&L calculation was performed."
    )
    final_status: str = "unknown"
    timestamp: datetime = Field(default_factory=utc_now)


class MarketDataDiagnosticReport(SerializableModel):
    """Full read-only IBKR market-data diagnostic report."""

    title: str = "Read-only Market Data Probe"
    report_type: str = "market_probe"
    ok: bool
    mode: str
    host: str
    port: int
    client_id: int
    broker_kind: str
    connected: bool
    ibapi_available: bool
    ibapi_import_error: str | None = None
    connection_attempted: bool = False
    failure_stage: str | None = None
    symbols_requested: list[str] = Field(default_factory=list)
    market_data_type_requested: MarketDataRequestType = MarketDataRequestType.DELAYED
    market_data_type_requested_code: int = 3
    include_historical: bool = False
    contract_resolutions: list[ContractResolutionResult] = Field(default_factory=list)
    quote_snapshots: list[QuoteSnapshot] = Field(default_factory=list)
    spread_diagnostics: list[SpreadDiagnostic] = Field(default_factory=list)
    historical_data: list[HistoricalDataDiagnostic] = Field(default_factory=list)
    ibkr_messages: list[BrokerErrorEvent] = Field(default_factory=list)
    errors: list[BrokerErrorEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    order_routing_enabled: bool = False
    final_status: str = "unknown"
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This market-data probe uses read-only data requests only and order routing is disabled."
    )
    timestamp: datetime = Field(default_factory=utc_now)

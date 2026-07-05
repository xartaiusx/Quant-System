"""Typed domain models for the trading workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trader.config import mask_account_id

T = TypeVar("T")


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class SerializableModel(BaseModel):
    """Base model configured for stable JSON serialization."""

    model_config = ConfigDict(frozen=True, use_enum_values=True)

    @field_validator("campaign_id", mode="before", check_fields=False)
    @classmethod
    def normalize_campaign_id_field(cls, value: object) -> str | None:
        return normalize_campaign_id(value)


_CAMPAIGN_ID_ALLOWED_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "._:-"
)


def new_campaign_id() -> str:
    """Return a no-secret local correlation ID for one paper alpha campaign."""

    return f"campaign-{uuid4().hex[:12]}"


def normalize_campaign_id(value: object) -> str | None:
    """Normalize optional campaign IDs used to correlate ignored local reports."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("campaign_id must be text")
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 80:
        raise ValueError("campaign_id must be 80 characters or fewer")
    if any(character not in _CAMPAIGN_ID_ALLOWED_CHARS for character in normalized):
        raise ValueError(
            "campaign_id may contain only letters, numbers, dots, underscores, colons, "
            "and hyphens"
        )
    return normalized


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


class CommodityProxyCategory(StrEnum):
    """Commodity-linked research proxy groups."""

    METALS = "metals"
    ENERGY = "energy"
    AGRICULTURE = "agriculture"
    BROAD_BASKET = "broad_basket"


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


class DisabledSignalRunnerStatus(StrEnum):
    """Offline disabled signal runner states for diagnostic-only runs."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class AnalyticalSignalConditionState(StrEnum):
    """Approved non-actionable analytical condition states."""

    CONDITION_MET = "condition_met"
    CONDITION_NOT_MET = "condition_not_met"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID_DATA = "invalid_data"


class AnalyticalSignalEvaluationStatus(StrEnum):
    """Offline analytical signal evaluation run states."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class PaperReadinessRunStatus(StrEnum):
    """Read-only IBKR paper-client readiness run states."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class AlphaShadowRunStatus(StrEnum):
    """Read-only broker-connected alpha shadow run states."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class PaperOrderSmokeRunStatus(StrEnum):
    """Gated IBKR paper-order smoke run states."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class AlphaPaperRunStatus(StrEnum):
    """First strategy-gated paper alpha execution states."""

    COMPLETED = "completed"
    NO_TRADE = "no_trade"
    FAILED = "failed"


class PaperReconcileStatus(StrEnum):
    """Post-paper-run broker reconciliation states."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class AlphaTestSummaryStatus(StrEnum):
    """Post-paper-run campaign summary states."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class AlphaCampaignRunMode(StrEnum):
    """Sequential alpha campaign orchestration modes."""

    SHADOW = "shadow"
    PAPER = "paper"


class AlphaCampaignRunStatus(StrEnum):
    """Sequential alpha campaign orchestration states."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class PaperReadinessStageStatus(StrEnum):
    """Stage-level status for the paper readiness orchestration."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    SKIPPED = "skipped"


class DataQualityGateStatus(StrEnum):
    """Offline data-quality gate states."""

    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"


class EvaluatorComparisonStatus(StrEnum):
    """Broker-free evaluator comparison states."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
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
    positions_query_completed: bool = False
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


class CommodityProxyInstrument(SerializableModel):
    """Broker-free commodity-linked security proxy for research."""

    symbol: str
    name: str
    category: CommodityProxyCategory
    proxy_kind: str = "exchange_traded_product"
    ibkr_sec_type: str = "STK"
    exchange: str = "SMART"
    currency: str = "USD"
    underlying_exposure: str
    futures_contract_enabled: bool = False
    direct_futures_data_enabled: bool = False
    notes: str = ""

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized

    @field_validator(
        "name",
        "proxy_kind",
        "ibkr_sec_type",
        "exchange",
        "currency",
        "underlying_exposure",
    )
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("commodity proxy text fields cannot be empty")
        return normalized.upper() if normalized.upper() in {"STK", "SMART", "USD"} else normalized

    @model_validator(mode="after")
    def validate_proxy_safety(self) -> CommodityProxyInstrument:
        if self.ibkr_sec_type != "STK":
            raise ValueError("commodity proxy instruments must remain STK securities")
        if self.futures_contract_enabled:
            raise ValueError("futures_contract_enabled must remain false")
        if self.direct_futures_data_enabled:
            raise ValueError("direct_futures_data_enabled must remain false")
        return self


class CommodityResearchUniverseRequest(SerializableModel):
    """Offline commodity proxy universe request."""

    symbols: list[str] = Field(default_factory=list)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol.strip()]


class CommodityResearchUniverseReport(SerializableModel):
    """Report for the broker-free commodity research proxy universe."""

    title: str = "Broker-free Commodity Research Universe"
    report_type: str = "commodity_universe"
    command: str = "commodity-universe"
    ok: bool
    request: CommodityResearchUniverseRequest
    symbols_requested: list[str] = Field(default_factory=list)
    instruments: list[CommodityProxyInstrument] = Field(default_factory=list)
    categories: dict[str, list[str]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    commodity_proxy_universe: bool = True
    futures_contracts_enabled: bool = False
    direct_futures_data_enabled: bool = False
    broker_contacted: bool = False
    signal_evaluation_enabled: bool = False
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This commodity universe report is offline-only and does not contact a broker."
    )
    no_execution_statement: str = (
        "This command lists commodity-linked security proxies for research only. "
        "Direct futures contracts, signal evaluation, order intents, execution, "
        "fills, portfolio accounting, and P&L are disabled."
    )
    final_status: str = "unknown"
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_commodity_universe_safety(self) -> CommodityResearchUniverseReport:
        return _validate_commodity_universe_flags(self)


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
    zero_volume_sample_timestamps: list[str] = Field(default_factory=list)
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
    zero_volume_count: int = 0
    zero_volume_sample_timestamps: list[str] = Field(default_factory=list)
    volume_count: int = 0
    total_volume: Decimal = Decimal("0")
    average_volume: Decimal | None = None
    dollar_volume_count: int = 0
    total_dollar_volume: Decimal = Decimal("0")
    average_dollar_volume: Decimal | None = None
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


class AnalyticalSignalEvaluatorMetadata(SerializableModel):
    """Metadata for a broker-free analytical signal evaluator."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    required_fields: list[str] = Field(
        default_factory=lambda: ["open", "high", "low", "close", "volume"]
    )
    required_lookback_bars: int = 20
    supported_bar_sizes: list[str] = Field(default_factory=lambda: ["5 mins"])
    broker_required: bool = False
    emits_trading_actions: bool = False
    emits_order_intents: bool = False

    @field_validator("name", "version")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("analytical evaluator metadata text fields cannot be empty")
        return normalized

    @field_validator("required_fields", "supported_bar_sizes")
    @classmethod
    def normalize_text_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("required_lookback_bars")
    @classmethod
    def validate_required_lookback(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("required_lookback_bars must be positive")
        return value

    @model_validator(mode="after")
    def validate_broker_free_metadata(self) -> AnalyticalSignalEvaluatorMetadata:
        if self.broker_required:
            raise ValueError("broker_required must remain false")
        if self.emits_trading_actions:
            raise ValueError("emits_trading_actions must remain false")
        if self.emits_order_intents:
            raise ValueError("emits_order_intents must remain false")
        if not self.required_fields:
            raise ValueError("required_fields must not be empty")
        if not self.supported_bar_sizes:
            raise ValueError("supported_bar_sizes must not be empty")
        return self


class AnalyticalSignalEvaluationRequest(SerializableModel):
    """Offline analytical signal evaluation request."""

    symbols: list[str] = Field(default_factory=list)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    requested_bar_size: str | None = None
    requested_what_to_show: str | None = None
    latest: bool = True
    snapshot_timestamp: str | None = None
    strict: bool = False
    base_data_path: str = "data/historical"
    evaluator_name: str = "moving_average_relationship_diagnostic"
    short_window: int = 5
    long_window: int = 20

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol.strip()]

    @field_validator(
        "requested_bar_size",
        "requested_what_to_show",
        "snapshot_timestamp",
        "evaluator_name",
    )
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

    @field_validator("short_window", "long_window")
    @classmethod
    def validate_windows_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("evaluator windows must be positive")
        return value

    @model_validator(mode="after")
    def validate_window_order(self) -> AnalyticalSignalEvaluationRequest:
        if self.short_window > self.long_window:
            raise ValueError("short_window must be less than or equal to long_window")
        return self


class AnalyticalSignalObservation(SerializableModel):
    """One non-actionable analytical observation for a symbol and frame."""

    evaluator_name: str
    evaluator_version: str
    symbol: str
    timestamp: datetime
    frame_index: int
    condition_name: str
    condition_state: AnalyticalSignalConditionState
    numeric_value: Decimal | None = None
    threshold_or_reference_value: Decimal | None = None
    required_lookback_bars: int
    available_bars: int = 0
    used_bars: int = 0
    warmup_complete: bool = False
    data_valid: bool = False
    explanation: str = ""
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True

    @field_validator("evaluator_name", "evaluator_version", "condition_name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("analytical observation text fields cannot be empty")
        return normalized

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized

    @field_validator("condition_name", "explanation")
    @classmethod
    def validate_non_actionable_text(cls, value: str) -> str:
        return _validate_no_analytical_action_vocabulary(value)

    @field_validator("required_lookback_bars")
    @classmethod
    def validate_required_lookback(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("required_lookback_bars must be positive")
        return value

    @field_validator("available_bars", "used_bars", "frame_index")
    @classmethod
    def validate_non_negative_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("analytical observation counts must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_observation_safety(self) -> AnalyticalSignalObservation:
        return _validate_analytical_signal_safety_flags(self)


class AnalyticalSignalEvaluationDiagnostics(SerializableModel):
    """Run-level diagnostics for analytical signal evaluation."""

    evaluator_name: str = "moving_average_relationship_diagnostic"
    evaluator_version: str = "0.1.0"
    symbols: list[str] = Field(default_factory=list)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    feed_status: BacktestFeedStatus = BacktestFeedStatus.FAILED
    evaluation_status: AnalyticalSignalEvaluationStatus = (
        AnalyticalSignalEvaluationStatus.FAILED
    )
    frame_count: int = 0
    contexts_built: int = 0
    observations_count: int = 0
    observations_by_state: dict[str, int] = Field(default_factory=dict)
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    warmup_observations: int = 0
    invalid_data_observations: int = 0
    missing_symbols_by_frame_count: int = 0
    missing_symbols_by_symbol: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    signal_evaluation_enabled: bool = True
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True

    @model_validator(mode="after")
    def validate_diagnostic_safety(self) -> AnalyticalSignalEvaluationDiagnostics:
        return _validate_analytical_signal_safety_flags(self)


class AnalyticalSignalEvaluationResult(SerializableModel):
    """Result of evaluating analytical observations over an offline feed."""

    ok: bool
    request: AnalyticalSignalEvaluationRequest
    metadata: AnalyticalSignalEvaluatorMetadata
    feed_summary: BacktestDataFeedSummary | None = None
    diagnostics: AnalyticalSignalEvaluationDiagnostics
    observations: list[AnalyticalSignalObservation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    signal_evaluation_enabled: bool = True
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_result_safety(self) -> AnalyticalSignalEvaluationResult:
        return _validate_analytical_signal_safety_flags(self)


class AnalyticalSignalEvaluationReport(SerializableModel):
    """Report for the broker-free analytical signal evaluator."""

    title: str = "Broker-free Analytical Signal Evaluation"
    report_type: str = "signal_evaluation"
    command: str = "signal-evaluate"
    ok: bool
    request: AnalyticalSignalEvaluationRequest
    metadata: AnalyticalSignalEvaluatorMetadata
    symbols_requested: list[str] = Field(default_factory=list)
    feed_summary: BacktestDataFeedSummary | None = None
    result: AnalyticalSignalEvaluationResult
    diagnostics: AnalyticalSignalEvaluationDiagnostics
    observations: list[AnalyticalSignalObservation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    signal_evaluation_enabled: bool = True
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This analytical signal evaluation report reads local historical snapshots "
        "only and does not contact a broker."
    )
    no_execution_statement: str = (
        "This run emitted non-actionable analytical observations only. No trading "
        "signals, order intents, order simulation, broker routing, fills, portfolio "
        "accounting, or P&L calculation was performed."
    )
    final_status: str = "unknown"
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_report_safety(self) -> AnalyticalSignalEvaluationReport:
        return _validate_analytical_signal_safety_flags(self)


class PaperReadinessRunRequest(SerializableModel):
    """Read-only first paper-client orchestration request."""

    symbols: list[str] = Field(
        default_factory=lambda: ["SPY", "AAPL", "GLD", "USO", "DBA"]
    )
    commodity_symbols: list[str] = Field(default_factory=lambda: ["GLD", "USO", "DBA"])
    duration: str = "1 D"
    bar_size: str = "5 mins"
    what_to_show: str = "TRADES"
    use_rth: int = 1
    broker_timeout_seconds: float = 15
    history_timeout_seconds: float = 30
    broker_stage_pause_seconds: float = 1
    latest: bool = True
    strict: bool = False
    base_data_path: str = "data/historical"
    short_window: int = 5
    long_window: int = 20

    @field_validator("symbols", "commodity_symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        symbols = [symbol.strip().upper() for symbol in value if symbol.strip()]
        if not symbols:
            raise ValueError("paper readiness symbols must not be empty")
        return symbols

    @field_validator("duration", "bar_size", "what_to_show", "base_data_path")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("paper readiness text fields must not be empty")
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

    @field_validator("broker_timeout_seconds", "history_timeout_seconds")
    @classmethod
    def validate_timeout_seconds(cls, value: float) -> float:
        if value <= 0 or value > 120:
            raise ValueError("paper readiness timeouts must be greater than 0 and no more than 120")
        return value

    @field_validator("broker_stage_pause_seconds")
    @classmethod
    def validate_broker_stage_pause_seconds(cls, value: float) -> float:
        if value < 0 or value > 30:
            raise ValueError("broker stage pause must be between 0 and 30 seconds")
        return value

    @field_validator("short_window", "long_window")
    @classmethod
    def validate_windows_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("paper readiness evaluator windows must be positive")
        return value

    @model_validator(mode="after")
    def validate_window_order(self) -> PaperReadinessRunRequest:
        if self.short_window > self.long_window:
            raise ValueError("short_window must be less than or equal to long_window")
        return self


class PaperReadinessRunStage(SerializableModel):
    """One sequential stage in the paper readiness run."""

    name: str
    command: str
    ok: bool
    final_status: PaperReadinessStageStatus
    started_at: datetime
    finished_at: datetime
    report_paths: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @field_validator("name", "command")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("paper readiness stage text fields must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_failed_stage_has_errors(self) -> PaperReadinessRunStage:
        if self.final_status == PaperReadinessStageStatus.FAILED and not self.errors:
            raise ValueError("failed paper readiness stages must include errors")
        return self


class PaperReadinessRunReport(SerializableModel):
    """Read-only first paper-client orchestration report."""

    title: str = "Read-only IBKR Paper Readiness Run"
    report_type: str = "paper_readiness_run"
    command: str = "paper-readiness-run"
    ok: bool
    request: PaperReadinessRunRequest
    selected_universe: list[str] = Field(default_factory=list)
    commodity_symbols: list[str] = Field(default_factory=list)
    stages: list[PaperReadinessRunStage] = Field(default_factory=list)
    stage_statuses: dict[str, str] = Field(default_factory=dict)
    report_paths: dict[str, str] = Field(default_factory=dict)
    broker_connected: bool = False
    account_summary_verified: bool = False
    account_summary_source: str = "unavailable"
    account_ids_masked: list[str] = Field(default_factory=list)
    account_summary_fields_by_account: dict[str, list[str]] = Field(default_factory=dict)
    history_snapshot_written: bool = False
    history_load_completed: bool = False
    commodity_universe_verified: bool = False
    signal_evaluation_completed: bool = False
    readiness_status_by_symbol: dict[str, str] = Field(default_factory=dict)
    load_status_by_symbol: dict[str, str] = Field(default_factory=dict)
    partial_symbols: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    submitted_orders: bool = False
    paper_orders_enabled: bool = False
    configured_allow_paper_orders: bool = False
    read_only_api_expected: bool = True
    order_routing_enabled: bool = False
    broker_contacted: bool = False
    broker_contact_read_only: bool = True
    signal_evaluation_enabled: bool = True
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    futures_contracts_enabled: bool = False
    direct_futures_data_enabled: bool = False
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This readiness run may contact IBKR through read-only account and market-data "
        "requests, but order routing is disabled and no orders are submitted."
    )
    futures_scope_statement: str = (
        "Direct futures contracts remain out of scope; commodity exposure uses "
        "security proxies only."
    )
    final_status: PaperReadinessRunStatus
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("selected_universe", "commodity_symbols", "partial_symbols")
    @classmethod
    def normalize_report_symbols(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol.strip()]

    @model_validator(mode="after")
    def validate_readiness_safety(self) -> PaperReadinessRunReport:
        if self.submitted_orders:
            raise ValueError("submitted_orders must remain false")
        if self.paper_orders_enabled:
            raise ValueError("paper_orders_enabled must remain false")
        if not self.read_only_api_expected:
            raise ValueError("read_only_api_expected must remain true")
        if self.order_routing_enabled:
            raise ValueError("order_routing_enabled must remain false")
        if not self.broker_contact_read_only:
            raise ValueError("broker_contact_read_only must remain true")
        if not self.signal_evaluation_enabled:
            raise ValueError("signal_evaluation_enabled must remain true")
        if self.generated_signals:
            raise ValueError("generated_signals must remain false")
        if self.signal_count != 0:
            raise ValueError("signal_count must remain 0")
        if self.generated_orders:
            raise ValueError("generated_orders must remain false")
        if self.order_intents_generated:
            raise ValueError("order_intents_generated must remain false")
        if self.orders_simulated:
            raise ValueError("orders_simulated must remain false")
        if self.fills_simulated:
            raise ValueError("fills_simulated must remain false")
        if self.pnl_calculated:
            raise ValueError("pnl_calculated must remain false")
        if self.portfolio_accounting:
            raise ValueError("portfolio_accounting must remain false")
        if self.futures_contracts_enabled:
            raise ValueError("futures_contracts_enabled must remain false")
        if self.direct_futures_data_enabled:
            raise ValueError("direct_futures_data_enabled must remain false")
        if not self.no_order_guarantee:
            raise ValueError("no_order_guarantee must remain true")
        return self


class AlphaShadowRunRequest(SerializableModel):
    """Read-only alpha shadow run request for the first SPY-only paper test."""

    campaign_id: str | None = None
    symbols: list[str] = Field(default_factory=lambda: ["SPY"])
    duration: str = "1 D"
    bar_size: str = "5 mins"
    what_to_show: str = "TRADES"
    use_rth: int = 1
    broker_timeout_seconds: float = 15
    history_timeout_seconds: float = 30
    broker_stage_pause_seconds: float = 1
    latest: bool = True
    strict: bool = False
    base_data_path: str = "data/historical"
    short_window: int = 5
    long_window: int = 20
    min_bars: int = 50
    max_zero_volume_bars: int = 0
    min_average_volume: Decimal = Decimal("100")
    min_average_dollar_volume: Decimal = Decimal("5000")
    max_trade_notional: Decimal = Decimal("1000")
    max_open_positions: int = 1

    @field_validator("symbols")
    @classmethod
    def validate_spy_only(cls, value: list[str]) -> list[str]:
        symbols = [symbol.strip().upper() for symbol in value if symbol.strip()]
        if symbols != ["SPY"]:
            raise ValueError("alpha-shadow-run is SPY-only in this milestone")
        return symbols

    @field_validator("duration", "bar_size", "what_to_show", "base_data_path")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("alpha shadow request text fields must not be empty")
        return normalized

    @field_validator("what_to_show")
    @classmethod
    def normalize_what_to_show(cls, value: str) -> str:
        return value.upper()

    @field_validator("use_rth")
    @classmethod
    def validate_use_rth(cls, value: int) -> int:
        if value not in {0, 1}:
            raise ValueError("use_rth must be 0 or 1")
        return value

    @field_validator(
        "broker_timeout_seconds",
        "history_timeout_seconds",
        "broker_stage_pause_seconds",
    )
    @classmethod
    def validate_seconds(cls, value: float) -> float:
        if value < 0 or value > 120:
            raise ValueError("alpha shadow timing settings must be 0 through 120 seconds")
        return value

    @field_validator("short_window", "long_window", "min_bars", "max_open_positions")
    @classmethod
    def validate_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("alpha shadow integer settings must be positive")
        return value

    @field_validator("max_zero_volume_bars")
    @classmethod
    def validate_non_negative_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("max_zero_volume_bars must be non-negative")
        return value

    @field_validator(
        "min_average_volume",
        "min_average_dollar_volume",
        "max_trade_notional",
    )
    @classmethod
    def validate_positive_decimals(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("alpha shadow decimal settings must be positive")
        return value

    @model_validator(mode="after")
    def validate_windows(self) -> AlphaShadowRunRequest:
        if self.short_window > self.long_window:
            raise ValueError("short_window must be less than or equal to long_window")
        return self


class AlphaShadowRunReport(SerializableModel):
    """Read-only broker-connected shadow alpha report."""

    title: str = "Read-only IBKR Alpha Shadow Run"
    report_type: str = "alpha_shadow_run"
    command: str = "alpha-shadow-run"
    commit_sha: str | None = None
    campaign_id: str | None = None
    ok: bool
    request: AlphaShadowRunRequest
    selected_universe: list[str] = Field(default_factory=list)
    stages: list[PaperReadinessRunStage] = Field(default_factory=list)
    stage_statuses: dict[str, str] = Field(default_factory=dict)
    report_paths: dict[str, str] = Field(default_factory=dict)
    broker_connected: bool = False
    account_summary_verified: bool = False
    account_summary_source: str = "unavailable"
    account_ids_masked: list[str] = Field(default_factory=list)
    history_snapshot_written: bool = False
    history_load_completed: bool = False
    data_quality_completed: bool = False
    signal_evaluation_completed: bool = False
    trade_plan_completed: bool = False
    risk_completed: bool = False
    simulation_completed: bool = False
    shadow_risk_mode: str = "dry_run"
    shadow_quote_source: str = "historical_snapshot_shadow_quote"
    source_bar_timestamp_by_symbol: dict[str, str] = Field(default_factory=dict)
    data_quality_status_by_symbol: dict[str, str] = Field(default_factory=dict)
    shadow_signals: list[Signal] = Field(default_factory=list)
    trade_plans: list[TradePlan] = Field(default_factory=list)
    risk_decisions: list[RiskDecision] = Field(default_factory=list)
    execution_results: list[ExecutionResult] = Field(default_factory=list)
    shadow_signal_count: int = 0
    trade_plan_count: int = 0
    risk_decision_count: int = 0
    risk_approved_count: int = 0
    simulation_result_count: int = 0
    simulated_fill_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    submitted_orders: bool = False
    paper_orders_enabled: bool = False
    configured_allow_paper_orders: bool = False
    live_orders_enabled: bool = False
    read_only_api_expected: bool = True
    order_routing_enabled: bool = False
    broker_contacted: bool = False
    broker_contact_read_only: bool = True
    paper_execution_enabled: bool = False
    simulator_routed: bool = False
    generated_signals: bool = False
    generated_trade_plans: bool = False
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    futures_contracts_enabled: bool = False
    direct_futures_data_enabled: bool = False
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This alpha shadow run may contact IBKR through read-only account and "
        "historical-data requests, then routes shadow decisions to the simulator only."
    )
    no_paper_execution_statement: str = (
        "No paper orders are submitted. IBKR Read-Only API is expected to remain enabled, "
        "ALLOW_PAPER_ORDERS must remain false, and broker order routing is disabled."
    )
    final_status: AlphaShadowRunStatus
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("selected_universe")
    @classmethod
    def normalize_selected_universe(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol.strip()]

    @model_validator(mode="after")
    def validate_alpha_shadow_safety(self) -> AlphaShadowRunReport:
        if self.submitted_orders:
            raise ValueError("alpha-shadow-run must not submit orders")
        if self.paper_orders_enabled:
            raise ValueError("paper_orders_enabled must remain false for alpha-shadow-run")
        if self.live_orders_enabled:
            raise ValueError("live_orders_enabled must remain false")
        if not self.read_only_api_expected:
            raise ValueError("read_only_api_expected must remain true")
        if self.order_routing_enabled:
            raise ValueError("broker order routing must remain false")
        if not self.broker_contact_read_only:
            raise ValueError("broker contact must remain read-only")
        if self.paper_execution_enabled:
            raise ValueError("paper execution must remain disabled")
        if self.generated_orders:
            raise ValueError("alpha-shadow-run must not generate broker orders")
        if self.order_intents_generated:
            raise ValueError("alpha-shadow-run must not generate order intents")
        if self.pnl_calculated:
            raise ValueError("alpha-shadow-run must not calculate P&L")
        if self.portfolio_accounting:
            raise ValueError("alpha-shadow-run must not perform portfolio accounting")
        if self.futures_contracts_enabled:
            raise ValueError("futures_contracts_enabled must remain false")
        if self.direct_futures_data_enabled:
            raise ValueError("direct_futures_data_enabled must remain false")
        if not self.no_order_guarantee:
            raise ValueError("no_order_guarantee must remain true")
        return self


class PaperOrderCallbackEvent(SerializableModel):
    """Masked callback evidence from the IBKR paper-order smoke path."""

    event_type: str
    order_id: int | None = None
    perm_id: int | None = None
    status: str | None = None
    filled_quantity: Decimal | None = None
    remaining_quantity: Decimal | None = None
    message: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)


class PaperOrderQuote(SerializableModel):
    """Quote snapshot used to derive a non-marketable smoke-test limit price."""

    symbol: str
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    close: Decimal | None = None
    quote_timestamp: datetime | None = None
    quote_age_seconds: float | None = None
    stale: bool = True
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_quote_prices(self) -> PaperOrderQuote:
        for field_name in ("bid", "ask", "last", "close"):
            value = getattr(self, field_name)
            if value is not None and value <= 0:
                raise ValueError(f"{field_name} must be positive when provided")
        if self.bid is not None and self.ask is not None and self.ask < self.bid:
            raise ValueError("ask must be greater than or equal to bid")
        return self


class PaperOrderSmokeRequest(SerializableModel):
    """Strict request for the first paper-only order lifecycle smoke test."""

    campaign_id: str | None = None
    symbol: str = "SPY"
    action: TradeAction = TradeAction.BUY
    quantity: int = 1
    order_type: OrderType = OrderType.LIMIT
    time_in_force: str = "DAY"
    transmit: bool = False
    allow_fill: bool = False
    cancel_after_seconds: float = 30
    confirm: str = ""
    max_trade_notional: Decimal = Decimal("1000")
    quote_max_age_seconds: int = 900
    timeout_seconds: float = 30

    @field_validator("symbol")
    @classmethod
    def validate_spy_only(cls, value: str) -> str:
        symbol = value.strip().upper()
        if symbol != "SPY":
            raise ValueError("paper-order-smoke is SPY-only in this milestone")
        return symbol

    @field_validator("quantity")
    @classmethod
    def validate_single_share(cls, value: int) -> int:
        if value != 1:
            raise ValueError("paper-order-smoke requires quantity 1")
        return value

    @field_validator("time_in_force")
    @classmethod
    def validate_day_tif(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized != "DAY":
            raise ValueError("paper-order-smoke supports DAY time-in-force only")
        return normalized

    @field_validator("cancel_after_seconds", "timeout_seconds")
    @classmethod
    def validate_seconds(cls, value: float) -> float:
        if value < 0 or value > 120:
            raise ValueError("paper-order-smoke timing settings must be 0 through 120 seconds")
        return value

    @field_validator("max_trade_notional")
    @classmethod
    def validate_max_notional(cls, value: Decimal) -> Decimal:
        if value <= 0 or value > Decimal("1000"):
            raise ValueError(
                "paper-order-smoke max notional must be greater than 0 "
                "and no more than 1000"
            )
        return value

    @field_validator("quote_max_age_seconds")
    @classmethod
    def validate_quote_age(cls, value: int) -> int:
        if value <= 0 or value > 3600:
            raise ValueError("quote_max_age_seconds must be greater than 0 and no more than 3600")
        return value

    @model_validator(mode="after")
    def validate_order_shape(self) -> PaperOrderSmokeRequest:
        if self.action != TradeAction.BUY:
            raise ValueError(
                "paper-order-smoke supports BUY only; SELL is reserved for reduce-only"
            )
        if self.order_type != OrderType.LIMIT:
            raise ValueError("paper-order-smoke supports limit orders only")
        return self


class PaperOrderSmokeReport(SerializableModel):
    """No-secret report for the gated IBKR paper-order smoke command."""

    title: str = "IBKR Paper Order Smoke Run"
    report_type: str = "paper_order_smoke"
    command: str = "paper-order-smoke"
    commit_sha: str | None = None
    campaign_id: str | None = None
    ok: bool
    request: PaperOrderSmokeRequest
    mode: str
    host: str
    port: int
    client_id: int
    broker_kind: str
    broker_connected: bool = False
    account_summary_verified: bool = False
    account_ids_masked: list[str] = Field(default_factory=list)
    existing_open_order_count: int = 0
    duplicate_open_order_detected: bool = False
    quote: PaperOrderQuote | None = None
    limit_price: Decimal | None = None
    notional: Decimal | None = None
    order_id: int | None = None
    perm_id: int | None = None
    order_status: str | None = None
    fill_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal | None = None
    cancel_requested: bool = False
    canceled: bool = False
    cancel_status: str | None = None
    callback_timeline: list[PaperOrderCallbackEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    submitted_orders: bool = False
    paper_orders_enabled: bool = False
    configured_allow_paper_orders: bool = False
    live_orders_enabled: bool = False
    read_only_api_expected: bool = False
    order_routing_enabled: bool = False
    paper_execution_enabled: bool = False
    live_route_possible: bool = False
    order_api_invoked: bool = False
    place_order_invoked: bool = False
    cancel_order_invoked: bool = False
    transmitted: bool = False
    market_order_requested: bool = False
    fractional_quantity_requested: bool = False
    cash_quantity_requested: bool = False
    short_sale_attempted: bool = False
    multi_order_batch: bool = False
    futures_contracts_enabled: bool = False
    options_contracts_enabled: bool = False
    algo_orders_enabled: bool = False
    bracket_orders_enabled: bool = False
    no_live_order_guarantee: bool = True
    safety_statement: str = (
        "This command is limited to one SPY STK/SMART/USD LMT DAY paper-order "
        "smoke test on localhost paper TWS/Gateway ports 7497/4002. Live ports, live mode, "
        "market orders, direct futures, options, algos, brackets, shorts, "
        "fractional or cash-quantity stock orders, and batches are refused."
    )
    final_status: PaperOrderSmokeRunStatus
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_paper_order_smoke_safety(self) -> PaperOrderSmokeReport:
        if self.live_orders_enabled:
            raise ValueError("live_orders_enabled must remain false")
        if self.live_route_possible:
            raise ValueError("live_route_possible must remain false")
        if self.market_order_requested:
            raise ValueError("market orders are not allowed")
        if self.fractional_quantity_requested:
            raise ValueError("fractional stock quantities are not allowed")
        if self.cash_quantity_requested:
            raise ValueError("cash quantity stock orders are not allowed")
        if self.short_sale_attempted:
            raise ValueError("short sale attempts are not allowed")
        if self.multi_order_batch:
            raise ValueError("multi-order batches are not allowed")
        if self.futures_contracts_enabled:
            raise ValueError("direct futures contracts must remain disabled")
        if self.options_contracts_enabled:
            raise ValueError("options contracts must remain disabled")
        if self.algo_orders_enabled:
            raise ValueError("algo orders must remain disabled")
        if self.bracket_orders_enabled:
            raise ValueError("bracket orders must remain disabled")
        if not self.no_live_order_guarantee:
            raise ValueError("no_live_order_guarantee must remain true")
        if self.request.transmit is False and self.submitted_orders:
            raise ValueError("untransmitted smoke rehearsals must not be marked submitted")
        return self


class AlphaPaperRunRequest(SerializableModel):
    """Strict request for the first strategy-gated SPY paper alpha run."""

    campaign_id: str | None = None
    symbol: str = "SPY"
    quantity: int = 1
    allow_fill: bool = False
    cancel_after_seconds: float = 30
    confirm: str = ""
    max_trade_notional: Decimal = Decimal("1000")
    timeout_seconds: float = 30
    max_report_age_hours: int = 24
    alpha_shadow_report_path: str = "reports/latest_alpha_shadow_run.json"
    paper_smoke_report_path: str = "reports/latest_paper_order_smoke.json"

    @field_validator("symbol")
    @classmethod
    def validate_spy_only(cls, value: str) -> str:
        symbol = value.strip().upper()
        if symbol != "SPY":
            raise ValueError("alpha-paper-run is SPY-only in this milestone")
        return symbol

    @field_validator("quantity")
    @classmethod
    def validate_single_share(cls, value: int) -> int:
        if value != 1:
            raise ValueError("alpha-paper-run requires quantity 1")
        return value

    @field_validator("cancel_after_seconds", "timeout_seconds")
    @classmethod
    def validate_seconds(cls, value: float) -> float:
        if value < 0 or value > 120:
            raise ValueError("alpha-paper-run timing settings must be 0 through 120 seconds")
        return value

    @field_validator("max_trade_notional")
    @classmethod
    def validate_max_notional(cls, value: Decimal) -> Decimal:
        if value <= 0 or value > Decimal("1000"):
            raise ValueError(
                "alpha-paper-run max notional must be greater than 0 and no more than 1000"
            )
        return value

    @field_validator("max_report_age_hours")
    @classmethod
    def validate_report_age(cls, value: int) -> int:
        if value <= 0 or value > 168:
            raise ValueError("max_report_age_hours must be greater than 0 and no more than 168")
        return value

    @field_validator("alpha_shadow_report_path", "paper_smoke_report_path")
    @classmethod
    def validate_report_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("report paths must not be empty")
        return normalized


class AlphaPaperRunReport(SerializableModel):
    """No-secret report for the first strategy-gated paper alpha run."""

    title: str = "IBKR Alpha Paper Run"
    report_type: str = "alpha_paper_run"
    command: str = "alpha-paper-run"
    ok: bool
    request: AlphaPaperRunRequest
    mode: str
    host: str
    port: int
    client_id: int
    broker_kind: str
    commit_sha: str | None = None
    campaign_id: str | None = None
    source_report_paths: dict[str, str] = Field(default_factory=dict)
    source_report_campaign_ids: dict[str, str | None] = Field(default_factory=dict)
    alpha_shadow_report_verified: bool = False
    paper_smoke_report_verified: bool = False
    alpha_shadow_commit_sha: str | None = None
    paper_smoke_commit_sha: str | None = None
    alpha_shadow_timestamp: datetime | None = None
    paper_smoke_timestamp: datetime | None = None
    shadow_signal: str | None = None
    risk_approved: bool = False
    no_trade_reason: str | None = None
    paper_order_report: PaperOrderSmokeReport | None = None
    account_ids_masked: list[str] = Field(default_factory=list)
    submitted_orders: bool = False
    paper_orders_enabled: bool = False
    configured_allow_paper_orders: bool = False
    live_orders_enabled: bool = False
    read_only_api_expected: bool = False
    order_routing_enabled: bool = False
    paper_execution_enabled: bool = False
    live_route_possible: bool = False
    order_api_invoked: bool = False
    place_order_invoked: bool = False
    cancel_order_invoked: bool = False
    order_id: int | None = None
    perm_id: int | None = None
    order_status: str | None = None
    fill_quantity: Decimal = Decimal("0")
    cancel_requested: bool = False
    canceled: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    market_order_requested: bool = False
    fractional_quantity_requested: bool = False
    cash_quantity_requested: bool = False
    short_sale_attempted: bool = False
    multi_order_batch: bool = False
    futures_contracts_enabled: bool = False
    options_contracts_enabled: bool = False
    algo_orders_enabled: bool = False
    bracket_orders_enabled: bool = False
    safety_statement: str = (
        "This command may submit at most one SPY BUY 1 STK/SMART/USD LMT DAY "
        "paper order after a same-commit read-only alpha shadow report and a "
        "same-commit paper-order smoke report pass within the configured freshness window."
    )
    final_status: AlphaPaperRunStatus
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_alpha_paper_safety(self) -> AlphaPaperRunReport:
        if self.live_orders_enabled:
            raise ValueError("live_orders_enabled must remain false")
        if self.live_route_possible:
            raise ValueError("live_route_possible must remain false")
        if self.market_order_requested:
            raise ValueError("market orders are not allowed")
        if self.fractional_quantity_requested:
            raise ValueError("fractional stock quantities are not allowed")
        if self.cash_quantity_requested:
            raise ValueError("cash quantity stock orders are not allowed")
        if self.short_sale_attempted:
            raise ValueError("short sale attempts are not allowed")
        if self.multi_order_batch:
            raise ValueError("multi-order batches are not allowed")
        if self.futures_contracts_enabled:
            raise ValueError("direct futures contracts must remain disabled")
        if self.options_contracts_enabled:
            raise ValueError("options contracts must remain disabled")
        if self.algo_orders_enabled:
            raise ValueError("algo orders must remain disabled")
        if self.bracket_orders_enabled:
            raise ValueError("bracket orders must remain disabled")
        if self.submitted_orders and self.final_status == AlphaPaperRunStatus.NO_TRADE:
            raise ValueError("no_trade reports must not submit orders")
        if self.submitted_orders and not self.paper_orders_enabled:
            raise ValueError("submitted paper orders require paper_orders_enabled")
        return self


class PaperReconcileRequest(SerializableModel):
    """Read-only post-paper-run broker reconciliation request."""

    campaign_id: str | None = None
    timeout_seconds: float = 30
    paper_smoke_report_path: str = "reports/latest_paper_order_smoke.json"
    alpha_paper_report_path: str = "reports/latest_alpha_paper_run.json"

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        if value <= 0 or value > 120:
            raise ValueError("paper-reconcile timeout must be greater than 0 and no more than 120")
        return value

    @field_validator("paper_smoke_report_path", "alpha_paper_report_path")
    @classmethod
    def validate_report_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("paper-reconcile report paths must not be empty")
        return normalized


class BrokerOpenOrderSnapshot(SerializableModel):
    """Read-only open-order row captured from IBKR."""

    order_id: int
    symbol: str
    action: str | None = None
    status: str | None = None
    perm_id: int | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class PaperOrderEvidence(SerializableModel):
    """Order evidence extracted from ignored local paper-run reports."""

    source: str
    report_path: str
    report_type: str | None = None
    campaign_id: str | None = None
    ok: bool | None = None
    final_status: str | None = None
    commit_sha: str | None = None
    timestamp: datetime | None = None
    submitted_orders: bool = False
    order_id: int | None = None
    perm_id: int | None = None
    order_status: str | None = None
    fill_quantity: Decimal | None = None
    canceled: bool = False
    cancel_requested: bool = False
    live_orders_enabled: bool = False
    live_route_possible: bool = False


class PaperReconcileReport(SerializableModel):
    """No-secret read-only reconciliation after paper execution windows."""

    title: str = "IBKR Paper Reconciliation"
    report_type: str = "paper_reconcile"
    command: str = "paper-reconcile"
    ok: bool
    request: PaperReconcileRequest
    mode: str
    host: str
    port: int
    client_id: int
    broker_kind: str
    commit_sha: str | None = None
    campaign_id: str | None = None
    broker_connected: bool = False
    account_summary_verified: bool = False
    account_summary_source: str = "unavailable_or_mock_fallback_rejected"
    account_ids_masked: list[str] = Field(default_factory=list)
    account_snapshot: dict[str, Any] = Field(default_factory=dict)
    positions_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    positions_source: str = "unavailable_or_mock_fallback_rejected"
    broker_positions_available: bool = False
    positions_query_completed: bool = False
    zero_positions_confirmed: bool = False
    positions_unavailable_reason: str | None = None
    open_orders: list[BrokerOpenOrderSnapshot] = Field(default_factory=list)
    open_order_count: int = 0
    open_order_source: str = "broker_read_only_open_orders"
    executions_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    executions_available: bool = False
    executions_source: str = "not_implemented_in_current_ibkr_adapter"
    execution_order_ids: list[int] = Field(default_factory=list)
    commission_reports: list[dict[str, Any]] = Field(default_factory=list)
    broker_state_fingerprint: str | None = None
    source_report_paths: dict[str, str] = Field(default_factory=dict)
    source_report_campaign_ids: dict[str, str | None] = Field(default_factory=dict)
    latest_order_evidence: list[PaperOrderEvidence] = Field(default_factory=list)
    latest_order_ids: list[int] = Field(default_factory=list)
    latest_perm_ids: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    submitted_orders: bool = False
    paper_orders_enabled: bool = False
    configured_allow_paper_orders: bool = False
    live_orders_enabled: bool = False
    read_only_api_expected: bool = True
    order_routing_enabled: bool = False
    paper_execution_enabled: bool = False
    live_route_possible: bool = False
    order_api_invoked: bool = False
    place_order_invoked: bool = False
    cancel_order_invoked: bool = False
    market_order_requested: bool = False
    futures_contracts_enabled: bool = False
    direct_futures_data_enabled: bool = False
    options_contracts_enabled: bool = False
    no_order_guarantee: bool = True
    safety_statement: str = (
        "This reconciliation command is read-only. It may query account summary, "
        "positions, and open orders, but it must not submit, modify, or cancel orders."
    )
    final_status: PaperReconcileStatus
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_reconcile_safety(self) -> PaperReconcileReport:
        if self.submitted_orders:
            raise ValueError("paper-reconcile must not submit orders")
        if self.paper_orders_enabled:
            raise ValueError("paper-reconcile requires paper_orders_enabled=false")
        if self.live_orders_enabled:
            raise ValueError("live_orders_enabled must remain false")
        if self.order_routing_enabled:
            raise ValueError("paper-reconcile must keep order_routing_enabled=false")
        if self.paper_execution_enabled:
            raise ValueError("paper execution must remain disabled")
        if self.live_route_possible:
            raise ValueError("live_route_possible must remain false")
        if self.order_api_invoked or self.place_order_invoked or self.cancel_order_invoked:
            raise ValueError("paper-reconcile must not invoke order APIs")
        if self.market_order_requested:
            raise ValueError("market orders are not allowed")
        if self.futures_contracts_enabled or self.direct_futures_data_enabled:
            raise ValueError("direct futures must remain disabled")
        if self.options_contracts_enabled:
            raise ValueError("options must remain disabled")
        if not self.no_order_guarantee:
            raise ValueError("no_order_guarantee must remain true")
        if self.open_order_count != len(self.open_orders):
            raise ValueError("open_order_count must match open_orders length")
        return self


class AlphaTestSummaryRequest(SerializableModel):
    """Offline summary request for a paper alpha test campaign."""

    campaign_id: str | None = None
    alpha_shadow_report_path: str = "reports/latest_alpha_shadow_run.json"
    paper_smoke_report_path: str = "reports/latest_paper_order_smoke.json"
    alpha_paper_report_path: str = "reports/latest_alpha_paper_run.json"
    paper_reconcile_report_path: str = "reports/latest_paper_reconcile.json"
    max_report_age_hours: int = 24

    @field_validator(
        "alpha_shadow_report_path",
        "paper_smoke_report_path",
        "alpha_paper_report_path",
        "paper_reconcile_report_path",
    )
    @classmethod
    def validate_report_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("alpha-test-summary report paths must not be empty")
        return normalized

    @field_validator("max_report_age_hours")
    @classmethod
    def validate_report_age(cls, value: int) -> int:
        if value <= 0 or value > 168:
            raise ValueError("max_report_age_hours must be greater than 0 and no more than 168")
        return value


class AlphaTestSummaryReport(SerializableModel):
    """Offline no-secret summary of one paper alpha campaign."""

    title: str = "IBKR Alpha Test Summary"
    report_type: str = "alpha_test_summary"
    command: str = "alpha-test-summary"
    ok: bool
    request: AlphaTestSummaryRequest
    commit_sha: str | None = None
    campaign_id: str | None = None
    source_report_paths: dict[str, str] = Field(default_factory=dict)
    source_report_campaign_ids: dict[str, str | None] = Field(default_factory=dict)
    source_report_statuses: dict[str, str] = Field(default_factory=dict)
    source_report_commits: dict[str, str | None] = Field(default_factory=dict)
    source_report_timestamps: dict[str, datetime | None] = Field(default_factory=dict)
    alpha_shadow_verified: bool = False
    paper_smoke_verified: bool = False
    alpha_paper_verified: bool = False
    paper_reconcile_verified: bool = False
    account_ids_masked: list[str] = Field(default_factory=list)
    account_summary_verified: bool = False
    open_order_count: int | None = None
    latest_order_ids: list[int] = Field(default_factory=list)
    latest_perm_ids: list[int] = Field(default_factory=list)
    paper_smoke_order_status: str | None = None
    paper_smoke_fill_quantity: Decimal | None = None
    paper_smoke_canceled: bool | None = None
    alpha_paper_order_status: str | None = None
    alpha_paper_fill_quantity: Decimal | None = None
    alpha_paper_canceled: bool | None = None
    next_eligible_for_alpha_window: bool = False
    next_eligibility_reason: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    submitted_orders: bool = False
    paper_orders_enabled: bool = False
    live_orders_enabled: bool = False
    live_route_possible: bool = False
    order_routing_enabled: bool = False
    order_api_invoked: bool = False
    futures_contracts_enabled: bool = False
    direct_futures_data_enabled: bool = False
    commodity_scope: str = (
        "Commodity-linked proxies remain research-only. Direct futures, options, "
        "rollover, margin, and commodity execution are out of scope."
    )
    safety_statement: str = (
        "This summary is offline-only and reads ignored local reports. It does not "
        "contact IBKR or invoke order APIs."
    )
    final_status: AlphaTestSummaryStatus
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_alpha_summary_safety(self) -> AlphaTestSummaryReport:
        if self.live_orders_enabled:
            raise ValueError("live_orders_enabled must remain false")
        if self.live_route_possible:
            raise ValueError("live_route_possible must remain false")
        if self.order_routing_enabled:
            raise ValueError("alpha-test-summary must not enable order routing")
        if self.order_api_invoked:
            raise ValueError("alpha-test-summary must not invoke order APIs")
        if self.futures_contracts_enabled or self.direct_futures_data_enabled:
            raise ValueError("direct futures must remain disabled")
        if self.next_eligible_for_alpha_window and self.errors:
            raise ValueError("summary with errors cannot be next-window eligible")
        if self.next_eligible_for_alpha_window and self.open_order_count not in {0, None}:
            raise ValueError("open orders block next alpha-window eligibility")
        return self


class AlphaCampaignRunRequest(SerializableModel):
    """Sequential orchestration request for one SPY paper alpha campaign."""

    campaign_id: str | None = None
    mode: AlphaCampaignRunMode = AlphaCampaignRunMode.SHADOW
    broker_timeout_seconds: float = 30
    history_timeout_seconds: float = 45
    broker_stage_pause_seconds: float = 2
    cancel_after_seconds: float = 30
    allow_fill: bool = False
    max_report_age_hours: int = 24
    alpha_shadow_report_path: str = "reports/latest_alpha_shadow_run.json"
    paper_smoke_report_path: str = "reports/latest_paper_order_smoke.json"
    read_only_off_confirm: str = ""

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator(
        "broker_timeout_seconds",
        "history_timeout_seconds",
        "broker_stage_pause_seconds",
        "cancel_after_seconds",
    )
    @classmethod
    def validate_seconds(cls, value: float) -> float:
        if value < 0 or value > 120:
            raise ValueError("alpha campaign timing settings must be 0 through 120 seconds")
        return value

    @field_validator("max_report_age_hours")
    @classmethod
    def validate_report_age(cls, value: int) -> int:
        if value <= 0 or value > 168:
            raise ValueError("max_report_age_hours must be greater than 0 and no more than 168")
        return value

    @field_validator("alpha_shadow_report_path", "paper_smoke_report_path")
    @classmethod
    def validate_report_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("alpha campaign source report paths must not be empty")
        return normalized


class AlphaCampaignRunReport(SerializableModel):
    """No-secret report for a sequential SPY paper alpha campaign run."""

    title: str = "IBKR Alpha Campaign Run"
    report_type: str = "alpha_campaign_run"
    command: str = "alpha-campaign-run"
    ok: bool
    request: AlphaCampaignRunRequest
    commit_sha: str | None = None
    campaign_id: str | None = None
    mode: AlphaCampaignRunMode
    stages: list[PaperReadinessRunStage] = Field(default_factory=list)
    stage_statuses: dict[str, str] = Field(default_factory=dict)
    report_paths: dict[str, str] = Field(default_factory=dict)
    alpha_shadow_completed: bool = False
    alpha_paper_completed: bool = False
    paper_reconcile_completed: bool = False
    alpha_test_summary_completed: bool = False
    submitted_orders: bool = False
    paper_orders_enabled: bool = False
    live_orders_enabled: bool = False
    live_route_possible: bool = False
    order_routing_enabled: bool = False
    order_api_invoked: bool = False
    read_only_api_expected_initially: bool = True
    read_only_restore_required: bool = False
    paper_execution_window_confirmed: bool = False
    futures_contracts_enabled: bool = False
    direct_futures_data_enabled: bool = False
    options_contracts_enabled: bool = False
    market_order_requested: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    safety_statement: str = (
        "alpha-campaign-run is a sequential orchestrator over existing SPY-only "
        "paper alpha stages. It does not add live trading, live ports, market orders, "
        "direct futures, options, algos, brackets, shorts, fractional/cash-quantity "
        "stock orders, or multi-order batches."
    )
    final_status: AlphaCampaignRunStatus
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_campaign_safety(self) -> AlphaCampaignRunReport:
        if self.live_orders_enabled or self.live_route_possible:
            raise ValueError("live order routing must remain disabled")
        if self.futures_contracts_enabled or self.direct_futures_data_enabled:
            raise ValueError("direct futures must remain disabled")
        if self.options_contracts_enabled:
            raise ValueError("options must remain disabled")
        if self.market_order_requested:
            raise ValueError("market orders are not allowed")
        if self.paper_orders_enabled and self.mode != AlphaCampaignRunMode.PAPER:
            raise ValueError("paper_orders_enabled is only valid in paper mode")
        return self


class DataQualityGateRequest(SerializableModel):
    """Offline historical data-quality acceptance request."""

    symbols: list[str] = Field(
        default_factory=lambda: ["SPY", "AAPL", "GLD", "USO", "DBA"]
    )
    bar_size: str | None = "5 mins"
    what_to_show: str | None = "TRADES"
    latest: bool = True
    strict: bool = False
    base_data_path: str = "data/historical"
    min_bars: int = 50
    max_zero_volume_bars: int = 0
    min_average_volume: Decimal = Decimal("0")
    min_average_dollar_volume: Decimal = Decimal("0")
    max_duplicate_timestamps: int = 0
    max_missing_gap_count: int = 0
    max_malformed_lines: int = 0
    max_invalid_ohlc_count: int = 0
    max_negative_volume_count: int = 0
    allow_stale_snapshot: bool = False

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        symbols = [symbol.strip().upper() for symbol in value if symbol.strip()]
        if not symbols:
            raise ValueError("data-quality symbols must not be empty")
        return symbols

    @field_validator("bar_size", "what_to_show")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("what_to_show")
    @classmethod
    def normalize_what_to_show(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("base_data_path")
    @classmethod
    def validate_base_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("base_data_path must not be empty")
        return normalized

    @field_validator(
        "min_bars",
        "max_zero_volume_bars",
        "max_duplicate_timestamps",
        "max_missing_gap_count",
        "max_malformed_lines",
        "max_invalid_ohlc_count",
        "max_negative_volume_count",
    )
    @classmethod
    def validate_non_negative_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("data-quality thresholds must be non-negative")
        return value

    @field_validator("min_average_volume", "min_average_dollar_volume")
    @classmethod
    def validate_non_negative_decimal(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("data-quality liquidity thresholds must be non-negative")
        return value


class DataQualityGateIssue(SerializableModel):
    """One offline data-quality gate issue."""

    symbol: str
    severity: str
    code: str
    message: str
    observed_value: int | float | str | bool | Decimal | None = None
    threshold_value: int | float | str | bool | Decimal | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized

    @field_validator("severity", "code", "message")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("data-quality issue text fields must not be empty")
        return normalized


class DataQualityGateSymbolResult(SerializableModel):
    """Per-symbol offline data-quality gate result."""

    symbol: str
    status: DataQualityGateStatus
    bars_count: int = 0
    zero_volume_bars: int = 0
    zero_volume_sample_timestamps: list[str] = Field(default_factory=list)
    average_volume: Decimal | None = None
    average_dollar_volume: Decimal | None = None
    duplicate_timestamps_count: int = 0
    missing_gap_count: int = 0
    malformed_line_count: int = 0
    invalid_ohlc_count: int = 0
    negative_volume_count: int = 0
    stale_snapshot: bool = False
    load_status: str = "unknown"
    readiness_status: str = "unknown"
    snapshot_path: str | None = None
    manifest_path: str | None = None
    issues: list[DataQualityGateIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized

    @model_validator(mode="after")
    def validate_symbol_gate_safety(self) -> DataQualityGateSymbolResult:
        if self.broker_contacted:
            raise ValueError("broker_contacted must remain false")
        if self.order_routing_enabled:
            raise ValueError("order_routing_enabled must remain false")
        if not self.no_order_guarantee:
            raise ValueError("no_order_guarantee must remain true")
        return self


class DataQualityGateReport(SerializableModel):
    """Offline data-quality gate report."""

    title: str = "Broker-free Data Quality Gate"
    report_type: str = "data_quality_gate"
    command: str = "data-quality-gate"
    ok: bool
    request: DataQualityGateRequest
    symbols_requested: list[str] = Field(default_factory=list)
    results: list[DataQualityGateSymbolResult] = Field(default_factory=list)
    readiness_final_status: str = "unknown"
    loader_final_status: str = "unknown"
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    signal_evaluation_enabled: bool = False
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    futures_contracts_enabled: bool = False
    direct_futures_data_enabled: bool = False
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This data-quality gate reads local historical snapshots only and does "
        "not contact a broker."
    )
    final_status: DataQualityGateStatus
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_gate_safety(self) -> DataQualityGateReport:
        return _validate_data_quality_gate_flags(self)


class EvaluatorWindowCandidate(SerializableModel):
    """One diagnostic analytical evaluator parameter candidate."""

    short_window: int
    long_window: int
    label: str | None = None

    @field_validator("short_window", "long_window")
    @classmethod
    def validate_windows_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("comparison windows must be positive")
        return value

    @model_validator(mode="after")
    def validate_window_order(self) -> EvaluatorWindowCandidate:
        if self.short_window > self.long_window:
            raise ValueError("short_window must be less than or equal to long_window")
        return self


class EvaluatorComparisonRequest(SerializableModel):
    """Broker-free analytical evaluator comparison request."""

    symbols: list[str] = Field(
        default_factory=lambda: ["SPY", "AAPL", "GLD", "USO", "DBA"]
    )
    candidates: list[EvaluatorWindowCandidate] = Field(
        default_factory=lambda: [
            EvaluatorWindowCandidate(short_window=5, long_window=20),
            EvaluatorWindowCandidate(short_window=10, long_window=30),
        ]
    )
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    requested_bar_size: str | None = "5 mins"
    requested_what_to_show: str | None = "TRADES"
    latest: bool = True
    strict: bool = False
    snapshot_timestamp: str | None = None
    base_data_path: str = "data/historical"
    train_fraction: float = 0.7

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        symbols = [symbol.strip().upper() for symbol in value if symbol.strip()]
        if not symbols:
            raise ValueError("comparison symbols must not be empty")
        return symbols

    @field_validator(
        "requested_bar_size",
        "requested_what_to_show",
        "snapshot_timestamp",
        "base_data_path",
    )
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("requested_what_to_show")
    @classmethod
    def normalize_requested_what_to_show(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("train_fraction")
    @classmethod
    def validate_train_fraction(cls, value: float) -> float:
        if value <= 0 or value >= 1:
            raise ValueError("train_fraction must be greater than 0 and less than 1")
        return value

    @field_validator("candidates")
    @classmethod
    def validate_candidates(
        cls,
        value: list[EvaluatorWindowCandidate],
    ) -> list[EvaluatorWindowCandidate]:
        if not value:
            raise ValueError("at least one evaluator candidate is required")
        return value


class EvaluatorComparisonSegmentSummary(SerializableModel):
    """Train/test segment summary for one evaluator candidate."""

    segment: str
    frame_count: int = 0
    observation_count: int = 0
    condition_met_count: int = 0
    condition_not_met_count: int = 0
    insufficient_data_count: int = 0
    invalid_data_count: int = 0
    condition_met_rate: float | None = None


class EvaluatorComparisonResult(SerializableModel):
    """One broker-free evaluator comparison result."""

    candidate: EvaluatorWindowCandidate
    ok: bool
    final_status: EvaluatorComparisonStatus
    diagnostics_status: str = "unknown"
    total_observations: int = 0
    train: EvaluatorComparisonSegmentSummary
    test: EvaluatorComparisonSegmentSummary
    condition_met_rate_delta: float | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    signal_evaluation_enabled: bool = True
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True

    @model_validator(mode="after")
    def validate_comparison_result_safety(self) -> EvaluatorComparisonResult:
        return _validate_analytical_signal_safety_flags(self)


class EvaluatorComparisonReport(SerializableModel):
    """Broker-free analytical evaluator comparison report."""

    title: str = "Broker-free Analytical Evaluator Comparison"
    report_type: str = "evaluator_comparison"
    command: str = "evaluator-compare"
    ok: bool
    request: EvaluatorComparisonRequest
    symbols_requested: list[str] = Field(default_factory=list)
    results: list[EvaluatorComparisonResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    signal_evaluation_enabled: bool = True
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This evaluator comparison reads local historical snapshots only and "
        "emits diagnostic condition summaries, not trading signals."
    )
    no_execution_statement: str = (
        "No trading signals, order intents, order simulation, broker routing, "
        "fills, portfolio accounting, or P&L calculation were produced."
    )
    final_status: EvaluatorComparisonStatus
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_comparison_report_safety(self) -> EvaluatorComparisonReport:
        return _validate_analytical_signal_safety_flags(self)


class DisabledSignalRunnerRequest(SerializableModel):
    """Offline disabled signal diagnostic runner request."""

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


class DisabledSignalFrameDiagnostic(SerializableModel):
    """Per-frame result from the disabled signal diagnostic runner."""

    signal_contract_name: str
    signal_contract_version: str
    timestamp: datetime
    frame_index: int
    available_symbols: list[str] = Field(default_factory=list)
    missing_symbols: list[str] = Field(default_factory=list)
    diagnostic: SignalContractDiagnostic
    disabled_signal_runner: bool = True
    signal_contract_validated: bool = True
    signal_evaluation_enabled: bool = False
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True

    @model_validator(mode="after")
    def validate_disabled_output(self) -> DisabledSignalFrameDiagnostic:
        return _validate_disabled_signal_runner_flags(self)


class DisabledSignalRunnerDiagnostics(SerializableModel):
    """Run-level diagnostics from the disabled signal runner."""

    signal_contract_name: str = "disabled_signal_contract"
    signal_contract_version: str = "0.1.0"
    symbols: list[str] = Field(default_factory=list)
    alignment_mode: BacktestAlignmentMode = BacktestAlignmentMode.UNION
    feed_status: BacktestFeedStatus = BacktestFeedStatus.FAILED
    runner_status: DisabledSignalRunnerStatus = DisabledSignalRunnerStatus.FAILED
    frame_count: int = 0
    contexts_built: int = 0
    diagnostics_emitted: int = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    missing_symbols_by_frame_count: int = 0
    missing_symbols_by_symbol: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    disabled_signal_runner: bool = True
    signal_contract_validated: bool = True
    signal_evaluation_enabled: bool = False
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True

    @model_validator(mode="after")
    def validate_disabled_output(self) -> DisabledSignalRunnerDiagnostics:
        return _validate_disabled_signal_runner_flags(self)


class DisabledSignalRunnerResult(SerializableModel):
    """Result of replaying feed frames through the disabled signal contract."""

    ok: bool
    request: DisabledSignalRunnerRequest
    metadata: SignalContractMetadata
    feed_summary: BacktestDataFeedSummary | None = None
    diagnostics: DisabledSignalRunnerDiagnostics
    frame_diagnostics: list[DisabledSignalFrameDiagnostic] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    disabled_signal_runner: bool = True
    signal_contract_validated: bool = True
    signal_evaluation_enabled: bool = False
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_disabled_output(self) -> DisabledSignalRunnerResult:
        return _validate_disabled_signal_runner_flags(self)


class DisabledSignalRunnerReport(SerializableModel):
    """Report for the broker-free disabled signal diagnostic runner."""

    title: str = "Broker-free Disabled Signal Runner"
    report_type: str = "signal_runner"
    command: str = "signal-runner"
    ok: bool
    request: DisabledSignalRunnerRequest
    metadata: SignalContractMetadata
    symbols_requested: list[str] = Field(default_factory=list)
    feed_summary: BacktestDataFeedSummary | None = None
    result: DisabledSignalRunnerResult
    diagnostics: DisabledSignalRunnerDiagnostics
    frame_diagnostics: list[DisabledSignalFrameDiagnostic] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    disabled_signal_runner: bool = True
    signal_contract_validated: bool = True
    signal_evaluation_enabled: bool = False
    generated_signals: bool = False
    signal_count: int = 0
    generated_orders: bool = False
    order_intents_generated: bool = False
    orders_simulated: bool = False
    fills_simulated: bool = False
    pnl_calculated: bool = False
    portfolio_accounting: bool = False
    broker_contacted: bool = False
    order_routing_enabled: bool = False
    no_order_guarantee: bool = True
    no_order_guarantee_statement: str = (
        "This disabled signal runner report reads local historical snapshots only "
        "and does not contact a broker."
    )
    no_execution_statement: str = (
        "This run exercised the disabled signal contract only. Signal evaluation "
        "is disabled. No trading signals, order intents, order simulation, broker "
        "routing, fills, portfolio accounting, or P&L calculation was performed."
    )
    final_status: str = "unknown"
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_disabled_output(self) -> DisabledSignalRunnerReport:
        return _validate_disabled_signal_runner_flags(self)


def _validate_disabled_signal_runner_flags(model: T) -> T:
    if getattr(model, "disabled_signal_runner", False) is not True:
        raise ValueError("disabled_signal_runner must remain true")
    if getattr(model, "signal_contract_validated", False) is not True:
        raise ValueError("signal_contract_validated must remain true")
    if getattr(model, "signal_evaluation_enabled", True):
        raise ValueError("signal_evaluation_enabled must remain false")
    if getattr(model, "generated_signals", True):
        raise ValueError("generated_signals must remain false")
    if getattr(model, "signal_count", 1) != 0:
        raise ValueError("signal_count must remain 0")
    if getattr(model, "generated_orders", True):
        raise ValueError("generated_orders must remain false")
    if getattr(model, "order_intents_generated", True):
        raise ValueError("order_intents_generated must remain false")
    if getattr(model, "orders_simulated", True):
        raise ValueError("orders_simulated must remain false")
    if getattr(model, "fills_simulated", True):
        raise ValueError("fills_simulated must remain false")
    if getattr(model, "pnl_calculated", True):
        raise ValueError("pnl_calculated must remain false")
    if getattr(model, "portfolio_accounting", True):
        raise ValueError("portfolio_accounting must remain false")
    if getattr(model, "broker_contacted", True):
        raise ValueError("broker_contacted must remain false")
    if getattr(model, "order_routing_enabled", True):
        raise ValueError("order_routing_enabled must remain false")
    if getattr(model, "no_order_guarantee", False) is not True:
        raise ValueError("no_order_guarantee must remain true")
    return model


def _validate_commodity_universe_flags(model: T) -> T:
    if getattr(model, "commodity_proxy_universe", False) is not True:
        raise ValueError("commodity_proxy_universe must remain true")
    if getattr(model, "futures_contracts_enabled", True):
        raise ValueError("futures_contracts_enabled must remain false")
    if getattr(model, "direct_futures_data_enabled", True):
        raise ValueError("direct_futures_data_enabled must remain false")
    if getattr(model, "broker_contacted", True):
        raise ValueError("broker_contacted must remain false")
    if getattr(model, "signal_evaluation_enabled", True):
        raise ValueError("signal_evaluation_enabled must remain false")
    if getattr(model, "generated_signals", True):
        raise ValueError("generated_signals must remain false")
    if getattr(model, "signal_count", 1) != 0:
        raise ValueError("signal_count must remain 0")
    if getattr(model, "generated_orders", True):
        raise ValueError("generated_orders must remain false")
    if getattr(model, "order_intents_generated", True):
        raise ValueError("order_intents_generated must remain false")
    if getattr(model, "orders_simulated", True):
        raise ValueError("orders_simulated must remain false")
    if getattr(model, "fills_simulated", True):
        raise ValueError("fills_simulated must remain false")
    if getattr(model, "pnl_calculated", True):
        raise ValueError("pnl_calculated must remain false")
    if getattr(model, "portfolio_accounting", True):
        raise ValueError("portfolio_accounting must remain false")
    if getattr(model, "order_routing_enabled", True):
        raise ValueError("order_routing_enabled must remain false")
    if getattr(model, "no_order_guarantee", False) is not True:
        raise ValueError("no_order_guarantee must remain true")
    return model


def _validate_data_quality_gate_flags(model: T) -> T:
    if getattr(model, "broker_contacted", True):
        raise ValueError("broker_contacted must remain false")
    if getattr(model, "signal_evaluation_enabled", True):
        raise ValueError("signal_evaluation_enabled must remain false")
    if getattr(model, "generated_signals", True):
        raise ValueError("generated_signals must remain false")
    if getattr(model, "signal_count", 1) != 0:
        raise ValueError("signal_count must remain 0")
    if getattr(model, "generated_orders", True):
        raise ValueError("generated_orders must remain false")
    if getattr(model, "order_intents_generated", True):
        raise ValueError("order_intents_generated must remain false")
    if getattr(model, "orders_simulated", True):
        raise ValueError("orders_simulated must remain false")
    if getattr(model, "fills_simulated", True):
        raise ValueError("fills_simulated must remain false")
    if getattr(model, "pnl_calculated", True):
        raise ValueError("pnl_calculated must remain false")
    if getattr(model, "portfolio_accounting", True):
        raise ValueError("portfolio_accounting must remain false")
    if getattr(model, "futures_contracts_enabled", True):
        raise ValueError("futures_contracts_enabled must remain false")
    if getattr(model, "direct_futures_data_enabled", True):
        raise ValueError("direct_futures_data_enabled must remain false")
    if getattr(model, "order_routing_enabled", True):
        raise ValueError("order_routing_enabled must remain false")
    if getattr(model, "no_order_guarantee", False) is not True:
        raise ValueError("no_order_guarantee must remain true")
    return model


_ANALYTICAL_ACTION_WORDS = frozenset(
    {
        "buy",
        "sell",
        "hold",
        "long",
        "short",
        "enter",
        "exit",
        "order",
        "position",
        "allocation",
        "rebalance",
    }
)


def _validate_no_analytical_action_vocabulary(value: str) -> str:
    tokens = {
        "".join(character for character in token if character.isalpha()).lower()
        for token in value.replace("_", " ").replace("-", " ").split()
    }
    forbidden = sorted(token for token in tokens if token in _ANALYTICAL_ACTION_WORDS)
    if forbidden:
        raise ValueError(
            "analytical observation text contains forbidden action vocabulary: "
            + ", ".join(forbidden)
        )
    return value


def _validate_analytical_signal_safety_flags(model: T) -> T:
    if getattr(model, "signal_evaluation_enabled", True) is not True:
        raise ValueError("signal_evaluation_enabled must remain true")
    if getattr(model, "generated_signals", True):
        raise ValueError("generated_signals must remain false")
    if getattr(model, "signal_count", 1) != 0:
        raise ValueError("signal_count must remain 0")
    if getattr(model, "generated_orders", True):
        raise ValueError("generated_orders must remain false")
    if getattr(model, "order_intents_generated", True):
        raise ValueError("order_intents_generated must remain false")
    if getattr(model, "orders_simulated", True):
        raise ValueError("orders_simulated must remain false")
    if getattr(model, "fills_simulated", True):
        raise ValueError("fills_simulated must remain false")
    if getattr(model, "pnl_calculated", True):
        raise ValueError("pnl_calculated must remain false")
    if getattr(model, "portfolio_accounting", True):
        raise ValueError("portfolio_accounting must remain false")
    if getattr(model, "broker_contacted", True):
        raise ValueError("broker_contacted must remain false")
    if getattr(model, "order_routing_enabled", True):
        raise ValueError("order_routing_enabled must remain false")
    if getattr(model, "no_order_guarantee", False) is not True:
        raise ValueError("no_order_guarantee must remain true")
    return model


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

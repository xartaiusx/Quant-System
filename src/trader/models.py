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

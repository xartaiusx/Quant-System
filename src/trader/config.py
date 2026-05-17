"""Fail-closed configuration loading for the trading system."""

from __future__ import annotations

import os
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class ConfigError(ValueError):
    """Raised when runtime configuration is missing, invalid, or unsafe."""


class TradingMode(StrEnum):
    """Supported initial trading modes."""

    PAPER = "paper"
    DRY_RUN = "dry_run"
    BACKTEST = "backtest"


class BrokerKind(StrEnum):
    """Supported IBKR desktop API hosts."""

    TWS = "tws"
    IB_GATEWAY = "ib_gateway"
    AUTO = "auto"


LIVE_PORTS = {7496, 4001}
PAPER_PORTS = {7497, 4002}
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
ACCOUNT_ID_KEYS = {"account_id", "ibkr_account_id"}
SENSITIVE_KEYS = {"token", "secret", "key", "password"}


class TraderConfig(BaseModel):
    """Runtime settings with conservative defaults."""

    model_config = ConfigDict(frozen=True)

    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    ibkr_client_id: int = 11
    ibkr_account_id: str | None = None
    broker_kind: BrokerKind = BrokerKind.AUTO
    ibkr_connect_timeout_seconds: float = 10
    ibkr_request_timeout_seconds: float = 10

    trading_mode: TradingMode = TradingMode.PAPER
    allow_paper_orders: bool = False
    allow_live_orders: bool = False

    max_trade_notional: Decimal = Decimal("50")
    max_open_positions: int = 3
    max_daily_loss: Decimal = Decimal("25")
    max_position_pct_equity: Decimal = Decimal("2")

    universe: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"])

    @field_validator("ibkr_host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in LOCAL_HOSTS:
            raise ValueError("IBKR_HOST must be localhost in this initial safe version")
        return normalized

    @field_validator("ibkr_port")
    @classmethod
    def reject_live_ports(cls, value: int) -> int:
        if value in LIVE_PORTS:
            raise ValueError("live IBKR ports 7496 and 4001 are documented only and disabled")
        if value <= 0:
            raise ValueError("IBKR_PORT must be positive")
        return value

    @field_validator("ibkr_client_id")
    @classmethod
    def validate_client_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("IBKR_CLIENT_ID must be positive")
        return value

    @field_validator("ibkr_connect_timeout_seconds", "ibkr_request_timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        if value <= 0 or value > 120:
            raise ValueError("IBKR timeouts must be greater than 0 and no more than 120 seconds")
        return value

    @field_validator("trading_mode", mode="before")
    @classmethod
    def validate_trading_mode(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "live":
                raise ValueError("live trading mode is disabled in this initial version")
            return normalized
        return value

    @field_validator("allow_paper_orders", "allow_live_orders", mode="before")
    @classmethod
    def parse_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1"}:
                return True
            if normalized in {"false", "0"}:
                return False
        raise ValueError("boolean settings must be true or false")

    @field_validator("max_trade_notional", "max_daily_loss", "max_position_pct_equity")
    @classmethod
    def validate_positive_decimal(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("risk limits must be positive")
        return value

    @field_validator("max_open_positions")
    @classmethod
    def validate_open_positions(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("MAX_OPEN_POSITIONS must be positive")
        return value

    @field_validator("universe", mode="before")
    @classmethod
    def parse_universe(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            raw_symbols = value.split(",")
        elif isinstance(value, list):
            raw_symbols = value
        else:
            raise ValueError("UNIVERSE must be a comma-separated string or list")

        symbols: list[str] = []
        for raw_symbol in raw_symbols:
            symbol = str(raw_symbol).strip().upper()
            if not symbol:
                continue
            if not symbol.replace(".", "").replace("-", "").isalnum():
                raise ValueError(f"invalid symbol in UNIVERSE: {symbol}")
            symbols.append(symbol)

        if not symbols:
            raise ValueError("UNIVERSE must contain at least one symbol")
        return symbols

    @model_validator(mode="after")
    def reject_live_order_flag(self) -> TraderConfig:
        if self.allow_live_orders:
            raise ValueError("ALLOW_LIVE_ORDERS=true is rejected in this initial version")
        return self

    @property
    def dry_run_default(self) -> bool:
        """All commands default to dry-run behavior unless a later phase changes this."""

        return True

    @property
    def inferred_broker_kind(self) -> str:
        """Return configured or port-inferred broker kind for diagnostics."""

        if self.broker_kind != BrokerKind.AUTO:
            return self.broker_kind.value
        if self.ibkr_port in {7497, 7496}:
            return BrokerKind.TWS.value
        if self.ibkr_port in {4002, 4001}:
            return BrokerKind.IB_GATEWAY.value
        return BrokerKind.AUTO.value

    def safe_summary(self) -> dict[str, Any]:
        """Return config suitable for logs and reports."""

        return {
            "ibkr_host": self.ibkr_host,
            "ibkr_port": self.ibkr_port,
            "ibkr_client_id": self.ibkr_client_id,
            "ibkr_account_id": mask_account_id(self.ibkr_account_id),
            "broker_kind": self.broker_kind.value,
            "broker_kind_inferred": self.inferred_broker_kind,
            "ibkr_connect_timeout_seconds": self.ibkr_connect_timeout_seconds,
            "ibkr_request_timeout_seconds": self.ibkr_request_timeout_seconds,
            "trading_mode": self.trading_mode.value,
            "allow_paper_orders": self.allow_paper_orders,
            "allow_live_orders": self.allow_live_orders,
            "max_trade_notional": str(self.max_trade_notional),
            "max_open_positions": self.max_open_positions,
            "max_daily_loss": str(self.max_daily_loss),
            "max_position_pct_equity": str(self.max_position_pct_equity),
            "universe": list(self.universe),
            "dry_run_default": self.dry_run_default,
        }


ENV_TO_FIELD = {
    "IBKR_HOST": "ibkr_host",
    "IBKR_PORT": "ibkr_port",
    "IBKR_CLIENT_ID": "ibkr_client_id",
    "IBKR_ACCOUNT_ID": "ibkr_account_id",
    "BROKER_KIND": "broker_kind",
    "IBKR_CONNECT_TIMEOUT_SECONDS": "ibkr_connect_timeout_seconds",
    "IBKR_REQUEST_TIMEOUT_SECONDS": "ibkr_request_timeout_seconds",
    "TRADING_MODE": "trading_mode",
    "ALLOW_PAPER_ORDERS": "allow_paper_orders",
    "ALLOW_LIVE_ORDERS": "allow_live_orders",
    "MAX_TRADE_NOTIONAL": "max_trade_notional",
    "MAX_OPEN_POSITIONS": "max_open_positions",
    "MAX_DAILY_LOSS": "max_daily_loss",
    "MAX_POSITION_PCT_EQUITY": "max_position_pct_equity",
    "UNIVERSE": "universe",
}


def load_config(
    env: Mapping[str, str] | None = None,
    *,
    dotenv_path: str | Path | None = None,
    load_dotenv_file: bool = True,
) -> TraderConfig:
    """Load settings from environment and optional `.env`.

    Passing `env` makes tests deterministic by bypassing process environment reads.
    """

    source: Mapping[str, str]
    if env is None:
        if load_dotenv_file:
            load_dotenv(dotenv_path=dotenv_path, override=False)
        source = os.environ
    else:
        source = env

    raw_config: dict[str, Any] = {
        field_name: source[env_name]
        for env_name, field_name in ENV_TO_FIELD.items()
        if env_name in source and source[env_name] != ""
    }

    try:
        return TraderConfig.model_validate(raw_config)
    except ValidationError as exc:
        raise ConfigError(f"invalid trading configuration: {exc}") from exc


def mask_account_id(value: str | None) -> str | None:
    """Mask account identifiers while retaining enough shape for diagnostics."""

    if not value:
        return None
    normalized = value.strip()
    if len(normalized) <= 4:
        return "*" * len(normalized)
    if len(normalized) <= 6:
        return f"{normalized[:2]}****{normalized[-2:]}"
    return f"{normalized[:4]}****{normalized[-2:]}"


def mask_sensitive_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a recursively masked copy of a mapping."""

    masked: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if lowered in ACCOUNT_ID_KEYS:
            masked[key] = mask_account_id(str(value)) if value else None
        elif any(token in lowered for token in SENSITIVE_KEYS):
            masked[key] = "***" if value else None
        elif isinstance(value, Mapping):
            masked[key] = mask_sensitive_mapping(value)
        elif isinstance(value, list):
            masked[key] = [
                mask_sensitive_mapping(item) if isinstance(item, Mapping) else item
                for item in value
            ]
        else:
            masked[key] = value
    return masked

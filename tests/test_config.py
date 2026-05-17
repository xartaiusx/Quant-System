from __future__ import annotations

import pytest

from trader.config import ConfigError, TradingMode, load_config, mask_account_id


def test_config_defaults_are_safe() -> None:
    config = load_config(env={}, load_dotenv_file=False)

    assert config.ibkr_host == "127.0.0.1"
    assert config.ibkr_port == 7497
    assert config.trading_mode == TradingMode.PAPER
    assert config.allow_paper_orders is False
    assert config.allow_live_orders is False
    assert config.dry_run_default is True


def test_live_trading_rejected() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"TRADING_MODE": "live"}, load_dotenv_file=False)

    with pytest.raises(ConfigError):
        load_config(env={"ALLOW_LIVE_ORDERS": "true"}, load_dotenv_file=False)

    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "7496"}, load_dotenv_file=False)

    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "4001"}, load_dotenv_file=False)


def test_paper_ports_are_allowed() -> None:
    tws_config = load_config(env={"IBKR_PORT": "7497"}, load_dotenv_file=False)
    gateway_config = load_config(env={"IBKR_PORT": "4002"}, load_dotenv_file=False)

    assert tws_config.ibkr_port == 7497
    assert tws_config.inferred_broker_kind == "tws"
    assert gateway_config.ibkr_port == 4002
    assert gateway_config.inferred_broker_kind == "ib_gateway"


def test_account_ids_are_masked() -> None:
    assert mask_account_id("DUXXYYZZ99") == "DUXX****99"
    assert mask_account_id("ABC") == "***"


def test_invalid_risk_limits_fail_closed() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"MAX_TRADE_NOTIONAL": "0"}, load_dotenv_file=False)

    with pytest.raises(ConfigError):
        load_config(env={"MAX_OPEN_POSITIONS": "-1"}, load_dotenv_file=False)


def test_universe_parsing() -> None:
    config = load_config(env={"UNIVERSE": "spy, qqq,aapl"}, load_dotenv_file=False)

    assert config.universe == ["SPY", "QQQ", "AAPL"]

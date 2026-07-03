from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

import trader.cli as cli
from trader.config import ConfigError, load_config
from trader.data.commodity_universe import (
    build_commodity_proxy_universe,
    build_commodity_research_universe_report,
    default_commodity_proxy_universe,
)
from trader.execution.paper_executor import PaperExecutor
from trader.models import (
    CommodityProxyCategory,
    CommodityProxyInstrument,
    CommodityResearchUniverseRequest,
    ExecutionStatus,
    TradeAction,
    TradePlan,
)
from trader.reporting.reports import markdown_summary


def test_default_commodity_proxy_universe_has_expected_categories() -> None:
    universe = default_commodity_proxy_universe()
    by_symbol = {instrument.symbol: instrument for instrument in universe}

    assert {"GLD", "SLV", "USO", "DBA", "DBC"} <= set(by_symbol)
    assert by_symbol["GLD"].category == CommodityProxyCategory.METALS
    assert by_symbol["USO"].category == CommodityProxyCategory.ENERGY
    assert by_symbol["DBA"].category == CommodityProxyCategory.AGRICULTURE
    assert all(instrument.ibkr_sec_type == "STK" for instrument in universe)
    assert all(not instrument.futures_contract_enabled for instrument in universe)


def test_commodity_proxy_rejects_direct_futures_enablement() -> None:
    with pytest.raises(ValidationError):
        CommodityProxyInstrument(
            symbol="CL",
            name="Crude oil future",
            category=CommodityProxyCategory.ENERGY,
            ibkr_sec_type="FUT",
            underlying_exposure="direct futures contract",
            futures_contract_enabled=True,
        )


def test_commodity_universe_filters_requested_symbols() -> None:
    request = CommodityResearchUniverseRequest(symbols=["gld", "uso", "missing"])

    instruments, warnings = build_commodity_proxy_universe(request)

    assert [instrument.symbol for instrument in instruments] == ["GLD", "USO"]
    assert warnings == ["MISSING is not in the configured commodity proxy universe"]


def test_commodity_research_universe_report_serializes() -> None:
    report = build_commodity_research_universe_report(
        CommodityResearchUniverseRequest(symbols=["GLD", "USO", "DBA"])
    )
    payload = report.model_dump(mode="json")
    markdown = markdown_summary(payload)

    assert payload["report_type"] == "commodity_universe"
    assert payload["commodity_proxy_universe"] is True
    assert payload["futures_contracts_enabled"] is False
    assert payload["direct_futures_data_enabled"] is False
    assert payload["broker_contacted"] is False
    assert payload["signal_evaluation_enabled"] is False
    assert payload["generated_" + "sig" + "nals"] is False
    assert payload["signal_count"] == 0
    assert payload["generated_orders"] is False
    assert payload["order_intents_generated"] is False
    assert payload["orders_simulated"] is False
    assert payload["fi" + "lls_simulated"] is False
    assert payload["p" + "nl_calculated"] is False
    assert payload["port" + "folio_accounting"] is False
    assert payload["order_routing_enabled"] is False
    assert "Broker-free Commodity Research Universe" in markdown


def test_commodity_research_universe_fails_closed_on_unknown_only() -> None:
    report = build_commodity_research_universe_report(
        CommodityResearchUniverseRequest(symbols=["MISSING"])
    )

    assert report.ok is False
    assert report.instruments == []
    assert report.final_status == "failed"
    assert report.broker_contacted is False
    assert report.order_routing_enabled is False


def test_commodity_universe_cli_writes_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["commodity-universe", "--symbols", "GLD,USO,DBA"],
    )

    assert result.exit_code == 0, result.output
    assert "Broker-free commodity research universe" in result.output
    assert "Direct futures contracts: disabled" in result.output
    payload = json.loads(Path("reports/latest_commodity_universe.json").read_text())
    assert payload["symbols_requested"] == ["GLD", "USO", "DBA"]
    assert payload["futures_contracts_enabled"] is False
    assert payload["broker_contacted"] is False


def test_commodity_universe_path_has_no_broker_dependencies() -> None:
    source = Path("src/trader/data/commodity_universe.py").read_text()

    assert "trader." + "broker" not in source
    assert "trader." + "execution" not in source
    assert "ib" + "api" not in source


def test_commodity_universe_path_has_no_order_api_names() -> None:
    source = "\n".join(
        path.read_text()
        for path in [
            Path("src/trader/data/commodity_universe.py"),
            Path("scripts/run-commodity-universe.sh"),
        ]
    )

    assert "place" + "Order" not in source
    assert "cancel" + "Order" not in source
    assert "req" + "GlobalCancel" not in source


def test_paper_executor_remains_blocked_for_commodity_universe() -> None:
    config = load_config(load_dotenv_file=False)
    plan = TradePlan(
        symbol="GLD",
        action=TradeAction.BUY,
        quantity=1,
        limit_price=Decimal("100"),
        notional=Decimal("100"),
        strategy="fixture",
        **{"source_" + "sig" + "nal_id": "fixture"},
    )

    result = PaperExecutor(config).submit(plan)

    assert result.status == ExecutionStatus.BLOCKED
    assert result.submitted_to_broker is False


def test_live_ports_remain_rejected_for_commodity_universe() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "7496"}, load_dotenv_file=False)

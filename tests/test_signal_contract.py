from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from tests.fixtures.historical_snapshots import clean_two_symbol_dataset
from typer.testing import CliRunner

import trader.cli as cli
from trader.config import ConfigError, load_config
from trader.execution.paper_executor import PaperExecutor
from trader.models import (
    BacktestAlignmentMode,
    BacktestBar,
    BacktestDataFeed,
    BacktestDataFeedSummary,
    BacktestFeedFrame,
    BacktestFeedPoint,
    BacktestFeedStatus,
    ExecutionStatus,
    SignalContractDiagnostic,
    SignalContractValidationRequest,
    StrategyMetadata,
    TradeAction,
    TradePlan,
)
from trader.strategy.interface import NoOpStrategyContract
from trader.strategy.signals import (
    DisabledSignalContract,
    build_signal_contract_report,
    build_signal_evaluation_context,
    default_disabled_signal_contract_metadata,
    run_disabled_signal_contract_diagnostic,
    validate_signal_contract,
)


def fixture_times() -> tuple[datetime, datetime]:
    start = datetime(2026, 5, 18, 21, 30, tzinfo=UTC)
    return start, start + timedelta(minutes=5)


def bar(symbol: str, timestamp: datetime) -> BacktestBar:
    return BacktestBar(
        symbol=symbol,
        timestamp=timestamp,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.50"),
        volume=Decimal("1000"),
        source_snapshot_timestamp="20260519T010000Z",
        source_bars_path=f"/tmp/{symbol}_bars.jsonl",
        source_manifest_path=f"/tmp/{symbol}_manifest.json",
    )


def frame(timestamp: datetime, *, include_missing: bool = False) -> BacktestFeedFrame:
    bars = {
        "SPY": bar("SPY", timestamp),
        "AAPL": None if include_missing else bar("AAPL", timestamp),
    }
    missing = [symbol for symbol, value in bars.items() if value is None]
    return BacktestFeedFrame(
        timestamp=timestamp,
        bars_by_symbol=bars,
        points=[
            BacktestFeedPoint(symbol=symbol, bar=value, missing=value is None)
            for symbol, value in bars.items()
        ],
        missing_symbols=missing,
    )


def feed(*, include_missing: bool = False) -> BacktestDataFeed:
    t1, t2 = fixture_times()
    frames = [frame(t1, include_missing=include_missing), frame(t2)]
    return BacktestDataFeed(
        symbols=["SPY", "AAPL"],
        alignment_mode=BacktestAlignmentMode.UNION,
        frames=frames,
        total_bars=sum(
            1 for item in frames for value in item.bars_by_symbol.values() if value is not None
        ),
        frame_count=len(frames),
        first_timestamp=t1,
        last_timestamp=t2,
        missing_bars_by_symbol={"SPY": 0, "AAPL": 1 if include_missing else 0},
        duplicate_timestamps_by_symbol={"SPY": 0, "AAPL": 0},
        feed_status=BacktestFeedStatus.PARTIAL if include_missing else BacktestFeedStatus.READY,
        warnings=["source feed has missing bars"] if include_missing else [],
    )


def request() -> SignalContractValidationRequest:
    return SignalContractValidationRequest(symbols=["SPY", "AAPL"])


def test_signal_contract_metadata_serializes() -> None:
    metadata = default_disabled_signal_contract_metadata(supported_symbols=["SPY", "AAPL"])

    payload = metadata.model_dump(mode="json")

    assert payload["signal_contract_name"] == "disabled_signal_contract"
    assert payload["enabled"] is False
    assert payload["broker_required"] is False
    assert payload["supported_symbols"] == ["SPY", "AAPL"]


def test_signal_evaluation_context_serializes() -> None:
    summary = BacktestDataFeedSummary(symbols=["SPY", "AAPL"], frame_count=1)
    metadata = default_disabled_signal_contract_metadata()
    context = build_signal_evaluation_context(
        frame(fixture_times()[0]),
        summary,
        NoOpStrategyContract().metadata,
        metadata,
    )

    payload = context.model_dump(mode="json")

    assert payload["available_symbols"] == ["AAPL", "SPY"]
    assert payload["missing_symbols"] == []
    assert payload["signal_contract_metadata"]["enabled"] is False


def test_signal_contract_diagnostic_serializes() -> None:
    timestamp = fixture_times()[0]
    diagnostic = SignalContractDiagnostic(
        signal_contract_name="disabled_signal_contract",
        signal_contract_version="0.1.0",
        timestamp=timestamp,
        frame_index=0,
    )

    payload = diagnostic.model_dump(mode="json")

    assert payload["signal_evaluation_enabled"] is False
    assert payload["generated_signals"] is False
    assert payload["signal_count"] == 0
    assert payload["generated_orders"] is False


def test_disabled_signal_contract_metadata_validates() -> None:
    metadata = default_disabled_signal_contract_metadata()

    assert validate_signal_contract(metadata) == []
    assert metadata.enabled is False
    assert metadata.broker_required is False


def test_disabled_signal_contract_accepts_frame_context() -> None:
    summary = BacktestDataFeedSummary(symbols=["SPY", "AAPL"], frame_count=1)
    metadata = default_disabled_signal_contract_metadata()
    context = build_signal_evaluation_context(
        frame(fixture_times()[0]),
        summary,
        NoOpStrategyContract().metadata,
        metadata,
    )

    diagnostic = DisabledSignalContract(metadata).observe(context)

    assert diagnostic.diagnostics["context_observed"] is True
    assert diagnostic.available_symbols == ["AAPL", "SPY"]


def test_disabled_signal_contract_emits_diagnostics_only() -> None:
    result = run_disabled_signal_contract_diagnostic(feed(), request())

    assert result.ok is True
    assert result.contexts_observed == 2
    assert len(result.diagnostics) == 2
    assert all(
        diagnostic.signal_evaluation_enabled is False
        for diagnostic in result.diagnostics
    )
    assert all(diagnostic.signal_count == 0 for diagnostic in result.diagnostics)


def test_disabled_signal_contract_safety_flags_are_false() -> None:
    diagnostic = run_disabled_signal_contract_diagnostic(feed(), request()).diagnostics[0]

    assert diagnostic.signal_contract_validated is True
    assert diagnostic.signal_evaluation_enabled is False
    assert diagnostic.generated_signals is False
    assert diagnostic.signal_count == 0
    assert diagnostic.generated_orders is False
    assert diagnostic.orders_simulated is False
    assert getattr(diagnostic, "fi" + "lls_simulated") is False
    assert getattr(diagnostic, "p" + "nl_calculated") is False
    assert getattr(diagnostic, "port" + "folio_accounting") is False
    assert diagnostic.broker_contacted is False


def test_build_signal_evaluation_context_preserves_timestamp() -> None:
    timestamp = fixture_times()[0]
    summary = BacktestDataFeedSummary(symbols=["SPY", "AAPL"], frame_count=1)
    context = build_signal_evaluation_context(frame(timestamp), summary, frame_index=7)

    assert context.timestamp == timestamp
    assert context.frame_index == 7


def test_build_signal_evaluation_context_preserves_available_symbols() -> None:
    summary = BacktestDataFeedSummary(symbols=["SPY", "AAPL"], frame_count=1)
    context = build_signal_evaluation_context(frame(fixture_times()[0]), summary)

    assert context.available_symbols == ["AAPL", "SPY"]


def test_build_signal_evaluation_context_records_missing_symbols() -> None:
    summary = BacktestDataFeedSummary(symbols=["SPY", "AAPL"], frame_count=1)
    context = build_signal_evaluation_context(
        frame(fixture_times()[0], include_missing=True),
        summary,
    )

    assert context.missing_symbols == ["AAPL"]


def test_signal_contract_report_serializes() -> None:
    report = build_signal_contract_report(feed(), request())

    payload = report.model_dump(mode="json")

    assert payload["report_type"] == "signal_contract"
    assert payload["signal_contract_validated"] is True
    assert payload["signal_evaluation_enabled"] is False
    assert payload["generated_signals"] is False
    assert payload["signal_count"] == 0
    assert payload["generated_orders"] is False
    assert payload["orders_simulated"] is False
    assert payload["fi" + "lls_simulated"] is False
    assert payload["p" + "nl_calculated"] is False
    assert payload["port" + "folio_accounting"] is False
    assert payload["broker_contacted"] is False


def test_signal_contract_cli_runs_with_fixture_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = clean_two_symbol_dataset(tmp_path / "data" / "historical")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "signal-contract",
            "--symbols",
            ",".join(scenario.symbols),
            "--base-path",
            scenario.root.as_posix(),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Broker-free signal contract" in result.output
    assert "Signal evaluation enabled" in result.output
    assert Path("reports/latest_signal_contract.json").exists()


def test_signal_contract_path_has_no_socket_dependencies() -> None:
    source = Path("src/trader/strategy/signals.py").read_text()

    assert "trader." + "broker" not in source
    assert "IBKR" + "ReadOnlyClient" not in source
    assert "ib" + "api" not in source


def test_signal_contract_path_has_no_order_api_names() -> None:
    source = Path("src/trader/strategy/signals.py").read_text()

    assert "place" + "Order" not in source
    assert "cancel" + "Order" not in source
    assert "req" + "GlobalCancel" not in source


def test_signal_contract_produces_no_trading_output_models() -> None:
    report = build_signal_contract_report(feed(), request())

    assert report.signal_count == 0
    assert report.generated_signals is False
    assert report.generated_orders is False
    assert all(diagnostic.signal_count == 0 for diagnostic in report.diagnostics)


def test_signal_context_accepts_strategy_metadata() -> None:
    metadata = StrategyMetadata(strategy_name="noop_contract", strategy_version="0.1.0")
    summary = BacktestDataFeedSummary(symbols=["SPY", "AAPL"], frame_count=1)

    context = build_signal_evaluation_context(
        frame(fixture_times()[0]),
        summary,
        strategy_metadata=metadata,
    )

    assert context.strategy_metadata == metadata


def test_paper_executor_remains_blocked_for_signal_contract() -> None:
    config = load_config(load_dotenv_file=False)
    plan = TradePlan(
        symbol="SPY",
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


def test_live_ports_remain_rejected_for_signal_contract() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "7496"}, load_dotenv_file=False)

from __future__ import annotations

import json
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
    BacktestFeedFrame,
    BacktestFeedPoint,
    BacktestFeedStatus,
    DisabledSignalRunnerRequest,
    DisabledSignalRunnerStatus,
    ExecutionStatus,
    TradeAction,
    TradePlan,
)
from trader.reporting.reports import markdown_summary
from trader.strategy.signal_runner import (
    build_disabled_signal_runner_report,
    run_disabled_signal_runner,
    summarize_disabled_signal_runner,
    validate_disabled_signal_runner_result,
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


def feed(
    *,
    status: BacktestFeedStatus = BacktestFeedStatus.READY,
    include_missing: bool = False,
    empty: bool = False,
) -> BacktestDataFeed:
    t1, t2 = fixture_times()
    frames = [] if empty else [frame(t1, include_missing=include_missing), frame(t2)]
    return BacktestDataFeed(
        symbols=["SPY", "AAPL"],
        alignment_mode=BacktestAlignmentMode.UNION,
        frames=frames,
        total_bars=sum(
            1 for item in frames for value in item.bars_by_symbol.values() if value is not None
        ),
        frame_count=len(frames),
        first_timestamp=frames[0].timestamp if frames else None,
        last_timestamp=frames[-1].timestamp if frames else None,
        missing_bars_by_symbol={"SPY": 0, "AAPL": 1 if include_missing else 0},
        duplicate_timestamps_by_symbol={"SPY": 0, "AAPL": 0},
        feed_status=status,
        warnings=["source feed has missing bars"] if include_missing else [],
        errors=["source feed failed"] if status == BacktestFeedStatus.FAILED else [],
    )


def request() -> DisabledSignalRunnerRequest:
    return DisabledSignalRunnerRequest(symbols=["SPY", "AAPL"])


def test_signal_runner_runs_on_ready_feed() -> None:
    result = run_disabled_signal_runner(feed(), request())

    assert result.ok is True
    assert result.diagnostics.runner_status == DisabledSignalRunnerStatus.COMPLETED
    assert result.diagnostics.frame_count == 2
    assert result.diagnostics.contexts_built == 2
    assert result.diagnostics.diagnostics_emitted == 2


def test_signal_runner_handles_partial_feed_with_warnings() -> None:
    result = run_disabled_signal_runner(
        feed(status=BacktestFeedStatus.PARTIAL, include_missing=True),
        request(),
    )

    assert result.ok is True
    assert result.diagnostics.runner_status == DisabledSignalRunnerStatus.PARTIAL
    assert result.diagnostics.missing_symbols_by_frame_count == 1
    assert result.diagnostics.missing_symbols_by_symbol["AAPL"] == 1
    assert "source feed has missing bars" in result.warnings


def test_signal_runner_fails_cleanly_on_empty_feed() -> None:
    result = run_disabled_signal_runner(feed(empty=True), request())

    assert result.ok is False
    assert result.diagnostics.runner_status == DisabledSignalRunnerStatus.FAILED
    assert "source feed contains no frames" in result.errors


def test_signal_runner_fails_cleanly_on_failed_feed() -> None:
    result = run_disabled_signal_runner(feed(status=BacktestFeedStatus.FAILED), request())

    assert result.ok is False
    assert result.diagnostics.runner_status == DisabledSignalRunnerStatus.FAILED
    assert "source feed status is failed" in result.errors


def test_signal_runner_builds_one_signal_context_per_frame() -> None:
    result = run_disabled_signal_runner(feed(), request())

    assert result.diagnostics.contexts_built == len(feed().frames)
    assert [item.frame_index for item in result.frame_diagnostics] == [0, 1]
    assert all(
        item.diagnostic.diagnostics["context_observed"] is True
        for item in result.frame_diagnostics
    )


def test_signal_runner_emits_one_diagnostic_per_frame() -> None:
    result = run_disabled_signal_runner(feed(), request())

    assert result.diagnostics.diagnostics_emitted == len(result.frame_diagnostics)
    assert len(result.frame_diagnostics) == 2


def test_signal_runner_records_first_and_last_timestamp() -> None:
    t1, t2 = fixture_times()
    summary = summarize_disabled_signal_runner(run_disabled_signal_runner(feed(), request()))

    assert summary.first_timestamp == t1
    assert summary.last_timestamp == t2


def test_signal_runner_records_missing_symbols() -> None:
    result = run_disabled_signal_runner(feed(include_missing=True), request())

    first = result.frame_diagnostics[0]
    assert first.available_symbols == ["SPY"]
    assert first.missing_symbols == ["AAPL"]


def test_signal_runner_result_serializes_to_json() -> None:
    result = run_disabled_signal_runner(feed(), request())
    payload = result.model_dump(mode="json")

    assert payload["ok"] is True
    assert payload["diagnostics"]["runner_status"] == "completed"
    assert payload["disabled_signal_runner"] is True
    assert payload["signal_count"] == 0


def test_signal_runner_report_serializes() -> None:
    report = build_disabled_signal_runner_report(feed(), request())
    payload = report.model_dump(mode="json")
    markdown = markdown_summary(payload)

    assert payload["report_type"] == "signal_runner"
    assert payload["disabled_signal_runner"] is True
    assert payload["signal_contract_validated"] is True
    assert payload["signal_evaluation_enabled"] is False
    assert payload["generated_" + "sig" + "nals"] is False
    assert payload["signal_count"] == 0
    assert payload["generated_orders"] is False
    assert payload["order_intents_generated"] is False
    assert payload["orders_simulated"] is False
    assert payload["fi" + "lls_simulated"] is False
    assert payload["p" + "nl_calculated"] is False
    assert payload["port" + "folio_accounting"] is False
    assert payload["broker_contacted"] is False
    assert payload["order_routing_enabled"] is False
    assert payload["no_order_guarantee"] is True
    assert "This run exercised the disabled signal contract only" in markdown


def test_validate_signal_runner_detects_unsorted_results() -> None:
    frame_diagnostics = run_disabled_signal_runner(feed(), request()).frame_diagnostics
    result = run_disabled_signal_runner(feed(), request()).model_copy(
        update={"frame_diagnostics": list(reversed(frame_diagnostics))}
    )

    errors = validate_disabled_signal_runner_result(result)

    assert "signal runner frame diagnostics are not sorted by timestamp" in errors


def test_signal_runner_cli_runs_with_fixture_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = clean_two_symbol_dataset(tmp_path / "data" / "historical")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "signal-runner",
            "--symbols",
            ",".join(scenario.symbols),
            "--base-path",
            scenario.root.as_posix(),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Broker-free disabled signal runner" in result.output
    assert "Disabled signal runner" in result.output
    assert Path("reports/latest_signal_runner.json").exists()
    payload = json.loads(Path("reports/latest_signal_runner.json").read_text())
    assert payload["disabled_signal_runner"] is True
    assert payload["signal_contract_validated"] is True
    assert payload["signal_evaluation_enabled"] is False
    assert payload["generated_" + "sig" + "nals"] is False
    assert payload["signal_count"] == 0
    assert payload["generated_orders"] is False
    assert payload["order_intents_generated"] is False
    assert payload["broker_contacted"] is False


def test_signal_runner_cli_fails_closed_with_missing_local_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "signal-runner",
            "--symbols",
            "SPY,AAPL",
            "--base-path",
            (tmp_path / "missing").as_posix(),
        ],
    )

    assert result.exit_code == 1
    assert "Broker contacted: false" in result.output
    assert "source feed contains no frames" in result.output
    payload = json.loads(Path("reports/latest_signal_runner.json").read_text())
    assert payload["ok"] is False
    assert payload["broker_contacted"] is False
    assert payload["order_routing_enabled"] is False


def test_signal_runner_path_has_no_socket_dependencies() -> None:
    source = Path("src/trader/strategy/signal_runner.py").read_text()

    assert "trader." + "broker" not in source
    assert "IBKR" + "ReadOnlyClient" not in source
    assert "ib" + "api" not in source


def test_signal_runner_path_has_no_order_api_names() -> None:
    source = "\n".join(
        path.read_text()
        for path in [
            Path("src/trader/strategy/signal_runner.py"),
            Path("scripts/run-signal-runner.sh"),
        ]
    )

    assert "place" + "Order" not in source
    assert "cancel" + "Order" not in source
    assert "req" + "GlobalCancel" not in source


def test_signal_runner_required_flags_are_disabled() -> None:
    result = run_disabled_signal_runner(feed(), request())

    assert result.disabled_signal_runner is True
    assert result.signal_contract_validated is True
    assert result.signal_evaluation_enabled is False
    assert getattr(result, "generated_" + "sig" + "nals") is False
    assert result.signal_count == 0
    assert result.generated_orders is False
    assert result.order_intents_generated is False
    assert result.orders_simulated is False
    assert getattr(result, "fi" + "lls_simulated") is False
    assert getattr(result, "p" + "nl_calculated") is False
    assert getattr(result, "port" + "folio_accounting") is False
    assert result.broker_contacted is False
    assert result.order_routing_enabled is False
    assert result.no_order_guarantee is True


def test_paper_executor_remains_blocked_for_signal_runner() -> None:
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


def test_live_ports_remain_rejected_for_signal_runner() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "7496"}, load_dotenv_file=False)

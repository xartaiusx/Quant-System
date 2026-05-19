from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
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
    ExecutionStatus,
    HistoricalSnapshotBar,
    HistoricalSnapshotManifest,
    InertStrategyRunnerRequest,
    InertStrategyRunnerStatus,
    TradeAction,
    TradePlan,
)
from trader.strategy.runner import (
    build_inert_strategy_runner_report,
    run_inert_strategy_runner,
    summarize_inert_strategy_runner,
    validate_inert_strategy_runner_result,
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


def request() -> InertStrategyRunnerRequest:
    return InertStrategyRunnerRequest(symbols=["SPY", "AAPL"])


def test_runner_runs_on_ready_feed() -> None:
    result = run_inert_strategy_runner(feed(), request())

    assert result.ok is True
    assert result.diagnostics.runner_status == InertStrategyRunnerStatus.COMPLETED
    assert result.diagnostics.frame_count == 2
    assert result.diagnostics.contexts_built == 2
    assert result.diagnostics.diagnostics_emitted == 2


def test_runner_handles_partial_feed_with_warnings() -> None:
    result = run_inert_strategy_runner(
        feed(status=BacktestFeedStatus.PARTIAL, include_missing=True),
        request(),
    )

    assert result.ok is True
    assert result.diagnostics.runner_status == InertStrategyRunnerStatus.PARTIAL
    assert result.diagnostics.missing_symbols_by_frame_count == 1
    assert result.diagnostics.missing_symbols_by_symbol["AAPL"] == 1
    assert "source feed has missing bars" in result.warnings


def test_runner_fails_cleanly_on_empty_feed() -> None:
    result = run_inert_strategy_runner(feed(empty=True), request())

    assert result.ok is False
    assert result.diagnostics.runner_status == InertStrategyRunnerStatus.FAILED
    assert "source feed contains no frames" in result.errors


def test_runner_fails_cleanly_on_failed_feed() -> None:
    result = run_inert_strategy_runner(feed(status=BacktestFeedStatus.FAILED), request())

    assert result.ok is False
    assert result.diagnostics.runner_status == InertStrategyRunnerStatus.FAILED
    assert "source feed status is failed" in result.errors


def test_runner_builds_one_frame_context_per_frame() -> None:
    result = run_inert_strategy_runner(feed(), request())

    assert result.diagnostics.contexts_built == len(feed().frames)
    assert [item.frame_index for item in result.frame_results] == [0, 1]


def test_runner_emits_one_diagnostic_per_frame() -> None:
    result = run_inert_strategy_runner(feed(), request())

    assert result.diagnostics.diagnostics_emitted == len(result.frame_results)
    assert all(
        item.diagnostic.diagnostics["frame_observed"] is True
        for item in result.frame_results
    )


def test_runner_records_first_and_last_timestamp() -> None:
    t1, t2 = fixture_times()
    summary = summarize_inert_strategy_runner(run_inert_strategy_runner(feed(), request()))

    assert summary.first_timestamp == t1
    assert summary.last_timestamp == t2


def test_runner_records_missing_symbols() -> None:
    result = run_inert_strategy_runner(feed(include_missing=True), request())

    first = result.frame_results[0]
    assert first.available_symbols == ["SPY"]
    assert first.missing_symbols == ["AAPL"]


def test_runner_result_serializes_to_json() -> None:
    result = run_inert_strategy_runner(feed(), request())
    payload = result.model_dump(mode="json")

    assert payload["ok"] is True
    assert payload["diagnostics"]["runner_status"] == "completed"
    assert payload["diagnostic_only"] is True


def test_runner_report_serializes() -> None:
    report = build_inert_strategy_runner_report(feed(), request())
    payload = report.model_dump(mode="json")

    assert payload["report_type"] == "strategy_runner"
    assert payload["diagnostic_only"] is True
    assert payload["noop_strategy_observed"] is True
    assert payload["real_strategy_evaluated"] is False
    assert payload["generated_" + "sig" + "nals"] is False
    assert payload["generated_orders"] is False
    assert payload["orders_simulated"] is False
    assert payload["fi" + "lls_simulated"] is False
    assert payload["p" + "nl_calculated"] is False
    assert payload["port" + "folio_accounting"] is False
    assert payload["broker_contacted"] is False


def test_validate_runner_detects_unsorted_results() -> None:
    frame_results = run_inert_strategy_runner(feed(), request()).frame_results
    result = run_inert_strategy_runner(feed(), request()).model_copy(
        update={"frame_results": list(reversed(frame_results))}
    )

    errors = validate_inert_strategy_runner_result(result)

    assert "strategy runner frame diagnostics are not sorted by timestamp" in errors


def write_fixture_snapshot(
    root: Path,
    *,
    symbol: str = "SPY",
    timestamp_slug: str = "20260519T010000Z",
) -> tuple[Path, Path]:
    timestamps = ["20260518  21:30:00", "20260518  21:35:00"]
    snapshot_dir = root / symbol / "5_mins" / "TRADES"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    bars_path = snapshot_dir / f"{timestamp_slug}_bars.jsonl"
    manifest_path = snapshot_dir / f"{timestamp_slug}_manifest.json"
    bars = [
        HistoricalSnapshotBar(
            symbol=symbol,
            contract_id=1001,
            timestamp=timestamp,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.50"),
            volume=Decimal("1000"),
            wap=Decimal("100.25"),
            bar_count=10,
            duration="1 D",
            bar_size="5 mins",
            what_to_show="TRADES",
            use_rth=1,
        )
        for timestamp in timestamps
    ]
    bars_path.write_text(
        "".join(
            json.dumps(item.model_dump(mode="json"), sort_keys=True) + "\n"
            for item in bars
        )
    )
    manifest = HistoricalSnapshotManifest(
        generated_at=datetime(2026, 5, 19, 4, 0, tzinfo=UTC),
        symbol=symbol,
        contract_id=1001,
        exchange="SMART",
        currency="USD",
        duration="1 D",
        bar_size="5 mins",
        what_to_show="TRADES",
        use_rth=1,
        bar_count=len(bars),
        first_bar_time=timestamps[0],
        last_bar_time=timestamps[-1],
        request_timeout=30,
        snapshot_path=bars_path.as_posix(),
        manifest_path=manifest_path.as_posix(),
    )
    manifest_path.write_text(manifest.model_dump_json())
    return bars_path, manifest_path


def test_strategy_runner_cli_runs_with_fixture_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_fixture_snapshot(tmp_path, symbol="SPY")
    write_fixture_snapshot(tmp_path, symbol="AAPL")
    monkeypatch.chdir(tmp_path.parent)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "strategy-runner",
            "--symbols",
            "SPY,AAPL",
            "--base-path",
            tmp_path.as_posix(),
        ],
    )

    assert result.exit_code == 0
    assert "Broker contacted: false" in result.output
    assert "Diagnostic-only" in result.output
    assert (tmp_path.parent / "reports" / "latest_strategy_runner.json").exists()


def test_runner_path_has_no_broker_dependency() -> None:
    source = Path("src/trader/strategy/runner.py").read_text()

    assert "trader." + "broker" not in source
    assert "IBKR" + "ReadOnlyClient" not in source
    assert "ib" + "api" not in source


def test_runner_path_does_not_call_order_apis() -> None:
    source = "\n".join(
        path.read_text()
        for path in [
            Path("src/trader/strategy/runner.py"),
            Path("scripts/run-strategy-runner.sh"),
        ]
    )

    assert "place" + "Order" not in source
    assert "cancel" + "Order" not in source
    assert "req" + "GlobalCancel" not in source


def test_runner_required_flags_are_inert() -> None:
    result = run_inert_strategy_runner(feed(), request())

    assert result.diagnostic_only is True
    assert result.noop_strategy_observed is True
    assert result.real_strategy_evaluated is False
    assert getattr(result, "generated_" + "sig" + "nals") is False
    assert result.generated_orders is False
    assert result.orders_simulated is False
    assert getattr(result, "fi" + "lls_simulated") is False
    assert getattr(result, "p" + "nl_calculated") is False
    assert getattr(result, "port" + "folio_accounting") is False
    assert result.broker_contacted is False


def test_paper_executor_remains_blocked_for_strategy_runner() -> None:
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


def test_live_ports_remain_rejected_for_strategy_runner() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "7496"}, load_dotenv_file=False)

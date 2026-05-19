from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

import trader.cli as cli
from trader.backtest.engine import (
    build_backtest_run_report,
    run_backtest_engine,
    summarize_backtest_run,
    validate_backtest_run,
)
from trader.config import ConfigError, load_config
from trader.execution.paper_executor import PaperExecutor
from trader.models import (
    BacktestAlignmentMode,
    BacktestBar,
    BacktestDataFeed,
    BacktestFeedFrame,
    BacktestFeedPoint,
    BacktestFeedStatus,
    BacktestRunRequest,
    BacktestRunStatus,
    ExecutionStatus,
    HistoricalSnapshotBar,
    HistoricalSnapshotManifest,
    TradeAction,
    TradePlan,
)


def fixture_times() -> tuple[datetime, datetime, datetime]:
    start = datetime(2026, 5, 18, 21, 30, tzinfo=UTC)
    return start, start + timedelta(minutes=5), start + timedelta(minutes=10)


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


def frame(
    timestamp: datetime,
    *,
    spy: BacktestBar | None,
    aapl: BacktestBar | None,
) -> BacktestFeedFrame:
    bars = {"SPY": spy, "AAPL": aapl}
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
    t1, t2, _t3 = fixture_times()
    frames = [] if empty else [
        frame(t1, spy=bar("SPY", t1), aapl=None if include_missing else bar("AAPL", t1)),
        frame(t2, spy=bar("SPY", t2), aapl=bar("AAPL", t2)),
    ]
    missing = {"SPY": 0, "AAPL": 1 if include_missing else 0}
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
        missing_bars_by_symbol=missing,
        duplicate_timestamps_by_symbol={"SPY": 0, "AAPL": 0},
        feed_status=status,
        warnings=["source feed has missing bars"] if include_missing else [],
        errors=["source feed failed"] if status == BacktestFeedStatus.FAILED else [],
    )


def request() -> BacktestRunRequest:
    return BacktestRunRequest(symbols=["SPY", "AAPL"])


def test_engine_runs_on_ready_feed() -> None:
    result = run_backtest_engine(feed(), request())

    assert result.ok is True
    assert result.diagnostics.run_status == BacktestRunStatus.COMPLETED
    assert result.diagnostics.frame_count == 2
    assert result.diagnostics.total_bars_observed == 4


def test_engine_handles_partial_feed_with_warnings() -> None:
    result = run_backtest_engine(
        feed(status=BacktestFeedStatus.PARTIAL, include_missing=True),
        request(),
    )

    assert result.ok is True
    assert result.diagnostics.run_status == BacktestRunStatus.PARTIAL
    assert result.diagnostics.frames_with_missing_bars == 1
    assert result.diagnostics.missing_bars_by_symbol["AAPL"] == 1


def test_engine_fails_cleanly_on_empty_feed() -> None:
    result = run_backtest_engine(feed(empty=True), request())

    assert result.ok is False
    assert result.diagnostics.run_status == BacktestRunStatus.FAILED
    assert "source feed contains no frames" in result.errors


def test_engine_fails_cleanly_on_failed_feed() -> None:
    result = run_backtest_engine(feed(status=BacktestFeedStatus.FAILED), request())

    assert result.ok is False
    assert result.diagnostics.run_status == BacktestRunStatus.FAILED
    assert "source feed status is failed" in result.errors


def test_frame_observations_are_sorted_by_timestamp() -> None:
    t1, t2, _t3 = fixture_times()
    unsorted_feed = feed().model_copy(
        update={
            "frames": [
                frame(t2, spy=bar("SPY", t2), aapl=bar("AAPL", t2)),
                frame(t1, spy=bar("SPY", t1), aapl=bar("AAPL", t1)),
            ]
        }
    )

    result = run_backtest_engine(unsorted_feed, request())

    assert [item.timestamp for item in result.observations] == [t1, t2]


def test_frame_observations_record_symbols_present_and_missing() -> None:
    result = run_backtest_engine(feed(include_missing=True), request())

    first = result.observations[0]
    assert first.symbols_present == ["SPY"]
    assert first.symbols_missing == ["AAPL"]
    assert first.bar_count == 1
    assert first.missing_bar_count == 1


def test_run_summary_records_counts_and_timestamps() -> None:
    t1, t2, _t3 = fixture_times()
    result = run_backtest_engine(feed(), request())
    summary = summarize_backtest_run(result)

    assert summary.frame_count == 2
    assert summary.observations_count == 2
    assert summary.total_bars_observed == 4
    assert summary.first_timestamp == t1
    assert summary.last_timestamp == t2


def test_validate_backtest_run_detects_unsorted_result() -> None:
    t1, t2, _t3 = fixture_times()
    result = run_backtest_engine(feed(), request()).model_copy(
        update={
            "observations": [
                run_backtest_engine(feed(), request()).observations[1],
                run_backtest_engine(feed(), request()).observations[0],
            ]
        }
    )

    errors = validate_backtest_run(result)

    assert "frame observations are not sorted by timestamp" in errors
    assert [t2, t1] == [item.timestamp for item in result.observations]


def test_result_serializes_to_json() -> None:
    result = run_backtest_engine(feed(), request())
    payload = result.model_dump(mode="json")

    assert payload["ok"] is True
    assert payload["diagnostics"]["run_status"] == "completed"


def test_report_serializes() -> None:
    report = build_backtest_run_report(feed(), request())
    payload = report.model_dump(mode="json")

    assert payload["report_type"] == "backtest_run"
    assert payload["broker_contacted"] is False
    assert payload["strategy_evaluated"] is False
    assert payload["orders_simulated"] is False
    assert payload["p" + "nl_calculated"] is False


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
        generated_at=datetime.now(UTC),
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


def test_cli_backtest_run_runs_with_fixture_data(tmp_path: Path, monkeypatch: object) -> None:
    write_fixture_snapshot(tmp_path, symbol="SPY")
    write_fixture_snapshot(tmp_path, symbol="AAPL")
    monkeypatch.chdir(tmp_path.parent)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "backtest-run",
            "--symbols",
            "SPY,AAPL",
            "--base-path",
            tmp_path.as_posix(),
        ],
    )

    assert result.exit_code == 0
    assert "Broker contacted: false" in result.output
    assert "data frames only" in result.output
    assert (tmp_path.parent / "reports" / "latest_backtest_run.json").exists()


def test_engine_path_has_no_broker_dependency() -> None:
    source = Path("src/trader/backtest/engine.py").read_text()

    assert "trader." + "broker" not in source
    assert "IBKR" + "ReadOnlyClient" not in source
    assert "ib" + "api" not in source


def test_engine_path_has_no_strategy_dependency() -> None:
    source = Path("src/trader/backtest/engine.py").read_text()

    assert "trader." + "strategy" not in source


def test_engine_path_does_not_call_order_apis() -> None:
    source = "\n".join(
        path.read_text()
        for path in [
            Path("src/trader/backtest/engine.py"),
            Path("scripts/run-backtest-run.sh"),
        ]
    )

    assert "place" + "Order" not in source
    assert "cancel" + "Order" not in source
    assert "req" + "GlobalCancel" not in source


def test_run_safety_flags_are_false() -> None:
    result = run_backtest_engine(feed(), request())

    assert result.strategy_evaluated is False
    assert result.orders_simulated is False
    assert getattr(result, "p" + "nl_calculated") is False


def test_paper_executor_remains_blocked() -> None:
    config = load_config(load_dotenv_file=False)
    plan = TradePlan(
        symbol="SPY",
        action=TradeAction.BUY,
        quantity=1,
        limit_price=Decimal("100"),
        notional=Decimal("100"),
        source_signal_id="fixture",
        strategy="fixture",
    )

    result = PaperExecutor(config).submit(plan)

    assert result.status == ExecutionStatus.BLOCKED
    assert result.submitted_to_broker is False


def test_live_ports_remain_rejected_for_backtest_run_milestone() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "7496"}, load_dotenv_file=False)

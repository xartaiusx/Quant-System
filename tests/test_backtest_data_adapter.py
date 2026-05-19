from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

import trader.cli as cli
from trader.backtest.data_adapter import (
    build_backtest_feed,
    build_backtest_feed_report,
    iter_feed_frames,
    summarize_backtest_feed,
)
from trader.config import ConfigError, load_config
from trader.execution.paper_executor import PaperExecutor
from trader.models import (
    BacktestAlignmentMode,
    BacktestDataAdapterRequest,
    BacktestFeedStatus,
    ExecutionStatus,
    HistoricalDatasetSummary,
    HistoricalLoadedBar,
    HistoricalLoadedDataset,
    HistoricalLoaderReport,
    HistoricalLoadResult,
    HistoricalLoadStatus,
    HistoricalSnapshotBar,
    HistoricalSnapshotLoadRequest,
    HistoricalSnapshotManifest,
    TradeAction,
    TradePlan,
)


def loaded_bar(
    symbol: str,
    timestamp: datetime,
    *,
    open_: Decimal = Decimal("100"),
    close: Decimal = Decimal("100.50"),
) -> HistoricalLoadedBar:
    return HistoricalLoadedBar(
        symbol=symbol,
        contract_id=1001,
        timestamp=timestamp,
        raw_timestamp=timestamp.strftime("%Y%m%d  %H:%M:%S"),
        open=open_,
        high=max(open_, close) + Decimal("1"),
        low=min(open_, close) - Decimal("1"),
        close=close,
        volume=Decimal("1000"),
        wap=Decimal("100.25"),
        bar_count=10,
        typical_price=(
            max(open_, close) + Decimal("1") + min(open_, close) - Decimal("1") + close
        )
        / Decimal("3"),
        dollar_volume=close * Decimal("1000"),
        interval_seconds=300,
        duration="1 D",
        bar_size="5 mins",
        what_to_show="TRADES",
        use_rth=1,
    )


def loaded_dataset(
    symbol: str,
    timestamps: list[datetime],
    *,
    status: HistoricalLoadStatus = HistoricalLoadStatus.LOADED,
) -> HistoricalLoadedDataset:
    bars = [loaded_bar(symbol, timestamp) for timestamp in timestamps]
    summary = HistoricalDatasetSummary(
        symbol=symbol,
        bar_size="5 mins",
        what_to_show="TRADES",
        snapshot_timestamp="20260519T010000Z",
        bars_path=f"/tmp/{symbol}_bars.jsonl",
        manifest_path=f"/tmp/{symbol}_manifest.json",
        bars_count=len(bars),
        first_timestamp=timestamps[0] if timestamps else None,
        last_timestamp=timestamps[-1] if timestamps else None,
        load_status=status,
        warnings=["fixture partial"] if status == HistoricalLoadStatus.PARTIAL else [],
        errors=["fixture failed"] if status == HistoricalLoadStatus.FAILED else [],
    )
    return HistoricalLoadedDataset(
        symbol=symbol,
        bar_size="5 mins",
        what_to_show="TRADES",
        snapshot_timestamp="20260519T010000Z",
        bars_path=f"/tmp/{symbol}_bars.jsonl",
        manifest_path=f"/tmp/{symbol}_manifest.json",
        bars=bars,
        summary=summary,
    )


def fixture_times() -> tuple[datetime, datetime, datetime]:
    start = datetime(2026, 5, 18, 21, 30, tzinfo=UTC)
    return start, start + timedelta(minutes=5), start + timedelta(minutes=10)


def test_builds_feed_from_one_dataset() -> None:
    t1, t2, _t3 = fixture_times()
    feed = build_backtest_feed([loaded_dataset("SPY", [t1, t2])])

    assert feed.feed_status == BacktestFeedStatus.READY
    assert feed.symbols == ["SPY"]
    assert feed.frame_count == 2
    assert feed.total_bars == 2
    assert feed.frames[0].bars_by_symbol["SPY"] is not None


def test_builds_feed_from_multiple_datasets() -> None:
    t1, t2, _t3 = fixture_times()
    feed = build_backtest_feed(
        [
            loaded_dataset("SPY", [t1, t2]),
            loaded_dataset("AAPL", [t1, t2]),
        ]
    )

    assert feed.symbols == ["SPY", "AAPL"]
    assert feed.frame_count == 2
    assert feed.total_bars == 4


def test_union_alignment_includes_all_timestamps() -> None:
    t1, t2, t3 = fixture_times()
    feed = build_backtest_feed(
        [
            loaded_dataset("SPY", [t1, t2]),
            loaded_dataset("AAPL", [t2, t3]),
        ],
        alignment_mode=BacktestAlignmentMode.UNION,
    )

    assert [frame.timestamp for frame in feed.frames] == [t1, t2, t3]
    assert feed.missing_bars_by_symbol == {"SPY": 1, "AAPL": 1}
    assert feed.feed_status == BacktestFeedStatus.PARTIAL


def test_intersection_alignment_includes_shared_timestamps_only() -> None:
    t1, t2, t3 = fixture_times()
    feed = build_backtest_feed(
        [
            loaded_dataset("SPY", [t1, t2]),
            loaded_dataset("AAPL", [t2, t3]),
        ],
        alignment_mode=BacktestAlignmentMode.INTERSECTION,
    )

    assert [frame.timestamp for frame in feed.frames] == [t2]
    assert feed.missing_bars_by_symbol == {"SPY": 0, "AAPL": 0}
    assert feed.feed_status == BacktestFeedStatus.READY


def test_missing_bars_counted_by_symbol() -> None:
    t1, t2, _t3 = fixture_times()
    feed = build_backtest_feed(
        [
            loaded_dataset("SPY", [t1, t2]),
            loaded_dataset("AAPL", [t2]),
        ]
    )

    assert feed.missing_bars_by_symbol["AAPL"] == 1
    assert feed.frames[0].bars_by_symbol["AAPL"] is None
    assert feed.frames[0].points[1].missing is True


def test_frames_sorted_and_bars_keyed_by_symbol() -> None:
    t1, t2, _t3 = fixture_times()
    feed = build_backtest_feed([loaded_dataset("SPY", [t2, t1])])

    assert [frame.timestamp for frame in feed.frames] == [t1, t2]
    assert set(feed.frames[0].bars_by_symbol) == {"SPY"}


def test_empty_dataset_fails_cleanly() -> None:
    feed = build_backtest_feed([loaded_dataset("SPY", [])])

    assert feed.feed_status == BacktestFeedStatus.FAILED
    assert "SPY source dataset contains no bars" in feed.errors


def test_empty_input_fails_cleanly() -> None:
    feed = build_backtest_feed([])

    assert feed.feed_status == BacktestFeedStatus.FAILED
    assert feed.errors == ["no historical datasets supplied", "feed contains no frames"]


def test_partial_dataset_produces_partial_status() -> None:
    t1, _t2, _t3 = fixture_times()
    feed = build_backtest_feed(
        [loaded_dataset("SPY", [t1], status=HistoricalLoadStatus.PARTIAL)]
    )

    assert feed.feed_status == BacktestFeedStatus.PARTIAL
    assert "SPY source dataset status is partial" in feed.warnings


def test_duplicate_timestamps_recorded() -> None:
    t1, _t2, _t3 = fixture_times()
    feed = build_backtest_feed([loaded_dataset("SPY", [t1, t1])])

    assert feed.duplicate_timestamps_by_symbol["SPY"] == 1
    assert feed.frame_count == 1
    assert feed.feed_status == BacktestFeedStatus.PARTIAL


def test_feed_summary_serializes() -> None:
    t1, _t2, _t3 = fixture_times()
    feed = build_backtest_feed([loaded_dataset("SPY", [t1])])
    summary = summarize_backtest_feed(feed)

    assert summary.model_dump(mode="json")["feed_status"] == "ready"


def test_report_serializes() -> None:
    t1, _t2, _t3 = fixture_times()
    loader_request = HistoricalSnapshotLoadRequest(symbols=["SPY"])
    dataset = loaded_dataset("SPY", [t1])
    loader_report = HistoricalLoaderReport(
        command="history-load",
        ok=True,
        request=loader_request,
        base_data_path="data/historical",
        symbols_requested=["SPY"],
        summaries=[dataset.summary],
        results=[
            HistoricalLoadResult(
                symbol="SPY",
                request=loader_request,
                dataset=dataset,
                summary=dataset.summary,
                load_status=HistoricalLoadStatus.LOADED,
            )
        ],
    )
    report = build_backtest_feed_report(
        loader_report,
        BacktestDataAdapterRequest(symbols=["SPY"]),
    )

    payload = report.model_dump(mode="json")
    assert payload["report_type"] == "backtest_feed"
    assert payload["broker_contacted"] is False
    assert "No strategy evaluation" in payload["no_strategy_execution_statement"]


def test_iter_feed_frames_is_deterministic() -> None:
    t1, t2, _t3 = fixture_times()
    feed = build_backtest_feed([loaded_dataset("SPY", [t2, t1])])

    assert [frame.timestamp for frame in iter_feed_frames(feed)] == [t1, t2]


def write_fixture_snapshot(
    root: Path,
    *,
    symbol: str = "SPY",
    timestamp_slug: str = "20260519T010000Z",
    timestamps: list[str] | None = None,
) -> tuple[Path, Path]:
    timestamps = timestamps or ["20260518  21:30:00", "20260518  21:35:00"]
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
            json.dumps(bar.model_dump(mode="json"), sort_keys=True) + "\n"
            for bar in bars
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


def test_cli_backtest_feed_runs_with_fixture_data(tmp_path: Path, monkeypatch: object) -> None:
    write_fixture_snapshot(tmp_path, symbol="SPY")
    write_fixture_snapshot(tmp_path, symbol="AAPL")
    monkeypatch.chdir(tmp_path.parent)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "backtest-feed",
            "--symbols",
            "SPY,AAPL",
            "--base-path",
            tmp_path.as_posix(),
        ],
    )

    assert result.exit_code == 0
    assert "Broker contacted: false" in result.output
    assert "No strategy evaluation" in result.output
    assert (tmp_path.parent / "reports" / "latest_backtest_feed.json").exists()


def test_backtest_adapter_path_has_no_broker_dependency() -> None:
    source = Path("src/trader/backtest/data_adapter.py").read_text()

    assert "trader." + "broker" not in source
    assert "IBKR" + "ReadOnlyClient" not in source
    assert "ib" + "api" not in source


def test_backtest_adapter_path_does_not_call_order_apis() -> None:
    source = "\n".join(
        path.read_text()
        for path in [
            Path("src/trader/backtest/data_adapter.py"),
            Path("scripts/run-backtest-feed.sh"),
        ]
    )

    assert "place" + "Order" not in source
    assert "cancel" + "Order" not in source
    assert "req" + "GlobalCancel" not in source


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


def test_live_ports_remain_rejected_for_backtest_feed_milestone() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "7496"}, load_dotenv_file=False)

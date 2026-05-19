from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

import trader.cli as cli
from trader.config import ConfigError, load_config
from trader.data.historical_loader import (
    build_history_index_report,
    discover_snapshots,
    load_historical_snapshots,
    load_snapshot_entry,
    select_snapshot_entries,
)
from trader.execution.paper_executor import PaperExecutor
from trader.models import (
    ExecutionStatus,
    HistoricalLoadStatus,
    HistoricalSnapshotBar,
    HistoricalSnapshotIndexEntry,
    HistoricalSnapshotLoadRequest,
    HistoricalSnapshotManifest,
    TradeAction,
    TradePlan,
)


def fixture_bar(
    *,
    symbol: str = "SPY",
    timestamp: str = "20260518  21:30:00",
    open_: Decimal = Decimal("100"),
    high: Decimal = Decimal("101"),
    low: Decimal = Decimal("99"),
    close: Decimal = Decimal("100.50"),
    volume: Decimal | None = Decimal("1000"),
    bar_size: str = "5 mins",
    what_to_show: str = "TRADES",
) -> HistoricalSnapshotBar:
    return HistoricalSnapshotBar(
        symbol=symbol,
        contract_id=1001,
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        wap=Decimal("100.25"),
        bar_count=10,
        duration="1 D",
        bar_size=bar_size,
        what_to_show=what_to_show,
        use_rth=1,
    )


def write_fixture_snapshot(
    root: Path,
    *,
    symbol: str = "SPY",
    timestamp_slug: str = "20260519T010000Z",
    bars: list[HistoricalSnapshotBar] | None = None,
    bar_size: str = "5 mins",
    what_to_show: str = "TRADES",
    manifest_bar_count: int | None = None,
) -> tuple[Path, Path]:
    bars = bars or [
        fixture_bar(symbol=symbol, timestamp="20260518  21:30:00"),
        fixture_bar(symbol=symbol, timestamp="20260518  21:35:00"),
    ]
    snapshot_dir = root / symbol / "5_mins" / what_to_show
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    bars_path = snapshot_dir / f"{timestamp_slug}_bars.jsonl"
    manifest_path = snapshot_dir / f"{timestamp_slug}_manifest.json"
    bars_path.write_text(
        "".join(
            json.dumps(bar.model_dump(mode="json"), sort_keys=True) + "\n"
            for bar in bars
        )
    )
    manifest = HistoricalSnapshotManifest(
        generated_at=datetime.now(UTC),
        symbol=symbol,
        contract_id=1001,
        exchange="SMART",
        currency="USD",
        duration="1 D",
        bar_size=bar_size,
        what_to_show=what_to_show,
        use_rth=1,
        bar_count=manifest_bar_count if manifest_bar_count is not None else len(bars),
        first_bar_time=bars[0].timestamp if bars else None,
        last_bar_time=bars[-1].timestamp if bars else None,
        request_timeout=30,
        snapshot_path=bars_path.as_posix(),
        manifest_path=manifest_path.as_posix(),
    )
    manifest_path.write_text(manifest.model_dump_json())
    return bars_path, manifest_path


def load_request(root: Path, *symbols: str, strict: bool = False) -> HistoricalSnapshotLoadRequest:
    return HistoricalSnapshotLoadRequest(
        symbols=list(symbols) or ["SPY"],
        bar_size="5 mins",
        what_to_show="TRADES",
        strict=strict,
        base_data_path=root.as_posix(),
    )


def test_discovers_snapshots(tmp_path: Path) -> None:
    write_fixture_snapshot(tmp_path, symbol="SPY")

    entries = discover_snapshots(base_dir=tmp_path)

    assert len(entries) == 1
    assert entries[0].symbol == "SPY"
    assert entries[0].snapshot_timestamp == "20260519T010000Z"


def test_handles_no_snapshots(tmp_path: Path) -> None:
    report = build_history_index_report(base_dir=tmp_path)

    assert report.ok is False
    assert report.errors == ["no historical snapshots found"]
    assert report.broker_contacted is False


def test_selects_latest_snapshot(tmp_path: Path) -> None:
    write_fixture_snapshot(tmp_path, symbol="SPY", timestamp_slug="20260519T010000Z")
    write_fixture_snapshot(tmp_path, symbol="SPY", timestamp_slug="20260519T020000Z")
    entries = discover_snapshots(base_dir=tmp_path)

    selected = select_snapshot_entries(entries, load_request(tmp_path, "SPY"))

    assert [entry.snapshot_timestamp for entry in selected] == ["20260519T020000Z"]


def test_filters_by_symbol_bar_size_and_what_to_show(tmp_path: Path) -> None:
    write_fixture_snapshot(tmp_path, symbol="SPY")
    write_fixture_snapshot(tmp_path, symbol="AAPL")

    entries = discover_snapshots(
        base_dir=tmp_path,
        symbols=["AAPL"],
        bar_size="5 mins",
        what_to_show="TRADES",
    )

    assert [entry.symbol for entry in entries] == ["AAPL"]


def test_loads_valid_jsonl_bars_and_manifest(tmp_path: Path) -> None:
    write_fixture_snapshot(tmp_path, symbol="SPY")

    report = load_historical_snapshots(load_request(tmp_path, "SPY"))

    assert report.ok is True
    assert report.results[0].load_status == HistoricalLoadStatus.LOADED
    assert report.summaries[0].bars_count == 2
    assert report.results[0].dataset is not None
    assert report.results[0].dataset.bars[0].typical_price == Decimal(
        "100.1666666666666666666666667"
    )


def test_detects_missing_manifest(tmp_path: Path) -> None:
    entry = HistoricalSnapshotIndexEntry(
        symbol="SPY",
        bar_size="5 mins",
        what_to_show="TRADES",
        snapshot_timestamp="20260519T010000Z",
        bars_path=(tmp_path / "missing_bars.jsonl").as_posix(),
        manifest_path=(tmp_path / "missing_manifest.json").as_posix(),
    )

    result = load_snapshot_entry(entry, request=load_request(tmp_path, "SPY"))

    assert result.load_status == HistoricalLoadStatus.FAILED
    assert result.issues[0].code == "missing_manifest"


def test_detects_missing_bars_file(tmp_path: Path) -> None:
    bars_path, manifest_path = write_fixture_snapshot(tmp_path, symbol="SPY")
    bars_path.unlink()
    entry = discover_snapshots(base_dir=tmp_path)[0].model_copy(
        update={"bars_path": bars_path.as_posix(), "manifest_path": manifest_path.as_posix()}
    )

    result = load_snapshot_entry(entry, request=load_request(tmp_path, "SPY"))

    assert result.load_status == HistoricalLoadStatus.FAILED
    assert result.issues[0].code == "missing_bars_file"


def test_detects_malformed_jsonl_line_non_strict_partial(tmp_path: Path) -> None:
    bars_path, _manifest_path = write_fixture_snapshot(tmp_path, symbol="SPY")
    with bars_path.open("a") as handle:
        handle.write("{bad json\n")

    report = load_historical_snapshots(load_request(tmp_path, "SPY"))

    assert report.results[0].load_status == HistoricalLoadStatus.PARTIAL
    assert report.summaries[0].malformed_line_count == 1


def test_strict_mode_fails_on_malformed_line(tmp_path: Path) -> None:
    bars_path, _manifest_path = write_fixture_snapshot(tmp_path, symbol="SPY")
    with bars_path.open("a") as handle:
        handle.write("{bad json\n")

    report = load_historical_snapshots(load_request(tmp_path, "SPY", strict=True))

    assert report.results[0].load_status == HistoricalLoadStatus.FAILED
    assert "malformed JSONL lines detected" in report.errors[0]


def test_detects_duplicate_timestamps(tmp_path: Path) -> None:
    bars = [
        fixture_bar(timestamp="20260518  21:30:00"),
        fixture_bar(timestamp="20260518  21:30:00"),
    ]
    write_fixture_snapshot(tmp_path, bars=bars)

    report = load_historical_snapshots(load_request(tmp_path, "SPY"))

    assert report.summaries[0].duplicate_timestamps_count == 1
    assert report.results[0].load_status == HistoricalLoadStatus.PARTIAL


def test_detects_timestamp_gaps(tmp_path: Path) -> None:
    bars = [
        fixture_bar(timestamp="20260518  21:30:00"),
        fixture_bar(timestamp="20260518  21:45:00"),
    ]
    write_fixture_snapshot(tmp_path, bars=bars)

    report = load_historical_snapshots(load_request(tmp_path, "SPY"))

    assert report.summaries[0].missing_gap_count == 1
    assert report.summaries[0].largest_gap_seconds == 900


def test_detects_invalid_ohlc(tmp_path: Path) -> None:
    bars = [fixture_bar(high=Decimal("99"), low=Decimal("98"), close=Decimal("100"))]
    write_fixture_snapshot(tmp_path, bars=bars)

    report = load_historical_snapshots(load_request(tmp_path, "SPY"))

    assert report.results[0].load_status == HistoricalLoadStatus.FAILED
    assert report.summaries[0].invalid_ohlc_count == 1


def test_detects_negative_volume(tmp_path: Path) -> None:
    bars = [fixture_bar(volume=Decimal("-1"))]
    write_fixture_snapshot(tmp_path, bars=bars)

    report = load_historical_snapshots(load_request(tmp_path, "SPY"))

    assert report.results[0].load_status == HistoricalLoadStatus.FAILED
    assert report.summaries[0].negative_volume_count == 1


def test_detects_bar_count_mismatch(tmp_path: Path) -> None:
    write_fixture_snapshot(tmp_path, manifest_bar_count=99)

    report = load_historical_snapshots(load_request(tmp_path, "SPY"))

    assert report.results[0].load_status == HistoricalLoadStatus.PARTIAL
    assert report.summaries[0].manifest_matches_bars is False


def test_produces_dataset_summary_and_serializes_report(tmp_path: Path) -> None:
    write_fixture_snapshot(tmp_path)

    report = load_historical_snapshots(load_request(tmp_path, "SPY"))
    payload = report.model_dump(mode="json")

    assert payload["report_type"] == "history_load"
    assert payload["summaries"][0]["load_status"] == "loaded"
    assert payload["broker_contacted"] is False


def test_cli_history_index_runs_with_fixture_data(tmp_path: Path, monkeypatch: object) -> None:
    write_fixture_snapshot(tmp_path)
    monkeypatch.chdir(tmp_path.parent)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["history-index", "--base-path", tmp_path.as_posix()],
    )

    assert result.exit_code == 0
    assert "Broker contacted: false" in result.output
    assert (tmp_path.parent / "reports" / "latest_history_index.json").exists()


def test_cli_history_load_runs_with_fixture_data(tmp_path: Path, monkeypatch: object) -> None:
    write_fixture_snapshot(tmp_path)
    monkeypatch.chdir(tmp_path.parent)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["history-load", "--symbols", "SPY", "--base-path", tmp_path.as_posix()],
    )

    assert result.exit_code == 0
    assert "Offline historical snapshot load" in result.output
    assert (tmp_path.parent / "reports" / "latest_history_load.json").exists()


def test_cli_history_inspect_runs_with_fixture_data(tmp_path: Path, monkeypatch: object) -> None:
    write_fixture_snapshot(tmp_path)
    monkeypatch.chdir(tmp_path.parent)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["history-inspect", "--symbol", "SPY", "--base-path", tmp_path.as_posix()],
    )

    assert result.exit_code == 0
    assert "Offline historical snapshot inspect" in result.output


def test_loader_path_has_no_broker_dependency() -> None:
    source = Path("src/trader/data/historical_loader.py").read_text()

    assert "trader." + "broker" not in source
    assert "IBKR" + "ReadOnlyClient" not in source
    assert "ib" + "api" not in source


def test_loader_path_does_not_call_order_apis() -> None:
    source = "\n".join(
        path.read_text()
        for path in [
            Path("src/trader/data/historical_loader.py"),
            Path("scripts/run-history-load.sh"),
        ]
    )

    assert "place" + "Order" not in source
    assert "cancel" + "Order" not in source
    assert "req" + "GlobalCancel" not in source


def test_live_ports_remain_rejected_for_loader_milestone() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "7496"}, load_dotenv_file=False)

    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "4001"}, load_dotenv_file=False)


def test_paper_executor_remains_blocked_for_loader_milestone() -> None:
    config = load_config(env={"ALLOW_PAPER_ORDERS": "true"}, load_dotenv_file=False)
    plan = TradePlan(
        symbol="SPY",
        action=TradeAction.BUY,
        quantity=1,
        limit_price=Decimal("10"),
        notional=Decimal("10"),
        source_signal_id="sig",
        strategy="unit",
    )

    result = PaperExecutor(config).submit(plan)

    assert result.status == ExecutionStatus.BLOCKED
    assert result.submitted_to_broker is False

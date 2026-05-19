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
    BacktestDataFeedSummary,
    BacktestFeedFrame,
    BacktestFeedPoint,
    BacktestFeedStatus,
    ExecutionStatus,
    HistoricalSnapshotBar,
    HistoricalSnapshotManifest,
    StrategyContractDiagnostic,
    StrategyContractValidationRequest,
    StrategyMetadata,
    StrategyParameterSpec,
    TradeAction,
    TradePlan,
)
from trader.strategy.interface import (
    NoOpStrategyContract,
    build_strategy_contract_report,
    build_strategy_frame_context,
    run_noop_strategy_contract_diagnostic,
    validate_strategy_contract,
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
    )


def request() -> StrategyContractValidationRequest:
    return StrategyContractValidationRequest(symbols=["SPY", "AAPL"])


def test_strategy_metadata_serializes() -> None:
    metadata = StrategyMetadata(
        strategy_name="noop_contract",
        strategy_version="0.1.0",
        parameters=[
            StrategyParameterSpec(
                name="window",
                parameter_type="integer",
                description="Example metadata only.",
                default_value=5,
            )
        ],
    )

    payload = metadata.model_dump(mode="json")

    assert payload["strategy_name"] == "noop_contract"
    assert payload["broker_required"] is False
    assert payload["parameters"][0]["name"] == "window"


def test_strategy_frame_context_serializes() -> None:
    summary = BacktestDataFeedSummary(symbols=["SPY", "AAPL"], frame_count=1)
    context = build_strategy_frame_context(frame(fixture_times()[0]), summary)

    payload = context.model_dump(mode="json")

    assert payload["available_symbols"] == ["AAPL", "SPY"]
    assert payload["missing_symbols"] == []


def test_strategy_contract_diagnostic_serializes() -> None:
    timestamp = fixture_times()[0]
    diagnostic = StrategyContractDiagnostic(
        strategy_name="noop_contract",
        strategy_version="0.1.0",
        timestamp=timestamp,
        frame_index=0,
    )

    payload = diagnostic.model_dump(mode="json")

    assert payload["evaluated"] is False
    assert payload["generated_signals"] is False
    assert payload["generated_orders"] is False


def test_noop_strategy_metadata_validates() -> None:
    contract = NoOpStrategyContract()

    assert validate_strategy_contract(contract.metadata) == []
    assert contract.metadata.broker_required is False


def test_noop_strategy_accepts_frame_context() -> None:
    summary = BacktestDataFeedSummary(symbols=["SPY", "AAPL"], frame_count=1)
    context = build_strategy_frame_context(frame(fixture_times()[0]), summary)

    diagnostic = NoOpStrategyContract().observe(context)

    assert diagnostic.diagnostics["frame_observed"] is True
    assert diagnostic.available_symbols == ["AAPL", "SPY"]


def test_noop_strategy_emits_diagnostics_only() -> None:
    result = run_noop_strategy_contract_diagnostic(feed(), request())

    assert result.ok is True
    assert result.contexts_observed == 2
    assert len(result.diagnostics) == 2
    assert all(diagnostic.evaluated is False for diagnostic in result.diagnostics)


def test_noop_strategy_safety_flags_are_false() -> None:
    diagnostic = run_noop_strategy_contract_diagnostic(feed(), request()).diagnostics[0]

    assert diagnostic.generated_signals is False
    assert diagnostic.generated_orders is False
    assert diagnostic.orders_simulated is False
    assert getattr(diagnostic, "p" + "nl_calculated") is False
    assert diagnostic.broker_contacted is False


def test_build_strategy_frame_context_preserves_timestamp() -> None:
    timestamp = fixture_times()[0]
    summary = BacktestDataFeedSummary(symbols=["SPY", "AAPL"], frame_count=1)
    context = build_strategy_frame_context(frame(timestamp), summary, frame_index=7)

    assert context.timestamp == timestamp
    assert context.frame_index == 7


def test_build_strategy_frame_context_preserves_available_symbols() -> None:
    summary = BacktestDataFeedSummary(symbols=["SPY", "AAPL"], frame_count=1)
    context = build_strategy_frame_context(frame(fixture_times()[0]), summary)

    assert context.available_symbols == ["AAPL", "SPY"]


def test_build_strategy_frame_context_records_missing_symbols() -> None:
    summary = BacktestDataFeedSummary(symbols=["SPY", "AAPL"], frame_count=1)
    context = build_strategy_frame_context(
        frame(fixture_times()[0], include_missing=True),
        summary,
    )

    assert context.missing_symbols == ["AAPL"]


def test_strategy_contract_report_serializes() -> None:
    report = build_strategy_contract_report(feed(), request())

    payload = report.model_dump(mode="json")

    assert payload["report_type"] == "strategy_contract"
    assert payload["evaluated"] is False
    assert payload["generated_signals"] is False
    assert payload["generated_orders"] is False
    assert payload["orders_simulated"] is False
    assert payload["p" + "nl_calculated"] is False
    assert payload["broker_contacted"] is False


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


def test_strategy_contract_cli_runs_with_fixture_data(
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
            "strategy-contract",
            "--symbols",
            "SPY,AAPL",
            "--base-path",
            tmp_path.as_posix(),
        ],
    )

    assert result.exit_code == 0
    assert "Broker contacted: false" in result.output
    assert "contract only" in result.output
    assert (tmp_path.parent / "reports" / "latest_strategy_contract.json").exists()


def test_strategy_interface_path_has_no_broker_dependency() -> None:
    source = Path("src/trader/strategy/interface.py").read_text()

    assert "trader." + "broker" not in source
    assert "IBKR" + "ReadOnlyClient" not in source
    assert "ib" + "api" not in source


def test_strategy_interface_path_does_not_call_order_apis() -> None:
    source = "\n".join(
        path.read_text()
        for path in [
            Path("src/trader/strategy/interface.py"),
            Path("scripts/run-strategy-contract.sh"),
        ]
    )

    assert "place" + "Order" not in source
    assert "cancel" + "Order" not in source
    assert "req" + "GlobalCancel" not in source


def test_paper_executor_remains_blocked_for_strategy_contract() -> None:
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


def test_live_ports_remain_rejected_for_strategy_contract() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "7496"}, load_dotenv_file=False)

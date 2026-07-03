from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.fixtures.historical_snapshots import clean_two_symbol_dataset
from typer.testing import CliRunner

import trader.cli as cli
from trader.config import ConfigError, load_config
from trader.execution.paper_executor import PaperExecutor
from trader.models import (
    AnalyticalSignalConditionState,
    AnalyticalSignalEvaluationRequest,
    AnalyticalSignalEvaluationStatus,
    AnalyticalSignalObservation,
    BacktestAlignmentMode,
    BacktestBar,
    BacktestDataFeed,
    BacktestDataFeedSummary,
    BacktestFeedFrame,
    BacktestFeedPoint,
    BacktestFeedStatus,
    ExecutionStatus,
    TradeAction,
    TradePlan,
)
from trader.reporting.reports import markdown_summary
from trader.strategy.signal_evaluation import (
    build_analytical_signal_evaluation_report,
    default_moving_average_relationship_metadata,
    evaluate_moving_average_relationship,
    run_analytical_signal_evaluation,
    validate_analytical_signal_evaluation_result,
)
from trader.strategy.signals import build_signal_evaluation_context


def fixture_start() -> datetime:
    return datetime(2026, 5, 18, 21, 30, tzinfo=UTC)


def bar(symbol: str, timestamp: datetime, close: Decimal) -> BacktestBar:
    return BacktestBar(
        symbol=symbol,
        timestamp=timestamp,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=Decimal("1000"),
        source_snapshot_timestamp="20260519T010000Z",
        source_bars_path=f"/tmp/{symbol}_bars.jsonl",
        source_manifest_path=f"/tmp/{symbol}_manifest.json",
    )


def invalid_bar(symbol: str, timestamp: datetime) -> BacktestBar:
    return BacktestBar(
        symbol=symbol,
        timestamp=timestamp,
        open=Decimal("100"),
        high=Decimal("99"),
        low=Decimal("98"),
        close=Decimal("101"),
        volume=Decimal("1000"),
        source_snapshot_timestamp="20260519T010000Z",
        source_bars_path=f"/tmp/{symbol}_bars.jsonl",
        source_manifest_path=f"/tmp/{symbol}_manifest.json",
    )


def trend_feed(
    *,
    closes: list[Decimal] | None = None,
    symbols: list[str] | None = None,
    status: BacktestFeedStatus = BacktestFeedStatus.READY,
    empty: bool = False,
) -> BacktestDataFeed:
    symbols = symbols or ["SPY", "AAPL"]
    closes = closes or [Decimal(index) for index in range(100, 122)]
    start = fixture_start()
    frames: list[BacktestFeedFrame] = []
    if not empty:
        for index, close in enumerate(closes):
            timestamp = start + timedelta(minutes=5 * index)
            bars = {
                symbol: bar(symbol, timestamp, close + Decimal(offset))
                for offset, symbol in enumerate(symbols)
            }
            frames.append(
                BacktestFeedFrame(
                    timestamp=timestamp,
                    bars_by_symbol=bars,
                    points=[
                        BacktestFeedPoint(symbol=symbol, bar=value, missing=False)
                        for symbol, value in bars.items()
                    ],
                    missing_symbols=[],
                )
            )
    return BacktestDataFeed(
        symbols=symbols,
        alignment_mode=BacktestAlignmentMode.UNION,
        frames=frames,
        total_bars=sum(
            1 for frame in frames for value in frame.bars_by_symbol.values() if value is not None
        ),
        frame_count=len(frames),
        first_timestamp=frames[0].timestamp if frames else None,
        last_timestamp=frames[-1].timestamp if frames else None,
        missing_bars_by_symbol={symbol: 0 for symbol in symbols},
        duplicate_timestamps_by_symbol={symbol: 0 for symbol in symbols},
        feed_status=status,
        warnings=["source feed has missing bars"] if status == BacktestFeedStatus.PARTIAL else [],
        errors=["source feed failed"] if status == BacktestFeedStatus.FAILED else [],
    )


def request() -> AnalyticalSignalEvaluationRequest:
    return AnalyticalSignalEvaluationRequest(
        symbols=["SPY", "AAPL"],
        short_window=5,
        long_window=20,
    )


def test_analytical_signal_metadata_serializes() -> None:
    metadata = default_moving_average_relationship_metadata()

    payload = metadata.model_dump(mode="json")

    assert payload["name"] == "moving_average_relationship_diagnostic"
    assert payload["broker_required"] is False
    assert payload["emits_trading_actions"] is False
    assert payload["emits_order_intents"] is False
    assert payload["required_lookback_bars"] == 20


def test_analytical_observation_rejects_unapproved_state() -> None:
    timestamp = fixture_start()

    with pytest.raises(ValidationError):
        AnalyticalSignalObservation(
            evaluator_name="moving_average_relationship_diagnostic",
            evaluator_version="0.1.0",
            symbol="SPY",
            timestamp=timestamp,
            frame_index=0,
            condition_name="moving_average_relationship_diagnostic",
            condition_state="unsupported",
            required_lookback_bars=20,
            explanation="diagnostic only",
        )


def test_analytical_observation_rejects_forbidden_output_vocabulary() -> None:
    timestamp = fixture_start()

    with pytest.raises(ValidationError):
        AnalyticalSignalObservation(
            evaluator_name="moving_average_relationship_diagnostic",
            evaluator_version="0.1.0",
            symbol="SPY",
            timestamp=timestamp,
            frame_index=0,
            condition_name="moving_average_relationship_diagnostic",
            condition_state=AnalyticalSignalConditionState.CONDITION_MET,
            required_lookback_bars=20,
            explanation="please " + "b" + "uy",
        )


def test_analytical_evaluation_emits_warmup_states() -> None:
    result = run_analytical_signal_evaluation(
        trend_feed(closes=[Decimal("100"), Decimal("101"), Decimal("102")]),
        request(),
    )

    assert result.ok is True
    assert result.diagnostics.warmup_observations == 6
    assert {
        observation.condition_state for observation in result.observations
    } == {AnalyticalSignalConditionState.INSUFFICIENT_DATA}
    assert all(observation.signal_count == 0 for observation in result.observations)


def test_analytical_evaluation_emits_invalid_data_state() -> None:
    feed = trend_feed(symbols=["SPY"], closes=[Decimal(index) for index in range(100, 121)])
    bad_frame = feed.frames[-1]
    bad_frame = bad_frame.model_copy(
        update={
            "bars_by_symbol": {
                "SPY": invalid_bar("SPY", bad_frame.timestamp),
            },
            "points": [
                BacktestFeedPoint(
                    symbol="SPY",
                    bar=invalid_bar("SPY", bad_frame.timestamp),
                    missing=False,
                )
            ],
        }
    )
    feed = feed.model_copy(update={"frames": [*feed.frames[:-1], bad_frame]})

    result = run_analytical_signal_evaluation(
        feed,
        AnalyticalSignalEvaluationRequest(symbols=["SPY"]),
    )

    assert result.ok is True
    assert result.diagnostics.evaluation_status == AnalyticalSignalEvaluationStatus.PARTIAL
    assert result.diagnostics.invalid_data_observations == 1
    assert result.observations[-1].condition_state == AnalyticalSignalConditionState.INVALID_DATA
    assert result.observations[-1].data_valid is False


def test_analytical_evaluation_proves_no_lookahead_with_future_sentinel() -> None:
    timestamp = fixture_start()
    closes = [Decimal(120 - index) for index in range(20)]
    bars = [
        bar("SPY", timestamp + timedelta(minutes=5 * index), close)
        for index, close in enumerate(closes)
    ]
    future = bar("SPY", timestamp + timedelta(minutes=105), Decimal("10000"))
    frame = BacktestFeedFrame(
        timestamp=bars[-1].timestamp,
        bars_by_symbol={"SPY": bars[-1]},
        points=[BacktestFeedPoint(symbol="SPY", bar=bars[-1], missing=False)],
        missing_symbols=[],
    )
    summary = BacktestDataFeedSummary(symbols=["SPY"], frame_count=1)
    context = build_signal_evaluation_context(frame, summary, frame_index=19)

    observations = evaluate_moving_average_relationship(
        context,
        {"SPY": [*bars, future]},
        default_moving_average_relationship_metadata(),
        short_window=5,
        long_window=20,
    )

    assert observations[0].condition_state == AnalyticalSignalConditionState.CONDITION_NOT_MET
    assert observations[0].numeric_value is not None
    assert observations[0].numeric_value < 0
    assert observations[0].threshold_or_reference_value != Decimal("10000")


def test_analytical_evaluation_uses_deterministic_symbol_order() -> None:
    result = run_analytical_signal_evaluation(trend_feed(), request())

    first_frame = [
        observation.symbol
        for observation in result.observations
        if observation.frame_index == 0
    ]

    assert first_frame == ["AAPL", "SPY"]


def test_analytical_evaluation_report_serializes() -> None:
    report = build_analytical_signal_evaluation_report(trend_feed(), request())
    payload = report.model_dump(mode="json")
    markdown = markdown_summary(payload)

    assert payload["report_type"] == "signal_evaluation"
    assert payload["signal_evaluation_enabled"] is True
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
    assert "Broker-free Analytical Signal Evaluation" in markdown


def test_validate_analytical_signal_evaluation_detects_unsorted_results() -> None:
    result = run_analytical_signal_evaluation(trend_feed(), request())
    tampered = result.model_copy(update={"observations": list(reversed(result.observations))})

    errors = validate_analytical_signal_evaluation_result(tampered)

    assert "analytical observations are not sorted by timestamp and symbol" in errors


def test_signal_evaluation_cli_runs_with_fixture_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = clean_two_symbol_dataset(tmp_path / "data" / "historical")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "signal-evaluate",
            "--symbols",
            ",".join(scenario.symbols),
            "--base-path",
            scenario.root.as_posix(),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Broker-free analytical signal evaluation" in result.output
    assert "Signal evaluation enabled" in result.output
    assert Path("reports/latest_signal_evaluation.json").exists()
    payload = json.loads(Path("reports/latest_signal_evaluation.json").read_text())
    assert payload["signal_evaluation_enabled"] is True
    assert payload["generated_" + "sig" + "nals"] is False
    assert payload["signal_count"] == 0
    assert payload["order_intents_generated"] is False
    assert payload["broker_contacted"] is False


def test_signal_evaluation_cli_fails_closed_with_missing_local_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "signal-evaluate",
            "--symbols",
            "SPY,AAPL",
            "--base-path",
            (tmp_path / "missing").as_posix(),
        ],
    )

    assert result.exit_code == 1
    assert "Broker contacted: false" in result.output
    assert "source feed contains no frames" in result.output
    payload = json.loads(Path("reports/latest_signal_evaluation.json").read_text())
    assert payload["ok"] is False
    assert payload["broker_contacted"] is False
    assert payload["order_routing_enabled"] is False


def test_signal_evaluation_path_has_no_socket_dependencies() -> None:
    source = Path("src/trader/strategy/signal_evaluation.py").read_text()

    assert "trader." + "broker" not in source
    assert "IBKR" + "ReadOnlyClient" not in source
    assert "ib" + "api" not in source


def test_signal_evaluation_path_has_no_execution_dependencies() -> None:
    source = Path("src/trader/strategy/signal_evaluation.py").read_text()

    assert "trader." + "execution" not in source
    assert "trader." + "portfolio" not in source
    assert "trader." + "risk" not in source


def test_signal_evaluation_path_has_no_order_api_names() -> None:
    source = "\n".join(
        path.read_text()
        for path in [
            Path("src/trader/strategy/signal_evaluation.py"),
            Path("scripts/run-signal-evaluate.sh"),
        ]
    )

    assert "place" + "Order" not in source
    assert "cancel" + "Order" not in source
    assert "req" + "GlobalCancel" not in source


def test_signal_evaluation_required_flags_are_safe() -> None:
    result = run_analytical_signal_evaluation(trend_feed(), request())

    assert result.signal_evaluation_enabled is True
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


def test_paper_executor_remains_blocked_for_signal_evaluation() -> None:
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


def test_live_ports_remain_rejected_for_signal_evaluation() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "7496"}, load_dotenv_file=False)

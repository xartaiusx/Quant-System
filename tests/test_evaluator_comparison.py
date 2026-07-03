from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from tests.fixtures.historical_snapshots import long_two_symbol_dataset
from typer.testing import CliRunner

import trader.cli as cli
from trader.config import ConfigError, load_config
from trader.execution.paper_executor import PaperExecutor
from trader.models import (
    EvaluatorComparisonRequest,
    EvaluatorComparisonStatus,
    EvaluatorWindowCandidate,
    ExecutionStatus,
    TradeAction,
    TradePlan,
)
from trader.reporting.reports import markdown_summary
from trader.strategy.evaluator_comparison import (
    build_evaluator_comparison_report,
    parse_window_candidates,
)


def comparison_request(root: Path, *symbols: str) -> EvaluatorComparisonRequest:
    return EvaluatorComparisonRequest(
        symbols=list(symbols) or ["SPY", "AAPL"],
        candidates=[
            EvaluatorWindowCandidate(short_window=5, long_window=20),
            EvaluatorWindowCandidate(short_window=10, long_window=20),
        ],
        requested_bar_size="5 mins",
        requested_what_to_show="TRADES",
        base_data_path=root.as_posix(),
        train_fraction=0.7,
    )


def test_parse_window_candidates() -> None:
    candidates = parse_window_candidates("5:20, 10:30")

    assert [(candidate.short_window, candidate.long_window) for candidate in candidates] == [
        (5, 20),
        (10, 30),
    ]


def test_parse_window_candidates_rejects_missing_separator() -> None:
    with pytest.raises(ValueError, match="short:long"):
        parse_window_candidates("5-20")


def test_evaluator_comparison_runs_on_local_snapshots(tmp_path: Path) -> None:
    scenario = long_two_symbol_dataset(tmp_path / "data" / "historical", bar_count=30)

    report = build_evaluator_comparison_report(comparison_request(scenario.root))

    assert report.ok is True
    assert report.final_status == EvaluatorComparisonStatus.COMPLETED
    assert len(report.results) == 2
    assert all(result.total_observations == 60 for result in report.results)
    assert report.broker_contacted is False
    assert report.signal_evaluation_enabled is True
    assert report.generated_signals is False
    assert report.signal_count == 0
    assert report.order_intents_generated is False
    assert report.pnl_calculated is False
    assert report.order_routing_enabled is False


def test_evaluator_comparison_fails_closed_when_data_missing(tmp_path: Path) -> None:
    report = build_evaluator_comparison_report(comparison_request(tmp_path / "missing"))

    assert report.ok is False
    assert report.final_status == EvaluatorComparisonStatus.FAILED
    assert report.broker_contacted is False
    assert report.order_routing_enabled is False


def test_evaluator_comparison_report_serializes_to_markdown(tmp_path: Path) -> None:
    scenario = long_two_symbol_dataset(tmp_path / "data" / "historical", bar_count=30)
    report = build_evaluator_comparison_report(comparison_request(scenario.root))

    payload = report.model_dump(mode="json")
    markdown = markdown_summary(payload)

    assert payload["report_type"] == "evaluator_comparison"
    assert "Broker-free Analytical Evaluator Comparison" in markdown
    assert "No trading signals" in markdown


def test_evaluator_compare_cli_runs_with_fixture_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = long_two_symbol_dataset(tmp_path / "data" / "historical", bar_count=30)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli.app,
        [
            "evaluator-compare",
            "--symbols",
            ",".join(scenario.symbols),
            "--base-path",
            scenario.root.as_posix(),
            "--window-pairs",
            "5:20,10:20",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Broker-free analytical evaluator comparison" in result.output
    assert "Broker contacted: false" in result.output
    payload = json.loads(Path("reports/latest_evaluator_comparison.json").read_text())
    assert payload["ok"] is True
    assert payload["generated_" + "sig" + "nals"] is False
    assert payload["order_intents_generated"] is False
    assert payload["broker_contacted"] is False


def test_evaluator_compare_cli_rejects_bad_window_pairs() -> None:
    result = CliRunner().invoke(
        cli.app,
        ["evaluator-compare", "--window-pairs", "5-20"],
    )

    assert result.exit_code == 2
    assert "Invalid --window-pairs" in result.output


def test_evaluator_comparison_path_has_no_socket_dependencies() -> None:
    source = Path("src/trader/strategy/evaluator_comparison.py").read_text()

    assert "trader." + "broker" not in source
    assert "IBKR" + "ReadOnlyClient" not in source
    assert "ib" + "api" not in source


def test_evaluator_comparison_path_has_no_order_api_names() -> None:
    source = "\n".join(
        path.read_text()
        for path in [
            Path("src/trader/strategy/evaluator_comparison.py"),
            Path("scripts/run-evaluator-compare.sh"),
        ]
        if path.exists()
    )

    assert "place" + "Order" not in source
    assert "cancel" + "Order" not in source
    assert "req" + "GlobalCancel" not in source


def test_live_ports_remain_rejected_for_evaluator_comparison() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "4001"}, load_dotenv_file=False)


def test_paper_executor_remains_blocked_for_evaluator_comparison() -> None:
    config = load_config(env={"ALLOW_PAPER_ORDERS": "true"}, load_dotenv_file=False)
    plan = TradePlan(
        symbol="SPY",
        action=TradeAction.BUY,
        quantity=1,
        limit_price=Decimal("100"),
        notional=Decimal("100"),
        strategy="unit",
        source_signal_id="unit",
    )

    result = PaperExecutor(config).submit(plan)

    assert result.status == ExecutionStatus.BLOCKED
    assert result.submitted_to_broker is False

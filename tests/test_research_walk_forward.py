from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from trader.backtest.research import build_research_backtest_report
from trader.backtest.walk_forward import (
    build_research_walk_forward_report,
    parse_research_candidates,
)
from trader.cli import app
from trader.models import (
    BacktestAlignmentMode,
    BacktestBar,
    BacktestDataFeed,
    BacktestFeedFrame,
    BacktestFeedStatus,
    ResearchBacktestRequest,
    ResearchWalkForwardRequest,
    ResearchWalkForwardStatus,
    ResearchWindowCandidate,
)
from trader.reporting.reports import markdown_summary


def _feed(bar_count: int = 140, *, holdout_variant: bool = False) -> BacktestDataFeed:
    pattern = ["100", "101", "103", "104", "102", "100", "98", "97", "99", "101"]
    start = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
    frames: list[BacktestFeedFrame] = []
    holdout_start = bar_count - 30
    for index in range(bar_count):
        base = Decimal(pattern[index % len(pattern)])
        if holdout_variant and index >= holdout_start:
            base = Decimal("130") - Decimal(index - holdout_start) / Decimal("3")
        bar = BacktestBar(
            symbol="SPY",
            timestamp=start + timedelta(minutes=5 * index),
            open=base,
            high=base + Decimal("1"),
            low=base - Decimal("1"),
            close=base,
            volume=Decimal("10000"),
        )
        frames.append(
            BacktestFeedFrame(
                timestamp=bar.timestamp,
                bars_by_symbol={"SPY": bar},
            )
        )
    return BacktestDataFeed(
        symbols=["SPY"],
        alignment_mode=BacktestAlignmentMode.INTERSECTION,
        frames=frames,
        total_bars=bar_count,
        frame_count=bar_count,
        first_timestamp=frames[0].timestamp,
        last_timestamp=frames[-1].timestamp,
        missing_bars_by_symbol={"SPY": 0},
        duplicate_timestamps_by_symbol={"SPY": 0},
        feed_status=BacktestFeedStatus.READY,
    )


def _request(**updates: object) -> ResearchWalkForwardRequest:
    values: dict[str, object] = {
        "candidates": [
            ResearchWindowCandidate(short_window=2, long_window=4),
            ResearchWindowCandidate(short_window=3, long_window=6),
        ],
        "fold_count": 2,
        "minimum_train_bars": 40,
        "validation_bars": 20,
        "holdout_bars": 30,
        "minimum_closed_trades": 1,
        "starting_cash": Decimal("10000"),
        "spread_bps": Decimal("2"),
        "slippage_bps": Decimal("1"),
        "commission_per_share": Decimal("0.005"),
        "minimum_commission": Decimal("1"),
    }
    values.update(updates)
    return ResearchWalkForwardRequest(**values)


def test_parse_research_candidates_requires_unique_ordered_pairs() -> None:
    candidates = parse_research_candidates("2:4, 3:6")

    assert [(item.short_window, item.long_window) for item in candidates] == [(2, 4), (3, 6)]
    with pytest.raises(ValueError, match="unique"):
        parse_research_candidates("2:4,2:4")
    with pytest.raises(ValueError, match="short_window"):
        parse_research_candidates("4:2")


def test_request_requires_training_history_for_longest_candidate() -> None:
    with pytest.raises(ValueError, match="longest candidate"):
        _request(minimum_train_bars=7)


def test_walk_forward_runs_anchored_folds_and_one_holdout() -> None:
    report = build_research_walk_forward_report(_feed(), _request())

    assert report.ok is True
    assert report.final_status == ResearchWalkForwardStatus.COMPLETED
    assert report.walk_forward_completed is True
    assert report.research_validation_completed is True
    assert len(report.folds) == 2
    assert [fold.train_bar_count for fold in report.folds] == [70, 90]
    assert all(len(fold.training_trials) == 2 for fold in report.folds)
    assert all(fold.selection_used_validation_data is False for fold in report.folds)
    assert report.walk_forward_summary is not None
    assert report.walk_forward_summary.completed_fold_count == 2
    assert len(report.full_development_trials) == 2
    assert report.selected_candidate is not None
    assert report.holdout_evaluation_count == 1
    assert report.holdout_used_for_selection is False
    assert report.sealed_holdout_completed is True
    assert report.holdout_report is not None
    assert report.holdout_report.warmup_bar_count > 0
    assert report.holdout_report.evaluation_bar_count == 30
    assert report.promotion_eligible is False
    assert report.broker_contacted is False
    assert report.submitted_orders is False
    assert report.order_api_invoked is False
    assert report.operator_rerun_prevention_enforced is False


def test_holdout_changes_cannot_change_candidate_selection() -> None:
    baseline = build_research_walk_forward_report(_feed(), _request())
    changed = build_research_walk_forward_report(
        _feed(holdout_variant=True),
        _request(),
    )

    assert baseline.selected_candidate == changed.selected_candidate
    assert [fold.selected_candidate for fold in baseline.folds] == [
        fold.selected_candidate for fold in changed.folds
    ]
    assert baseline.development_fingerprint == changed.development_fingerprint
    assert baseline.holdout_fingerprint != changed.holdout_fingerprint


def test_insufficient_bars_fail_before_holdout_access() -> None:
    report = build_research_walk_forward_report(_feed(80), _request())

    assert report.ok is False
    assert report.final_status == ResearchWalkForwardStatus.FAILED
    assert report.holdout_evaluation_count == 0
    assert report.holdout_report is None
    assert any("expected at least 110" in error for error in report.errors)


def test_no_eligible_candidate_fails_without_touching_holdout() -> None:
    report = build_research_walk_forward_report(
        _feed(),
        _request(minimum_closed_trades=1000),
    )

    assert report.ok is False
    assert report.holdout_evaluation_count == 0
    assert report.holdout_report is None
    assert any("no eligible training candidate" in error for error in report.errors)


def test_warmup_bars_never_generate_pre_evaluation_fills() -> None:
    feed = _feed(40)
    request = ResearchBacktestRequest(
        short_window=2,
        long_window=4,
        starting_cash=Decimal("10000"),
        spread_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        commission_per_share=Decimal("0"),
        minimum_commission=Decimal("0"),
    )

    report = build_research_backtest_report(feed, request, evaluation_start_index=10)

    assert report.ok is True
    assert report.warmup_bar_count == 10
    assert report.evaluation_bar_count == 30
    assert all(fill.signal_frame_index >= 10 for fill in report.fills)
    assert all(point.frame_index >= 10 for point in report.equity_curve)


def test_walk_forward_report_serializes_and_renders_markdown() -> None:
    report = build_research_walk_forward_report(_feed(), _request())
    payload = report.model_dump(mode="json")
    rendered = markdown_summary(payload)

    assert payload["report_type"] == "research_walk_forward"
    assert "Walk-forward Summary" in rendered
    assert "Final Sealed Holdout" in rendered
    assert "Promotion eligible: `False`" in rendered


def test_walk_forward_module_stays_broker_and_order_api_free() -> None:
    source = Path("src/trader/backtest/walk_forward.py").read_text()

    assert "trader.broker" not in source
    assert "trader.execution" not in source
    assert "ibapi" not in source
    assert "placeOrder" not in source
    assert "cancelOrder" not in source
    assert "reqGlobalCancel" not in source


def test_cli_exposes_research_walk_forward_command() -> None:
    result = CliRunner().invoke(app, ["research-walk-forward", "--help"])

    assert result.exit_code == 0
    assert "sealed holdout" in result.output

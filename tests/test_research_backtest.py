from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from trader.backtest.research import build_research_backtest_report
from trader.cli import app
from trader.models import (
    BacktestAlignmentMode,
    BacktestBar,
    BacktestDataFeed,
    BacktestFeedFrame,
    BacktestFeedStatus,
    ResearchBacktestRequest,
    ResearchBacktestStatus,
    TradeAction,
)
from trader.reporting.reports import markdown_summary


def _feed(
    closes: list[str],
    *,
    opens: list[str] | None = None,
) -> BacktestDataFeed:
    start = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
    selected_opens = opens or closes
    frames: list[BacktestFeedFrame] = []
    for index, (open_value, close_value) in enumerate(zip(selected_opens, closes, strict=True)):
        open_price = Decimal(open_value)
        close_price = Decimal(close_value)
        bar = BacktestBar(
            symbol="SPY",
            timestamp=start + timedelta(minutes=5 * index),
            open=open_price,
            high=max(open_price, close_price) + Decimal("1"),
            low=min(open_price, close_price) - Decimal("1"),
            close=close_price,
            volume=Decimal("1000"),
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
        total_bars=len(frames),
        frame_count=len(frames),
        first_timestamp=frames[0].timestamp,
        last_timestamp=frames[-1].timestamp,
        missing_bars_by_symbol={"SPY": 0},
        duplicate_timestamps_by_symbol={"SPY": 0},
        feed_status=BacktestFeedStatus.READY,
    )


def _request(**updates: object) -> ResearchBacktestRequest:
    values: dict[str, object] = {
        "short_window": 2,
        "long_window": 3,
        "starting_cash": Decimal("1000"),
        "spread_bps": Decimal("0"),
        "slippage_bps": Decimal("0"),
        "commission_per_share": Decimal("0"),
        "minimum_commission": Decimal("0"),
    }
    values.update(updates)
    return ResearchBacktestRequest(**values)


def _round_trip_feed() -> BacktestDataFeed:
    return _feed(
        ["10", "10", "10", "12", "13", "9", "8"],
        opens=["10", "10", "10", "12", "13", "9", "8"],
    )


def test_research_request_remains_spy_only() -> None:
    with pytest.raises(ValueError, match="must remain SPY"):
        ResearchBacktestRequest(symbol="GLD")


def test_research_request_requires_ordered_windows() -> None:
    with pytest.raises(ValueError, match="short_window must be less"):
        ResearchBacktestRequest(short_window=20, long_window=5)


def test_signal_fills_on_next_bar_open_without_lookahead() -> None:
    report = build_research_backtest_report(_round_trip_feed(), _request())

    assert report.ok is True
    assert report.final_status == ResearchBacktestStatus.COMPLETED
    assert len(report.fills) == 2
    assert report.fills[0].action == TradeAction.BUY
    assert report.fills[0].signal_frame_index == 3
    assert report.fills[0].fill_frame_index == 4
    assert report.fills[0].reference_price == Decimal("13")
    assert report.fills[1].action == TradeAction.SELL
    assert report.fills[1].signal_frame_index == 5
    assert report.fills[1].fill_frame_index == 6
    assert report.metrics is not None
    assert report.metrics.net_pnl == Decimal("-5.0000")
    assert report.metrics.ending_equity == Decimal("995.0000")
    assert report.promotion_eligible is False
    assert report.submitted_orders is False
    assert report.order_api_invoked is False


def test_cost_model_reduces_net_pnl_and_reports_components() -> None:
    report = build_research_backtest_report(
        _round_trip_feed(),
        _request(
            spread_bps=Decimal("2"),
            slippage_bps=Decimal("1"),
            minimum_commission=Decimal("1"),
        ),
    )

    assert report.metrics is not None
    assert report.metrics.total_commissions == Decimal("2.0000")
    assert report.metrics.total_spread_cost == Decimal("0.0021")
    assert report.metrics.total_slippage_cost == Decimal("0.0021")
    assert report.metrics.net_pnl == Decimal("-7.0042")
    assert report.metrics.gross_pnl_before_costs == Decimal("-5.0000")


def test_end_of_test_position_is_liquidated_and_logged() -> None:
    report = build_research_backtest_report(
        _feed(["10", "10", "10", "12", "13", "14"]),
        _request(),
    )

    assert report.ok is True
    assert len(report.fills) == 2
    assert len(report.trades) == 1
    assert report.trades[0].exit_reason == "end_of_test_liquidation"
    assert report.equity_curve[-1].position_quantity == 0


def test_open_position_can_be_marked_to_market_without_forced_close() -> None:
    report = build_research_backtest_report(
        _feed(["10", "10", "10", "12", "13", "14"]),
        _request(force_close_at_end=False),
    )

    assert report.ok is True
    assert len(report.fills) == 1
    assert report.trades == []
    assert report.equity_curve[-1].position_quantity == 1
    assert report.metrics is not None
    assert report.metrics.ending_equity == Decimal("1001.0000")


def test_insufficient_history_fails_closed() -> None:
    report = build_research_backtest_report(
        _feed(["10", "11", "12"]),
        _request(),
    )

    assert report.ok is False
    assert report.final_status == ResearchBacktestStatus.FAILED
    assert report.metrics is None
    assert "expected at least 5" in report.errors[0]


def test_partial_feed_fails_closed() -> None:
    feed = _round_trip_feed().model_copy(update={"feed_status": BacktestFeedStatus.PARTIAL})

    report = build_research_backtest_report(feed, _request())

    assert report.ok is False
    assert "source feed status must be ready" in report.errors


def test_duplicate_timestamps_fail_closed() -> None:
    feed = _round_trip_feed()
    duplicate = feed.frames[1].model_copy(update={"timestamp": feed.frames[0].timestamp})
    duplicate_bar = duplicate.bars_by_symbol["SPY"]
    assert duplicate_bar is not None
    duplicate = duplicate.model_copy(
        update={
            "bars_by_symbol": {
                "SPY": duplicate_bar.model_copy(update={"timestamp": feed.frames[0].timestamp})
            }
        }
    )
    feed = feed.model_copy(update={"frames": [feed.frames[0], duplicate, *feed.frames[2:]]})

    report = build_research_backtest_report(feed, _request())

    assert report.ok is False
    assert "SPY bars contain duplicate timestamps" in report.errors


def test_inconsistent_ohlc_fails_closed() -> None:
    feed = _round_trip_feed()
    bar = feed.frames[0].bars_by_symbol["SPY"]
    assert bar is not None
    invalid_bar = bar.model_copy(update={"high": bar.close - Decimal("1")})
    invalid_frame = feed.frames[0].model_copy(
        update={"bars_by_symbol": {"SPY": invalid_bar}}
    )
    feed = feed.model_copy(update={"frames": [invalid_frame, *feed.frames[1:]]})

    report = build_research_backtest_report(feed, _request())

    assert report.ok is False
    assert any("inconsistent OHLC" in error for error in report.errors)


def test_report_serializes_and_renders_markdown() -> None:
    report = build_research_backtest_report(_round_trip_feed(), _request())
    payload = report.model_dump(mode="json")
    rendered = markdown_summary(payload)

    assert payload["report_type"] == "research_backtest"
    assert payload["promotion_eligible"] is False
    assert "SPY Broker-free Research Backtest" in rendered
    assert "Lookahead prevention" in rendered
    assert "Submitted orders: `False`" in rendered


def test_research_engine_stays_broker_and_order_api_free() -> None:
    source = Path("src/trader/backtest/research.py").read_text()

    assert "trader.broker" not in source
    assert "trader.execution" not in source
    assert "ibapi" not in source
    assert "placeOrder" not in source
    assert "cancelOrder" not in source
    assert "reqGlobalCancel" not in source


def test_cli_exposes_research_backtest_command() -> None:
    result = CliRunner().invoke(app, ["research-backtest", "--help"])

    assert result.exit_code == 0
    assert "broker-free SPY research simulation" in result.output

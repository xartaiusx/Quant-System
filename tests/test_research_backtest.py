from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from trader.backtest.research import _risk_adjusted_metrics, build_research_backtest_report
from trader.cli import app
from trader.models import (
    BacktestAlignmentMode,
    BacktestBar,
    BacktestDataFeed,
    BacktestFeedFrame,
    BacktestFeedStatus,
    ResearchBacktestRequest,
    ResearchBacktestStatus,
    ResearchCorporateAction,
    ResearchDailyReturn,
    ResearchSizingMode,
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
    assert report.strategy_name == "spy_sma_target_state"
    assert report.strategy_version == "1.0.0"
    assert report.strategy_parameter_fingerprint is not None


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
    assert report.metrics.total_tick_rounding_cost == Decimal("0.0158")
    assert report.metrics.net_pnl == Decimal("-7.0200")
    assert report.metrics.gross_pnl_before_costs == Decimal("-5.0000")
    assert [scenario.multiplier for scenario in report.cost_scenarios] == [
        Decimal("1"),
        Decimal("2"),
        Decimal("3"),
    ]
    assert report.cost_scenarios[1].metrics is not None
    assert report.cost_scenarios[1].metrics.net_pnl < report.metrics.net_pnl


def test_adjusted_signal_feed_uses_raw_execution_prices() -> None:
    signal_feed = _round_trip_feed()
    execution_feed = _feed(
        ["100", "100", "100", "120", "130", "90", "80"],
        opens=["100", "100", "100", "120", "130", "90", "80"],
    )

    report = build_research_backtest_report(
        signal_feed,
        _request(starting_cash=Decimal("10000")),
        execution_feed=execution_feed,
    )

    assert report.ok is True
    assert report.signal_execution_timestamps_aligned is True
    assert report.fills[0].reference_price == Decimal("130")
    assert report.fills[0].fill_price == Decimal("130")


def test_target_allocation_is_unlevered_and_integer_sized() -> None:
    report = build_research_backtest_report(
        _round_trip_feed(),
        _request(
            sizing_mode=ResearchSizingMode.TARGET_ALLOCATION,
            target_allocation_pct=Decimal("100"),
            max_volume_participation=Decimal("1"),
        ),
    )

    assert report.ok is True
    assert report.fills[0].quantity == Decimal("76")
    assert report.fills[0].traded_notional <= Decimal("1000")
    assert report.equity_curve[0].position_quantity >= 0


def test_partial_fills_are_recorded_and_day_remainder_is_canceled() -> None:
    feed = _round_trip_feed()
    low_volume_frames = []
    for frame in feed.frames:
        bar = frame.bars_by_symbol["SPY"]
        assert bar is not None
        low_volume_frames.append(
            frame.model_copy(
                update={"bars_by_symbol": {"SPY": bar.model_copy(update={"volume": 2})}}
            )
        )
    low_volume_feed = feed.model_copy(update={"frames": low_volume_frames})

    report = build_research_backtest_report(
        low_volume_feed,
        _request(quantity=5, max_volume_participation=Decimal("0.5")),
    )

    assert report.ok is True
    assert report.fills[0].partial_fill is True
    assert report.orders[0].status == "partially_filled"
    assert report.orders[0].filled_quantity == Decimal("3")
    assert report.orders[0].remaining_quantity == Decimal("2")
    assert report.orders[0].canceled_reason == "day_expired"


def test_dividend_is_applied_to_position_held_into_ex_date() -> None:
    first_session = _feed(["10", "10", "10", "12", "13"])
    second_start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    second_frames: list[BacktestFeedFrame] = []
    for index, close in enumerate(("13", "14", "15")):
        price = Decimal(close)
        bar = BacktestBar(
            symbol="SPY",
            timestamp=second_start + timedelta(minutes=5 * index),
            open=price,
            high=price + 1,
            low=price - 1,
            close=price,
            volume=Decimal("1000"),
        )
        second_frames.append(
            BacktestFeedFrame(timestamp=bar.timestamp, bars_by_symbol={"SPY": bar})
        )
    frames = [*first_session.frames, *second_frames]
    feed = first_session.model_copy(
        update={
            "frames": frames,
            "total_bars": len(frames),
            "frame_count": len(frames),
            "last_timestamp": frames[-1].timestamp,
        }
    )
    action = ResearchCorporateAction(
        action_type="dividend",
        ex_date="2026-01-05",
        cash_amount=Decimal("1"),
        currency="USD",
        revision="fixture-v1",
    )

    report = build_research_backtest_report(
        feed,
        _request(force_close_at_end=False),
        corporate_actions=[action],
    )

    assert report.ok is True
    assert len(report.capital_events) == 1
    assert report.capital_events[0].cash_delta == Decimal("1.0000")
    assert report.daily_returns[-1].session_date == "2026-01-05"
    assert report.metrics is not None
    assert report.metrics.daily_observation_count == 2
    assert report.metrics.annualized_volatility_pct is None


def test_annualized_statistics_require_thirty_daily_observations() -> None:
    start = datetime(2026, 1, 2, tzinfo=UTC)
    observations = [
        ResearchDailyReturn(
            session_date=(start + timedelta(days=index)).date().isoformat(),
            ending_equity=Decimal("1000") + Decimal(index),
            return_pct=Decimal("0.10") if index % 2 else Decimal("-0.05"),
        )
        for index in range(30)
    ]

    cagr, volatility, sharpe, sortino, calmar = _risk_adjusted_metrics(
        observations,
        request=_request(),
        total_return_pct=Decimal("2"),
        max_drawdown_pct=Decimal("1"),
    )

    assert cagr is not None
    assert volatility is not None
    assert sharpe is not None
    assert sortino is not None
    assert calmar is not None


def test_split_adjusts_quantity_and_cost_basis_without_inventing_pnl() -> None:
    raw_first = _feed(["100", "100", "100", "120", "130"])
    signal_first = _feed(["50", "50", "50", "60", "65"])
    second_start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)

    def second_session(values: tuple[str, ...]) -> list[BacktestFeedFrame]:
        frames: list[BacktestFeedFrame] = []
        for index, value in enumerate(values):
            price = Decimal(value)
            bar = BacktestBar(
                symbol="SPY",
                timestamp=second_start + timedelta(minutes=5 * index),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=Decimal("1000"),
            )
            frames.append(
                BacktestFeedFrame(timestamp=bar.timestamp, bars_by_symbol={"SPY": bar})
            )
        return frames

    def append_session(
        feed: BacktestDataFeed,
        frames: list[BacktestFeedFrame],
    ) -> BacktestDataFeed:
        combined = [*feed.frames, *frames]
        return feed.model_copy(
            update={
                "frames": combined,
                "total_bars": len(combined),
                "frame_count": len(combined),
                "last_timestamp": combined[-1].timestamp,
            }
        )

    raw_feed = append_session(raw_first, second_session(("65", "66", "67")))
    signal_feed = append_session(signal_first, second_session(("65", "66", "67")))
    action = ResearchCorporateAction(
        action_type="split",
        ex_date="2026-01-05",
        factor=Decimal("2"),
        currency="USD",
        revision="synthetic-split-v1",
    )

    report = build_research_backtest_report(
        signal_feed,
        _request(),
        execution_feed=raw_feed,
        corporate_actions=[action],
    )

    assert report.ok is True
    assert len(report.capital_events) == 1
    assert report.capital_events[0].quantity_before == Decimal("1")
    assert report.capital_events[0].quantity_after == Decimal("2")
    assert report.capital_events[0].cash_delta == Decimal("0")
    assert report.trades[0].quantity == Decimal("2")
    assert report.trades[0].entry_price == Decimal("65.0000")
    assert report.trades[0].gross_pnl == Decimal("4.0000")
    assert report.metrics is not None
    assert report.metrics.ending_equity == Decimal("1004.0000")


def test_signal_execution_timestamp_mismatch_fails_closed() -> None:
    execution_feed = _round_trip_feed()
    changed = execution_feed.frames[-1]
    bar = changed.bars_by_symbol["SPY"]
    assert bar is not None
    shifted_bar = bar.model_copy(update={"timestamp": bar.timestamp + timedelta(minutes=1)})
    shifted_frame = changed.model_copy(
        update={
            "timestamp": shifted_bar.timestamp,
            "bars_by_symbol": {"SPY": shifted_bar},
        }
    )
    execution_feed = execution_feed.model_copy(
        update={"frames": [*execution_feed.frames[:-1], shifted_frame]}
    )

    report = build_research_backtest_report(
        _round_trip_feed(),
        _request(),
        execution_feed=execution_feed,
    )

    assert report.ok is False
    assert "timestamps must align exactly" in report.errors[0]


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

"""Cost-aware, broker-free SPY research backtester."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from trader.backtest.data_adapter import summarize_backtest_feed
from trader.models import (
    BacktestBar,
    BacktestDataFeed,
    BacktestFeedStatus,
    ResearchBacktestEquityPoint,
    ResearchBacktestFill,
    ResearchBacktestMetrics,
    ResearchBacktestReport,
    ResearchBacktestRequest,
    ResearchBacktestStatus,
    ResearchBacktestTrade,
    TradeAction,
)

_BPS = Decimal("10000")
_MONEY_QUANTUM = Decimal("0.0001")
_PERCENT_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class _PendingSignal:
    action: TradeAction
    timestamp: datetime
    frame_index: int
    reason: str


@dataclass(frozen=True)
class _SimulationResult:
    fills: list[ResearchBacktestFill]
    trades: list[ResearchBacktestTrade]
    equity_curve: list[ResearchBacktestEquityPoint]
    metrics: ResearchBacktestMetrics | None
    warnings: list[str]
    errors: list[str]


def build_research_backtest_report(
    feed: BacktestDataFeed,
    request: ResearchBacktestRequest,
    *,
    evaluation_start_index: int = 0,
) -> ResearchBacktestReport:
    """Run a deterministic long-only SPY simulation from an offline feed."""

    warnings = list(feed.warnings)
    errors = list(feed.errors)
    bars = _symbol_bars(feed, request.symbol)
    if feed.feed_status != BacktestFeedStatus.READY:
        errors.append("source feed status must be ready")
    if feed.symbols != [request.symbol]:
        errors.append("research backtest requires a SPY-only feed")
    timestamps = [bar.timestamp for bar in bars]
    if timestamps != sorted(timestamps):
        errors.append("SPY bars must be ordered by timestamp")
    if len(timestamps) != len(set(timestamps)):
        errors.append("SPY bars contain duplicate timestamps")
    for bar in bars:
        errors.extend(_validate_bar(bar))
    if evaluation_start_index < 0 or evaluation_start_index >= len(bars):
        errors.append("evaluation_start_index must identify a source bar")
    elif evaluation_start_index > 0 and evaluation_start_index < request.long_window + 1:
        errors.append("warmup segment must cover long_window + 1 bars")
    evaluation_bar_count = max(0, len(bars) - evaluation_start_index)
    minimum_bars = request.long_window + 2 if evaluation_start_index == 0 else 2
    observed_bars = len(bars) if evaluation_start_index == 0 else evaluation_bar_count
    if observed_bars < minimum_bars:
        errors.append(
            f"SPY evaluation bars observed {observed_bars}; expected at least {minimum_bars}"
        )

    if errors:
        return ResearchBacktestReport(
            ok=False,
            request=request,
            feed_summary=summarize_backtest_feed(feed),
            warnings=list(dict.fromkeys(warnings)),
            errors=list(dict.fromkeys(errors)),
            final_status=ResearchBacktestStatus.FAILED,
            warmup_bar_count=evaluation_start_index,
            evaluation_bar_count=evaluation_bar_count,
        )

    result = _simulate(bars, request, evaluation_start_index=evaluation_start_index)
    combined_warnings = list(dict.fromkeys([*warnings, *result.warnings]))
    combined_errors = list(dict.fromkeys(result.errors))
    return ResearchBacktestReport(
        ok=not combined_errors,
        request=request,
        feed_summary=summarize_backtest_feed(feed),
        fills=result.fills,
        trades=result.trades,
        equity_curve=result.equity_curve,
        metrics=result.metrics,
        warnings=combined_warnings,
        errors=combined_errors,
        final_status=(
            ResearchBacktestStatus.COMPLETED
            if not combined_errors
            else ResearchBacktestStatus.FAILED
        ),
        warmup_bar_count=evaluation_start_index,
        evaluation_bar_count=evaluation_bar_count,
    )


def _simulate(
    bars: list[BacktestBar],
    request: ResearchBacktestRequest,
    *,
    evaluation_start_index: int,
) -> _SimulationResult:
    cash = request.starting_cash
    position = 0
    pending: _PendingSignal | None = None
    open_fill: ResearchBacktestFill | None = None
    fills: list[ResearchBacktestFill] = []
    trades: list[ResearchBacktestTrade] = []
    equity_curve: list[ResearchBacktestEquityPoint] = []
    closes: list[Decimal] = []
    warnings: list[str] = []
    errors: list[str] = []
    signal_count = 0
    exposure_bars = 0
    peak_equity = request.starting_cash

    for frame_index, bar in enumerate(bars):
        if frame_index >= evaluation_start_index and pending is not None:
            fill = _build_fill(
                request,
                action=pending.action,
                signal_timestamp=pending.timestamp,
                fill_timestamp=bar.timestamp,
                signal_frame_index=pending.frame_index,
                fill_frame_index=frame_index,
                reference_price=bar.open,
                cash=cash,
                position=position,
                reason=pending.reason,
            )
            if fill.action == TradeAction.BUY:
                required_cash = fill.traded_notional + fill.commission
                if required_cash > cash:
                    errors.append("simulated buy rejected: insufficient cash")
                    break
                cash = fill.cash_after
                position = fill.position_after
                open_fill = fill
            else:
                if open_fill is None or position < request.quantity:
                    errors.append("simulated sell rejected: no matching long position")
                    break
                cash = fill.cash_after
                position = fill.position_after
                trades.append(_close_trade(open_fill, fill))
                open_fill = None
            fills.append(fill)
            pending = None

        closes.append(bar.close)
        if (
            frame_index >= evaluation_start_index
            and len(closes) >= request.long_window + 1
        ):
            previous_fast = _average(closes[-request.short_window - 1 : -1])
            previous_slow = _average(closes[-request.long_window - 1 : -1])
            current_fast = _average(closes[-request.short_window :])
            current_slow = _average(closes[-request.long_window :])
            if position == 0 and previous_fast <= previous_slow and current_fast > current_slow:
                pending = _PendingSignal(
                    action=TradeAction.BUY,
                    timestamp=bar.timestamp,
                    frame_index=frame_index,
                    reason="bullish_moving_average_cross",
                )
                signal_count += 1
            elif (
                position > 0
                and previous_fast >= previous_slow
                and current_fast < current_slow
            ):
                pending = _PendingSignal(
                    action=TradeAction.SELL,
                    timestamp=bar.timestamp,
                    frame_index=frame_index,
                    reason="bearish_moving_average_cross",
                )
                signal_count += 1

        if frame_index >= evaluation_start_index:
            if position > 0:
                exposure_bars += 1
            point, peak_equity = _equity_point(
                bar,
                frame_index=frame_index,
                cash=cash,
                position=position,
                peak_equity=peak_equity,
            )
            equity_curve.append(point)

    if not errors and position > 0 and request.force_close_at_end:
        final_bar = bars[-1]
        exit_fill = _build_fill(
            request,
            action=TradeAction.SELL,
            signal_timestamp=final_bar.timestamp,
            fill_timestamp=final_bar.timestamp,
            signal_frame_index=len(bars) - 1,
            fill_frame_index=len(bars) - 1,
            reference_price=final_bar.close,
            cash=cash,
            position=position,
            reason="end_of_test_liquidation",
        )
        if open_fill is None:
            errors.append("end-of-test liquidation has no matching entry fill")
        else:
            cash = exit_fill.cash_after
            position = exit_fill.position_after
            fills.append(exit_fill)
            trades.append(_close_trade(open_fill, exit_fill))
            previous_peak = max(
                [request.starting_cash, *[point.equity for point in equity_curve[:-1]]]
            )
            final_point, _ = _equity_point(
                final_bar,
                frame_index=len(bars) - 1,
                cash=cash,
                position=position,
                peak_equity=previous_peak,
            )
            equity_curve[-1] = final_point

    if pending is not None:
        warnings.append("final-bar signal was not filled because no next bar exists")

    metrics = None if errors else _metrics(
        bars[evaluation_start_index:],
        request,
        fills=fills,
        trades=trades,
        equity_curve=equity_curve,
        signal_count=signal_count,
        exposure_bars=exposure_bars,
    )
    return _SimulationResult(
        fills=fills,
        trades=trades,
        equity_curve=equity_curve,
        metrics=metrics,
        warnings=warnings,
        errors=errors,
    )


def _build_fill(
    request: ResearchBacktestRequest,
    *,
    action: TradeAction,
    signal_timestamp: datetime,
    fill_timestamp: datetime,
    signal_frame_index: int,
    fill_frame_index: int,
    reference_price: Decimal,
    cash: Decimal,
    position: int,
    reason: str,
) -> ResearchBacktestFill:
    half_spread_bps = request.spread_bps / Decimal("2")
    total_impact_bps = half_spread_bps + request.slippage_bps
    direction = Decimal("1") if action == TradeAction.BUY else Decimal("-1")
    fill_price = _money(reference_price * (Decimal("1") + direction * total_impact_bps / _BPS))
    spread_cost = _money(
        reference_price * Decimal(request.quantity) * half_spread_bps / _BPS
    )
    slippage_cost = _money(
        reference_price * Decimal(request.quantity) * request.slippage_bps / _BPS
    )
    commission = max(
        request.minimum_commission,
        request.commission_per_share * Decimal(request.quantity),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    traded_notional = _money(fill_price * Decimal(request.quantity))
    if action == TradeAction.BUY:
        cash_after = _money(cash - traded_notional - commission)
        position_after = position + request.quantity
    else:
        cash_after = _money(cash + traded_notional - commission)
        position_after = position - request.quantity
    return ResearchBacktestFill(
        symbol=request.symbol,
        action=action,
        quantity=request.quantity,
        signal_timestamp=signal_timestamp,
        fill_timestamp=fill_timestamp,
        signal_frame_index=signal_frame_index,
        fill_frame_index=fill_frame_index,
        reference_price=reference_price,
        fill_price=fill_price,
        commission=commission,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        traded_notional=traded_notional,
        cash_after=cash_after,
        position_after=position_after,
        reason=reason,
    )


def _close_trade(
    entry: ResearchBacktestFill,
    exit_fill: ResearchBacktestFill,
) -> ResearchBacktestTrade:
    gross_pnl = _money(
        (exit_fill.fill_price - entry.fill_price) * Decimal(entry.quantity)
    )
    net_pnl = _money(gross_pnl - entry.commission - exit_fill.commission)
    return ResearchBacktestTrade(
        symbol=entry.symbol,
        quantity=entry.quantity,
        entry_timestamp=entry.fill_timestamp,
        exit_timestamp=exit_fill.fill_timestamp,
        entry_price=entry.fill_price,
        exit_price=exit_fill.fill_price,
        entry_commission=entry.commission,
        exit_commission=exit_fill.commission,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        holding_bars=exit_fill.fill_frame_index - entry.fill_frame_index,
        profitable=net_pnl > 0,
        exit_reason=exit_fill.reason,
    )


def _equity_point(
    bar: BacktestBar,
    *,
    frame_index: int,
    cash: Decimal,
    position: int,
    peak_equity: Decimal,
) -> tuple[ResearchBacktestEquityPoint, Decimal]:
    position_value = _money(bar.close * Decimal(position))
    equity = _money(cash + position_value)
    updated_peak = max(peak_equity, equity)
    drawdown = (
        Decimal("0")
        if updated_peak <= 0
        else _percent((updated_peak - equity) / updated_peak * Decimal("100"))
    )
    return (
        ResearchBacktestEquityPoint(
            timestamp=bar.timestamp,
            frame_index=frame_index,
            cash=cash,
            position_quantity=position,
            mark_price=bar.close,
            position_value=position_value,
            equity=equity,
            drawdown_pct=drawdown,
        ),
        updated_peak,
    )


def _metrics(
    bars: list[BacktestBar],
    request: ResearchBacktestRequest,
    *,
    fills: list[ResearchBacktestFill],
    trades: list[ResearchBacktestTrade],
    equity_curve: list[ResearchBacktestEquityPoint],
    signal_count: int,
    exposure_bars: int,
) -> ResearchBacktestMetrics:
    ending_equity = equity_curve[-1].equity
    ending_cash = equity_curve[-1].cash
    net_pnl = _money(ending_equity - request.starting_cash)
    commissions = _money(sum((fill.commission for fill in fills), Decimal("0")))
    spread_cost = _money(sum((fill.spread_cost for fill in fills), Decimal("0")))
    slippage_cost = _money(sum((fill.slippage_cost for fill in fills), Decimal("0")))
    total_notional = _money(sum((fill.traded_notional for fill in fills), Decimal("0")))
    total_costs = commissions + spread_cost + slippage_cost
    winning = sum(1 for trade in trades if trade.profitable)
    closed_count = len(trades)
    first_close = bars[0].close
    benchmark_return = (
        Decimal("0")
        if first_close <= 0
        else (bars[-1].close / first_close - Decimal("1")) * Decimal("100")
    )
    return ResearchBacktestMetrics(
        starting_cash=request.starting_cash,
        ending_cash=ending_cash,
        ending_equity=ending_equity,
        gross_pnl_before_costs=_money(net_pnl + total_costs),
        net_pnl=net_pnl,
        total_return_pct=_percent(net_pnl / request.starting_cash * Decimal("100")),
        benchmark_return_pct=_percent(benchmark_return),
        max_drawdown_pct=max((point.drawdown_pct for point in equity_curve), default=Decimal("0")),
        turnover_ratio=_percent(total_notional / request.starting_cash),
        total_traded_notional=total_notional,
        total_commissions=commissions,
        total_spread_cost=spread_cost,
        total_slippage_cost=slippage_cost,
        signal_count=signal_count,
        fill_count=len(fills),
        closed_trade_count=closed_count,
        winning_trade_count=winning,
        win_rate_pct=(
            Decimal("0")
            if closed_count == 0
            else _percent(Decimal(winning) / Decimal(closed_count) * Decimal("100"))
        ),
        exposure_pct=_percent(Decimal(exposure_bars) / Decimal(len(bars)) * Decimal("100")),
    )


def _symbol_bars(feed: BacktestDataFeed, symbol: str) -> list[BacktestBar]:
    return [
        bar
        for frame in feed.frames
        if (bar := frame.bars_by_symbol.get(symbol)) is not None
    ]


def _validate_bar(bar: BacktestBar) -> list[str]:
    values = (bar.open, bar.high, bar.low, bar.close)
    if any(not value.is_finite() or value <= 0 for value in values):
        return [f"SPY bar {bar.timestamp.isoformat()} has invalid nonpositive OHLC"]
    if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
        return [f"SPY bar {bar.timestamp.isoformat()} has inconsistent OHLC"]
    return []


def _average(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _percent(value: Decimal) -> Decimal:
    return value.quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)

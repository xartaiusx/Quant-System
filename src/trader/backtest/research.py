"""Catalog-backed, broker-free SPY research simulator."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from trader.backtest.data_adapter import summarize_backtest_feed
from trader.models import (
    BacktestBar,
    BacktestDataFeed,
    BacktestFeedStatus,
    ResearchBacktestCostScenario,
    ResearchBacktestEquityPoint,
    ResearchBacktestFill,
    ResearchBacktestMetrics,
    ResearchBacktestOrder,
    ResearchBacktestReport,
    ResearchBacktestRequest,
    ResearchBacktestStatus,
    ResearchBacktestTrade,
    ResearchCapitalEventRecord,
    ResearchCorporateAction,
    ResearchDailyReturn,
    ResearchOrderStatus,
    ResearchSizingMode,
    SPYTargetState,
    TradeAction,
)
from trader.strategy.spy_sma import evaluate_spy_sma_policy, spy_sma_parameter_fingerprint

_BPS = Decimal("10000")
_MONEY_QUANTUM = Decimal("0.0001")
_PERCENT_QUANTUM = Decimal("0.0001")
_RATIO_QUANTUM = Decimal("0.000001")
_MIN_ANNUALIZED_OBSERVATIONS = 30
_EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class _PendingSignal:
    action: TradeAction
    timestamp: datetime
    frame_index: int
    reason: str


@dataclass
class _ActiveOrder:
    order_id: str
    action: TradeAction
    requested_quantity: Decimal
    remaining_quantity: Decimal
    submitted_timestamp: datetime
    submitted_frame_index: int
    limit_price: Decimal
    signal: _PendingSignal


@dataclass
class _OpenLot:
    quantity: Decimal
    entry_timestamp: datetime
    entry_frame_index: int
    entry_price: Decimal
    entry_commission: Decimal


@dataclass
class _ExitAccumulator:
    quantity: Decimal
    exit_timestamp: datetime
    exit_frame_index: int
    exit_price: Decimal
    exit_commission: Decimal
    reason: str


@dataclass(frozen=True)
class _SimulationResult:
    fills: list[ResearchBacktestFill]
    orders: list[ResearchBacktestOrder]
    trades: list[ResearchBacktestTrade]
    equity_curve: list[ResearchBacktestEquityPoint]
    capital_events: list[ResearchCapitalEventRecord]
    daily_returns: list[ResearchDailyReturn]
    metrics: ResearchBacktestMetrics | None
    warnings: list[str]
    errors: list[str]


def build_research_backtest_report(
    feed: BacktestDataFeed,
    request: ResearchBacktestRequest,
    *,
    execution_feed: BacktestDataFeed | None = None,
    benchmark_feed: BacktestDataFeed | None = None,
    corporate_actions: list[ResearchCorporateAction] | None = None,
    evaluation_start_index: int = 0,
) -> ResearchBacktestReport:
    """Run a long-only SPY LMT DAY simulation from offline catalog-like feeds."""

    selected_execution_feed = execution_feed or feed
    actions = corporate_actions or []
    warnings = list(dict.fromkeys([*feed.warnings, *selected_execution_feed.warnings]))
    errors = list(dict.fromkeys([*feed.errors, *selected_execution_feed.errors]))
    signal_bars = _symbol_bars(feed, request.symbol)
    execution_bars = _symbol_bars(selected_execution_feed, request.symbol)
    benchmark_bars = (
        _symbol_bars(benchmark_feed, request.symbol) if benchmark_feed is not None else []
    )
    if feed.feed_status != BacktestFeedStatus.READY:
        errors.append("source feed status must be ready")
    if (
        execution_feed is not None
        and selected_execution_feed.feed_status != BacktestFeedStatus.READY
    ):
        errors.append("source execution feed status must be ready")
    if feed.symbols != [request.symbol] or selected_execution_feed.symbols != [
        request.symbol
    ]:
        errors.append("research backtest requires SPY-only signal and execution feeds")
    signal_timestamps = [bar.timestamp for bar in signal_bars]
    execution_timestamps = [bar.timestamp for bar in execution_bars]
    timestamps_aligned = signal_timestamps == execution_timestamps
    if signal_timestamps != sorted(signal_timestamps):
        errors.append("SPY signal bars must be ordered by timestamp")
    if len(signal_timestamps) != len(set(signal_timestamps)):
        errors.append("SPY bars contain duplicate timestamps")
    if not timestamps_aligned:
        errors.append("SPY signal and raw execution timestamps must align exactly")
    for bar in [*signal_bars, *execution_bars]:
        errors.extend(_validate_bar(bar))
    if benchmark_feed is not None and benchmark_feed.feed_status != BacktestFeedStatus.READY:
        errors.append("source benchmark feed status must be ready")
    if evaluation_start_index < 0 or evaluation_start_index >= len(signal_bars):
        errors.append("evaluation_start_index must identify a source bar")
    elif evaluation_start_index > 0 and evaluation_start_index < request.long_window + 1:
        errors.append("warmup segment must cover long_window + 1 bars")
    evaluation_bar_count = max(0, len(signal_bars) - evaluation_start_index)
    minimum_bars = request.long_window + 2 if evaluation_start_index == 0 else 2
    observed_bars = len(signal_bars) if evaluation_start_index == 0 else evaluation_bar_count
    if observed_bars < minimum_bars:
        errors.append(
            f"SPY evaluation bars observed {observed_bars}; expected at least {minimum_bars}"
        )
    errors.extend(_validate_actions(actions))

    if errors:
        return ResearchBacktestReport(
            ok=False,
            request=request,
            feed_summary=summarize_backtest_feed(feed),
            execution_feed_summary=summarize_backtest_feed(selected_execution_feed),
            benchmark_feed_summary=(
                summarize_backtest_feed(benchmark_feed)
                if benchmark_feed is not None
                else None
            ),
            warnings=list(dict.fromkeys(warnings)),
            errors=list(dict.fromkeys(errors)),
            final_status=ResearchBacktestStatus.FAILED,
            strategy_parameter_fingerprint=spy_sma_parameter_fingerprint(
                request.short_window,
                request.long_window,
            ),
            signal_execution_timestamps_aligned=timestamps_aligned,
            warmup_bar_count=evaluation_start_index,
            evaluation_bar_count=evaluation_bar_count,
        )

    scenario_results = [
        (
            name,
            multiplier,
            _simulate(
                signal_bars,
                execution_bars,
                benchmark_bars,
                actions,
                request,
                evaluation_start_index=evaluation_start_index,
                cost_multiplier=multiplier,
            ),
        )
        for name, multiplier in (
            ("base", Decimal("1")),
            ("2x_costs", Decimal("2")),
            ("3x_costs", Decimal("3")),
            ("5x_crisis_costs", Decimal("5")),
        )
    ]
    result = scenario_results[0][2]
    cost_scenarios = [
        ResearchBacktestCostScenario(
            name=name,
            multiplier=multiplier,
            metrics=scenario.metrics,
            ok=not scenario.errors,
            errors=scenario.errors,
        )
        for name, multiplier, scenario in scenario_results
    ]
    combined_warnings = list(dict.fromkeys([*warnings, *result.warnings]))
    combined_errors = list(dict.fromkeys(result.errors))
    for name, _, scenario in scenario_results[1:]:
        if scenario.errors:
            combined_warnings.append(f"{name} scenario failed: {scenario.errors[0]}")
    return ResearchBacktestReport(
        ok=not combined_errors,
        request=request,
        feed_summary=summarize_backtest_feed(feed),
        execution_feed_summary=summarize_backtest_feed(selected_execution_feed),
        benchmark_feed_summary=(
            summarize_backtest_feed(benchmark_feed) if benchmark_feed is not None else None
        ),
        fills=result.fills,
        orders=result.orders,
        trades=result.trades,
        equity_curve=result.equity_curve,
        capital_events=result.capital_events,
        daily_returns=result.daily_returns,
        cost_scenarios=cost_scenarios,
        metrics=result.metrics,
        warnings=list(dict.fromkeys(combined_warnings)),
        errors=combined_errors,
        final_status=(
            ResearchBacktestStatus.COMPLETED
            if not combined_errors
            else ResearchBacktestStatus.FAILED
        ),
        strategy_parameter_fingerprint=spy_sma_parameter_fingerprint(
            request.short_window,
            request.long_window,
        ),
        signal_execution_timestamps_aligned=timestamps_aligned,
        warmup_bar_count=evaluation_start_index,
        evaluation_bar_count=evaluation_bar_count,
    )


def _simulate(
    signal_bars: list[BacktestBar],
    execution_bars: list[BacktestBar],
    benchmark_bars: list[BacktestBar],
    actions: list[ResearchCorporateAction],
    request: ResearchBacktestRequest,
    *,
    evaluation_start_index: int,
    cost_multiplier: Decimal,
) -> _SimulationResult:
    cash = request.starting_cash
    position = Decimal("0")
    pending: _PendingSignal | None = None
    active_order: _ActiveOrder | None = None
    open_lot: _OpenLot | None = None
    exit_accumulator: _ExitAccumulator | None = None
    fills: list[ResearchBacktestFill] = []
    orders: list[ResearchBacktestOrder] = []
    trades: list[ResearchBacktestTrade] = []
    equity_curve: list[ResearchBacktestEquityPoint] = []
    capital_events: list[ResearchCapitalEventRecord] = []
    warnings: list[str] = []
    errors: list[str] = []
    signal_count = 0
    exposure_bars = 0
    peak_equity = request.starting_cash
    order_number = 0
    current_session: date | None = None
    actions_by_date = _actions_by_date(actions)

    for frame_index, (signal_bar, execution_bar) in enumerate(
        zip(signal_bars, execution_bars, strict=True)
    ):
        session_date = _session_date(execution_bar.timestamp)
        if session_date != current_session:
            current_session = session_date
            (
                cash,
                position,
                open_lot,
                exit_accumulator,
                event_records,
            ) = _apply_capital_events(
                actions_by_date.get(session_date, []),
                timestamp=execution_bar.timestamp,
                cash=cash,
                position=position,
                open_lot=open_lot,
                exit_accumulator=exit_accumulator,
            )
            capital_events.extend(event_records)

        if frame_index >= evaluation_start_index and pending is not None:
            order_number += 1
            limit_price = _limit_price(
                request,
                action=pending.action,
                reference_price=execution_bar.open,
                cost_multiplier=cost_multiplier,
            )
            requested_quantity = _order_quantity(
                request,
                action=pending.action,
                cash=cash,
                position=position,
                reference_price=limit_price,
            )
            if requested_quantity <= 0:
                warnings.append(
                    f"simulated {pending.action} skipped because approved quantity was zero"
                )
            else:
                active_order = _ActiveOrder(
                    order_id=f"sim-{order_number:06d}",
                    action=pending.action,
                    requested_quantity=requested_quantity,
                    remaining_quantity=requested_quantity,
                    submitted_timestamp=execution_bar.timestamp,
                    submitted_frame_index=frame_index,
                    limit_price=limit_price,
                    signal=pending,
                )
            pending = None

        if active_order is not None:
            available_quantity = _available_quantity(execution_bar, request)
            if _trade_through(active_order, execution_bar) and available_quantity > 0:
                fill_quantity = min(
                    active_order.remaining_quantity,
                    available_quantity,
                )
                if active_order.action == TradeAction.SELL:
                    fill_quantity = min(fill_quantity, position)
                fill = _build_fill(
                    request,
                    active_order=active_order,
                    fill_timestamp=execution_bar.timestamp,
                    fill_frame_index=frame_index,
                    reference_price=execution_bar.open,
                    quantity=fill_quantity,
                    available_quantity=available_quantity,
                    cash=cash,
                    position=position,
                    cost_multiplier=cost_multiplier,
                )
                if fill.action == TradeAction.BUY:
                    required_cash = fill.traded_notional + fill.commission
                    if required_cash > cash:
                        errors.append("simulated buy rejected: insufficient cash")
                        break
                    cash = fill.cash_after
                    position = fill.position_after
                    open_lot = _add_entry_fill(open_lot, fill)
                else:
                    if open_lot is None or position < fill.quantity:
                        errors.append("simulated sell rejected: no matching long position")
                        break
                    cash = fill.cash_after
                    position = fill.position_after
                    exit_accumulator = _add_exit_fill(exit_accumulator, fill)
                    if position == 0:
                        assert exit_accumulator is not None
                        trades.append(_close_trade(open_lot, exit_accumulator))
                        open_lot = None
                        exit_accumulator = None
                fills.append(fill)
                active_order.remaining_quantity -= fill.quantity
                if active_order.remaining_quantity == 0:
                    orders.append(
                        _terminal_order(
                            active_order,
                            timestamp=execution_bar.timestamp,
                            status=ResearchOrderStatus.FILLED,
                        )
                    )
                    active_order = None

        if (
            not errors
            and frame_index >= evaluation_start_index
            and frame_index + 1 >= request.long_window + 1
            and pending is None
            and active_order is None
        ):
            policy = evaluate_spy_sma_policy(
                signal_bars[: frame_index + 1],
                short_window=request.short_window,
                long_window=request.long_window,
            )
            if position == 0 and policy.target_state == SPYTargetState.LONG:
                pending = _PendingSignal(
                    action=TradeAction.BUY,
                    timestamp=signal_bar.timestamp,
                    frame_index=frame_index,
                    reason=str(policy.transition),
                )
                signal_count += 1
            elif position > 0 and policy.target_state == SPYTargetState.FLAT:
                pending = _PendingSignal(
                    action=TradeAction.SELL,
                    timestamp=signal_bar.timestamp,
                    frame_index=frame_index,
                    reason=str(policy.transition),
                )
                signal_count += 1

        if active_order is not None and _is_session_end(execution_bars, frame_index):
            orders.append(
                _terminal_order(
                    active_order,
                    timestamp=execution_bar.timestamp,
                    status=ResearchOrderStatus.CANCELED,
                    canceled_reason="day_expired",
                )
            )
            active_order = None

        if frame_index >= evaluation_start_index:
            if position > 0:
                exposure_bars += 1
            point, peak_equity = _equity_point(
                execution_bar,
                frame_index=frame_index,
                cash=cash,
                position=position,
                peak_equity=peak_equity,
            )
            equity_curve.append(point)

    if not errors and position > 0 and request.force_close_at_end:
        final_bar = execution_bars[-1]
        order_number += 1
        forced_signal = _PendingSignal(
            action=TradeAction.SELL,
            timestamp=final_bar.timestamp,
            frame_index=len(execution_bars) - 1,
            reason="end_of_test_liquidation",
        )
        forced_order = _ActiveOrder(
            order_id=f"sim-{order_number:06d}",
            action=TradeAction.SELL,
            requested_quantity=position,
            remaining_quantity=position,
            submitted_timestamp=final_bar.timestamp,
            submitted_frame_index=len(execution_bars) - 1,
            limit_price=_limit_price(
                request,
                action=TradeAction.SELL,
                reference_price=final_bar.close,
                cost_multiplier=cost_multiplier,
            ),
            signal=forced_signal,
        )
        fill = _build_fill(
            request,
            active_order=forced_order,
            fill_timestamp=final_bar.timestamp,
            fill_frame_index=len(execution_bars) - 1,
            reference_price=final_bar.close,
            quantity=position,
            available_quantity=position,
            cash=cash,
            position=position,
            cost_multiplier=cost_multiplier,
        )
        if open_lot is None:
            errors.append("end-of-test liquidation has no matching entry lot")
        else:
            cash = fill.cash_after
            position = fill.position_after
            fills.append(fill)
            exit_accumulator = _add_exit_fill(exit_accumulator, fill)
            assert exit_accumulator is not None
            trades.append(_close_trade(open_lot, exit_accumulator))
            orders.append(
                _terminal_order(
                    forced_order,
                    timestamp=final_bar.timestamp,
                    status=ResearchOrderStatus.FILLED,
                )
            )
            previous_peak = max(
                [request.starting_cash, *[point.equity for point in equity_curve[:-1]]]
            )
            final_point, _ = _equity_point(
                final_bar,
                frame_index=len(execution_bars) - 1,
                cash=cash,
                position=position,
                peak_equity=previous_peak,
            )
            equity_curve[-1] = final_point
            warnings.append(
                "End-of-test liquidation bypassed participation only to close accounting"
            )

    if pending is not None:
        warnings.append("final-bar signal was not submitted because no next bar exists")

    daily_returns = _daily_returns(equity_curve, request.starting_cash)
    metrics = None if errors else _metrics(
        execution_bars[evaluation_start_index:],
        benchmark_bars,
        request,
        fills=fills,
        trades=trades,
        equity_curve=equity_curve,
        daily_returns=daily_returns,
        signal_count=signal_count,
        exposure_bars=exposure_bars,
    )
    return _SimulationResult(
        fills=fills,
        orders=orders,
        trades=trades,
        equity_curve=equity_curve,
        capital_events=capital_events,
        daily_returns=daily_returns,
        metrics=metrics,
        warnings=warnings,
        errors=errors,
    )


def _limit_price(
    request: ResearchBacktestRequest,
    *,
    action: TradeAction,
    reference_price: Decimal,
    cost_multiplier: Decimal,
) -> Decimal:
    adverse_bps = (
        request.spread_bps / Decimal("2") + request.slippage_bps
    ) * cost_multiplier + request.limit_buffer_bps
    direction = Decimal("1") if action == TradeAction.BUY else Decimal("-1")
    raw = reference_price * (Decimal("1") + direction * adverse_bps / _BPS)
    rounding = ROUND_CEILING if action == TradeAction.BUY else ROUND_FLOOR
    return (raw / request.tick_size).to_integral_value(rounding=rounding) * request.tick_size


def _order_quantity(
    request: ResearchBacktestRequest,
    *,
    action: TradeAction,
    cash: Decimal,
    position: Decimal,
    reference_price: Decimal,
) -> Decimal:
    if action == TradeAction.SELL:
        return position
    if request.sizing_mode == ResearchSizingMode.FIXED_QUANTITY:
        return Decimal(request.quantity)
    target_notional = cash * request.target_allocation_pct / Decimal("100")
    return (target_notional / reference_price).to_integral_value(rounding=ROUND_FLOOR)


def _available_quantity(
    bar: BacktestBar,
    request: ResearchBacktestRequest,
) -> Decimal:
    volume = bar.volume or Decimal("0")
    return (volume * request.max_volume_participation).to_integral_value(
        rounding=ROUND_FLOOR
    )


def _trade_through(order: _ActiveOrder, bar: BacktestBar) -> bool:
    if order.action == TradeAction.BUY:
        return bar.low <= order.limit_price
    return bar.high >= order.limit_price


def _build_fill(
    request: ResearchBacktestRequest,
    *,
    active_order: _ActiveOrder,
    fill_timestamp: datetime,
    fill_frame_index: int,
    reference_price: Decimal,
    quantity: Decimal,
    available_quantity: Decimal,
    cash: Decimal,
    position: Decimal,
    cost_multiplier: Decimal,
) -> ResearchBacktestFill:
    half_spread_bps = request.spread_bps / Decimal("2") * cost_multiplier
    slippage_bps = request.slippage_bps * cost_multiplier
    direction = Decimal("1") if active_order.action == TradeAction.BUY else Decimal("-1")
    theoretical = reference_price * (
        Decimal("1") + direction * (half_spread_bps + slippage_bps) / _BPS
    )
    rounding = ROUND_CEILING if active_order.action == TradeAction.BUY else ROUND_FLOOR
    fill_price = (
        theoretical / request.tick_size
    ).to_integral_value(rounding=rounding) * request.tick_size
    if active_order.action == TradeAction.BUY:
        fill_price = min(fill_price, active_order.limit_price)
    else:
        fill_price = max(fill_price, active_order.limit_price)
    spread_cost = _money(reference_price * quantity * half_spread_bps / _BPS)
    slippage_cost = _money(reference_price * quantity * slippage_bps / _BPS)
    theoretical_cost = abs(theoretical - reference_price) * quantity
    actual_cost = abs(fill_price - reference_price) * quantity
    tick_rounding_cost = _money(max(Decimal("0"), actual_cost - theoretical_cost))
    commission = max(
        request.minimum_commission,
        request.commission_per_share * quantity,
    ) * cost_multiplier
    commission = commission.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    traded_notional = _money(fill_price * quantity)
    if active_order.action == TradeAction.BUY:
        cash_after = _money(cash - traded_notional - commission)
        position_after = position + quantity
    else:
        cash_after = _money(cash + traded_notional - commission)
        position_after = position - quantity
    return ResearchBacktestFill(
        symbol=request.symbol,
        order_id=active_order.order_id,
        action=active_order.action,
        quantity=quantity,
        signal_timestamp=active_order.signal.timestamp,
        fill_timestamp=fill_timestamp,
        signal_frame_index=active_order.signal.frame_index,
        fill_frame_index=fill_frame_index,
        reference_price=reference_price,
        limit_price=active_order.limit_price,
        fill_price=fill_price,
        commission=commission,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        tick_rounding_cost=tick_rounding_cost,
        traded_notional=traded_notional,
        cash_after=cash_after,
        position_after=position_after,
        partial_fill=quantity < active_order.remaining_quantity,
        available_quantity=available_quantity,
        cost_multiplier=cost_multiplier,
        reason=active_order.signal.reason,
    )


def _terminal_order(
    order: _ActiveOrder,
    *,
    timestamp: datetime,
    status: ResearchOrderStatus,
    canceled_reason: str | None = None,
) -> ResearchBacktestOrder:
    remaining = Decimal("0") if status == ResearchOrderStatus.FILLED else order.remaining_quantity
    filled = order.requested_quantity - remaining
    final_status = status
    if status == ResearchOrderStatus.CANCELED and filled > 0:
        final_status = ResearchOrderStatus.PARTIALLY_FILLED
    return ResearchBacktestOrder(
        order_id=order.order_id,
        action=order.action,
        requested_quantity=order.requested_quantity,
        filled_quantity=filled,
        remaining_quantity=remaining,
        submitted_timestamp=order.submitted_timestamp,
        submitted_frame_index=order.submitted_frame_index,
        limit_price=order.limit_price,
        status=final_status,
        completed_timestamp=timestamp,
        canceled_reason=canceled_reason,
    )


def _add_entry_fill(
    lot: _OpenLot | None,
    fill: ResearchBacktestFill,
) -> _OpenLot:
    if lot is None:
        return _OpenLot(
            quantity=fill.quantity,
            entry_timestamp=fill.fill_timestamp,
            entry_frame_index=fill.fill_frame_index,
            entry_price=fill.fill_price,
            entry_commission=fill.commission,
        )
    new_quantity = lot.quantity + fill.quantity
    lot.entry_price = _money(
        (lot.entry_price * lot.quantity + fill.fill_price * fill.quantity)
        / new_quantity
    )
    lot.quantity = new_quantity
    lot.entry_commission += fill.commission
    return lot


def _add_exit_fill(
    accumulator: _ExitAccumulator | None,
    fill: ResearchBacktestFill,
) -> _ExitAccumulator:
    if accumulator is None:
        return _ExitAccumulator(
            quantity=fill.quantity,
            exit_timestamp=fill.fill_timestamp,
            exit_frame_index=fill.fill_frame_index,
            exit_price=fill.fill_price,
            exit_commission=fill.commission,
            reason=fill.reason,
        )
    new_quantity = accumulator.quantity + fill.quantity
    accumulator.exit_price = _money(
        (accumulator.exit_price * accumulator.quantity + fill.fill_price * fill.quantity)
        / new_quantity
    )
    accumulator.quantity = new_quantity
    accumulator.exit_timestamp = fill.fill_timestamp
    accumulator.exit_frame_index = fill.fill_frame_index
    accumulator.exit_commission += fill.commission
    accumulator.reason = fill.reason
    return accumulator


def _close_trade(
    entry: _OpenLot,
    exit_lot: _ExitAccumulator,
) -> ResearchBacktestTrade:
    quantity = min(entry.quantity, exit_lot.quantity)
    gross_pnl = _money((exit_lot.exit_price - entry.entry_price) * quantity)
    net_pnl = _money(gross_pnl - entry.entry_commission - exit_lot.exit_commission)
    return ResearchBacktestTrade(
        symbol="SPY",
        quantity=quantity,
        entry_timestamp=entry.entry_timestamp,
        exit_timestamp=exit_lot.exit_timestamp,
        entry_price=entry.entry_price,
        exit_price=exit_lot.exit_price,
        entry_commission=entry.entry_commission,
        exit_commission=exit_lot.exit_commission,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        holding_bars=exit_lot.exit_frame_index - entry.entry_frame_index,
        profitable=net_pnl > 0,
        exit_reason=exit_lot.reason,
    )


def _actions_by_date(
    actions: list[ResearchCorporateAction],
) -> dict[date, list[ResearchCorporateAction]]:
    result: dict[date, list[ResearchCorporateAction]] = {}
    for action in actions:
        result.setdefault(date.fromisoformat(action.ex_date), []).append(action)
    return result


def _apply_capital_events(
    actions: list[ResearchCorporateAction],
    *,
    timestamp: datetime,
    cash: Decimal,
    position: Decimal,
    open_lot: _OpenLot | None,
    exit_accumulator: _ExitAccumulator | None,
) -> tuple[
    Decimal,
    Decimal,
    _OpenLot | None,
    _ExitAccumulator | None,
    list[ResearchCapitalEventRecord],
]:
    records: list[ResearchCapitalEventRecord] = []
    for action in actions:
        before = position
        cash_delta = Decimal("0")
        if action.action_type == "split":
            assert action.factor is not None
            position *= action.factor
            if open_lot is not None:
                open_lot.quantity *= action.factor
                open_lot.entry_price = _money(open_lot.entry_price / action.factor)
            if exit_accumulator is not None:
                exit_accumulator.quantity *= action.factor
                exit_accumulator.exit_price = _money(
                    exit_accumulator.exit_price / action.factor
                )
        elif action.action_type == "dividend":
            assert action.cash_amount is not None
            cash_delta = _money(position * action.cash_amount)
            cash += cash_delta
        records.append(
            ResearchCapitalEventRecord(
                action_type=action.action_type,
                ex_date=action.ex_date,
                timestamp=timestamp,
                factor=action.factor,
                cash_amount_per_share=action.cash_amount,
                quantity_before=before,
                quantity_after=position,
                cash_delta=cash_delta,
                revision=action.revision,
            )
        )
    return cash, position, open_lot, exit_accumulator, records


def _equity_point(
    bar: BacktestBar,
    *,
    frame_index: int,
    cash: Decimal,
    position: Decimal,
    peak_equity: Decimal,
) -> tuple[ResearchBacktestEquityPoint, Decimal]:
    position_value = _money(bar.close * position)
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


def _daily_returns(
    equity_curve: list[ResearchBacktestEquityPoint],
    starting_cash: Decimal,
) -> list[ResearchDailyReturn]:
    session_ends: dict[date, ResearchBacktestEquityPoint] = {}
    for point in equity_curve:
        session_ends[_session_date(point.timestamp)] = point
    previous_equity = starting_cash
    results: list[ResearchDailyReturn] = []
    for session_date, point in sorted(session_ends.items()):
        return_pct = (
            Decimal("0")
            if previous_equity == 0
            else _percent((point.equity / previous_equity - Decimal("1")) * Decimal("100"))
        )
        results.append(
            ResearchDailyReturn(
                session_date=session_date.isoformat(),
                ending_equity=point.equity,
                return_pct=return_pct,
            )
        )
        previous_equity = point.equity
    return results


def _metrics(
    bars: list[BacktestBar],
    benchmark_bars: list[BacktestBar],
    request: ResearchBacktestRequest,
    *,
    fills: list[ResearchBacktestFill],
    trades: list[ResearchBacktestTrade],
    equity_curve: list[ResearchBacktestEquityPoint],
    daily_returns: list[ResearchDailyReturn],
    signal_count: int,
    exposure_bars: int,
) -> ResearchBacktestMetrics:
    ending_equity = equity_curve[-1].equity
    ending_cash = equity_curve[-1].cash
    net_pnl = _money(ending_equity - request.starting_cash)
    commissions = _money(sum((fill.commission for fill in fills), Decimal("0")))
    spread_cost = _money(sum((fill.spread_cost for fill in fills), Decimal("0")))
    slippage_cost = _money(sum((fill.slippage_cost for fill in fills), Decimal("0")))
    tick_cost = _money(sum((fill.tick_rounding_cost for fill in fills), Decimal("0")))
    total_notional = _money(sum((fill.traded_notional for fill in fills), Decimal("0")))
    total_costs = commissions + spread_cost + slippage_cost + tick_cost
    winning = sum(1 for trade in trades if trade.profitable)
    closed_count = len(trades)
    benchmark_source = benchmark_bars or bars
    first_benchmark = benchmark_source[0].close
    benchmark_return = (
        Decimal("0")
        if first_benchmark <= 0
        else (benchmark_source[-1].close / first_benchmark - Decimal("1"))
        * Decimal("100")
    )
    total_return = _percent(net_pnl / request.starting_cash * Decimal("100"))
    max_drawdown = max(
        (point.drawdown_pct for point in equity_curve),
        default=Decimal("0"),
    )
    cagr, volatility, sharpe, sortino, calmar = _risk_adjusted_metrics(
        daily_returns,
        request=request,
        total_return_pct=total_return,
        max_drawdown_pct=max_drawdown,
    )
    drawdown_bars, drawdown_days = _drawdown_durations(equity_curve, daily_returns)
    return ResearchBacktestMetrics(
        starting_cash=request.starting_cash,
        ending_cash=ending_cash,
        ending_equity=ending_equity,
        gross_pnl_before_costs=_money(net_pnl + total_costs),
        net_pnl=net_pnl,
        total_return_pct=total_return,
        benchmark_return_pct=_percent(benchmark_return),
        max_drawdown_pct=max_drawdown,
        turnover_ratio=_percent(total_notional / request.starting_cash),
        total_traded_notional=total_notional,
        total_commissions=commissions,
        total_spread_cost=spread_cost,
        total_slippage_cost=slippage_cost,
        total_tick_rounding_cost=tick_cost,
        signal_count=signal_count,
        fill_count=len(fills),
        closed_trade_count=closed_count,
        winning_trade_count=winning,
        win_rate_pct=(
            Decimal("0")
            if closed_count == 0
            else _percent(Decimal(winning) / Decimal(closed_count) * Decimal("100"))
        ),
        exposure_pct=_percent(
            Decimal(exposure_bars) / Decimal(len(bars)) * Decimal("100")
        ),
        cagr_pct=cagr,
        annualized_volatility_pct=volatility,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        max_drawdown_duration_bars=drawdown_bars,
        max_drawdown_duration_days=drawdown_days,
        benchmark_relative_return_pct=_percent(total_return - benchmark_return),
        daily_observation_count=len(daily_returns),
    )


def _risk_adjusted_metrics(
    daily_returns: list[ResearchDailyReturn],
    *,
    request: ResearchBacktestRequest,
    total_return_pct: Decimal,
    max_drawdown_pct: Decimal,
) -> tuple[
    Decimal | None,
    Decimal | None,
    Decimal | None,
    Decimal | None,
    Decimal | None,
]:
    if len(daily_returns) < _MIN_ANNUALIZED_OBSERVATIONS:
        return None, None, None, None, None
    cagr: Decimal | None = None
    growth = Decimal("1") + total_return_pct / Decimal("100")
    if growth > 0:
        years = Decimal(len(daily_returns)) / Decimal(request.annualization_factor)
        cagr = _percent(
            Decimal(str(math.pow(float(growth), float(Decimal("1") / years))))
            * Decimal("100")
            - Decimal("100")
        )
    returns = [float(item.return_pct / Decimal("100")) for item in daily_returns]
    standard_deviation = statistics.stdev(returns)
    annual_sqrt = math.sqrt(request.annualization_factor)
    volatility = _percent(Decimal(str(standard_deviation * annual_sqrt * 100)))
    sharpe = (
        None
        if standard_deviation == 0
        else _ratio(Decimal(str(statistics.mean(returns) / standard_deviation * annual_sqrt)))
    )
    downside = [min(value, 0.0) for value in returns]
    downside_deviation = math.sqrt(sum(value * value for value in downside) / len(downside))
    sortino = (
        None
        if downside_deviation == 0
        else _ratio(
            Decimal(str(statistics.mean(returns) / downside_deviation * annual_sqrt))
        )
    )
    calmar = (
        None
        if cagr is None or max_drawdown_pct == 0
        else _ratio(cagr / max_drawdown_pct)
    )
    return cagr, volatility, sharpe, sortino, calmar


def _drawdown_durations(
    equity_curve: list[ResearchBacktestEquityPoint],
    daily_returns: list[ResearchDailyReturn],
) -> tuple[int, int]:
    current_bars = 0
    maximum_bars = 0
    for point in equity_curve:
        current_bars = current_bars + 1 if point.drawdown_pct > 0 else 0
        maximum_bars = max(maximum_bars, current_bars)
    peak = Decimal("0")
    current_days = 0
    maximum_days = 0
    for item in daily_returns:
        peak = max(peak, item.ending_equity)
        current_days = current_days + 1 if item.ending_equity < peak else 0
        maximum_days = max(maximum_days, current_days)
    return maximum_bars, maximum_days


def _validate_actions(actions: list[ResearchCorporateAction]) -> list[str]:
    errors: list[str] = []
    for action in actions:
        try:
            date.fromisoformat(action.ex_date)
        except ValueError:
            errors.append(f"invalid corporate-action ex-date: {action.ex_date}")
        if action.action_type not in {"split", "dividend"}:
            errors.append(f"unsupported corporate action: {action.action_type}")
        if action.action_type == "split" and action.factor is None:
            errors.append("split action is missing factor")
        if action.action_type == "dividend" and action.cash_amount is None:
            errors.append("dividend action is missing cash amount")
    return errors


def _is_session_end(bars: list[BacktestBar], index: int) -> bool:
    if index == len(bars) - 1:
        return True
    return _session_date(bars[index].timestamp) != _session_date(bars[index + 1].timestamp)


def _session_date(timestamp: datetime) -> date:
    return timestamp.astimezone(_EASTERN).date()


def _symbol_bars(feed: BacktestDataFeed | None, symbol: str) -> list[BacktestBar]:
    if feed is None:
        return []
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
    if bar.volume is None:
        return [f"SPY bar {bar.timestamp.isoformat()} is missing volume"]
    if bar.volume < 0:
        return [f"SPY bar {bar.timestamp.isoformat()} has negative volume"]
    return []


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _percent(value: Decimal) -> Decimal:
    return value.quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


def _ratio(value: Decimal) -> Decimal:
    return value.quantize(_RATIO_QUANTUM, rounding=ROUND_HALF_UP)

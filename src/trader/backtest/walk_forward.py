"""Broker-free SPY walk-forward selection and sealed-holdout evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from trader.backtest.data_adapter import summarize_backtest_feed
from trader.backtest.research import build_research_backtest_report
from trader.models import (
    BacktestBar,
    BacktestDataFeed,
    BacktestFeedStatus,
    ResearchBacktestReport,
    ResearchBacktestRequest,
    ResearchCandidateTrial,
    ResearchWalkForwardFold,
    ResearchWalkForwardReport,
    ResearchWalkForwardRequest,
    ResearchWalkForwardStatus,
    ResearchWalkForwardSummary,
    ResearchWindowCandidate,
)

_PERCENT_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class _TrialExecution:
    trial: ResearchCandidateTrial
    report: ResearchBacktestReport


def parse_research_candidates(raw: str) -> list[ResearchWindowCandidate]:
    """Parse a predeclared comma-separated short:long candidate grid."""

    candidates: list[ResearchWindowCandidate] = []
    for item in raw.split(","):
        chunk = item.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(f"research candidate must use short:long format: {chunk}")
        short_raw, long_raw = chunk.split(":", 1)
        candidates.append(
            ResearchWindowCandidate(
                short_window=int(short_raw.strip()),
                long_window=int(long_raw.strip()),
            )
        )
    if not candidates:
        raise ValueError("at least one research candidate is required")
    pairs = [(candidate.short_window, candidate.long_window) for candidate in candidates]
    if len(pairs) != len(set(pairs)):
        raise ValueError("research candidates must be unique")
    return candidates


def build_research_walk_forward_report(
    feed: BacktestDataFeed,
    request: ResearchWalkForwardRequest,
) -> ResearchWalkForwardReport:
    """Run anchored folds, select on development data, then touch holdout once."""

    warnings = list(feed.warnings)
    errors = list(feed.errors)
    bars = _symbol_bars(feed, request.symbol)
    if feed.feed_status != BacktestFeedStatus.READY:
        errors.append("source feed status must be ready")
    if feed.symbols != [request.symbol]:
        errors.append("walk-forward research requires a SPY-only feed")
    if len(bars) != len(feed.frames):
        errors.append("every walk-forward frame must contain one SPY bar")

    required_bars = (
        request.minimum_train_bars
        + request.fold_count * request.validation_bars
        + request.holdout_bars
    )
    if len(bars) < required_bars:
        errors.append(
            f"SPY bars observed {len(bars)}; expected at least {required_bars} "
            "for train, validation folds, and holdout"
        )
    if errors:
        return _failed_report(feed, request, warnings=warnings, errors=errors)

    holdout_start = len(bars) - request.holdout_bars
    initial_train_end = holdout_start - request.fold_count * request.validation_bars
    development_bars = bars[:holdout_start]
    holdout_bars = bars[holdout_start:]
    dataset_fingerprint = _bars_fingerprint(bars)
    development_fingerprint = _bars_fingerprint(development_bars)
    holdout_fingerprint = _bars_fingerprint(holdout_bars)
    candidate_spec_fingerprint = _candidate_spec_fingerprint(request)

    folds: list[ResearchWalkForwardFold] = []
    for fold_offset in range(request.fold_count):
        fold_index = fold_offset + 1
        train_end = initial_train_end + fold_offset * request.validation_bars
        validation_start = train_end
        validation_end = validation_start + request.validation_bars
        training_executions = [
            _run_trial(
                feed,
                request,
                candidate,
                start=0,
                end=train_end,
                phase="fold_train",
                fold_index=fold_index,
            )
            for candidate in request.candidates
        ]
        selected_training = _select_trial(training_executions)
        if selected_training is None:
            fold_error = "no eligible training candidate"
            folds.append(
                _fold(
                    bars,
                    fold_index=fold_index,
                    train_end=train_end,
                    validation_start=validation_start,
                    validation_end=validation_end,
                    training_executions=training_executions,
                    validation_execution=None,
                    errors=[fold_error],
                )
            )
            errors.append(f"fold {fold_index}: {fold_error}")
            break

        validation_execution = _run_trial(
            feed,
            request,
            selected_training.trial.candidate,
            start=validation_start,
            end=validation_end,
            phase="fold_validation",
            fold_index=fold_index,
        )
        fold_errors = [] if validation_execution.trial.eligible else [
            "selected candidate did not pass next-period validation eligibility"
        ]
        folds.append(
            _fold(
                bars,
                fold_index=fold_index,
                train_end=train_end,
                validation_start=validation_start,
                validation_end=validation_end,
                training_executions=training_executions,
                validation_execution=validation_execution,
                errors=fold_errors,
            )
        )
        if fold_errors:
            errors.append(f"fold {fold_index}: {fold_errors[0]}")
            break

    walk_forward_summary = _walk_forward_summary(folds)
    if errors or len(folds) != request.fold_count:
        return ResearchWalkForwardReport(
            ok=False,
            request=request,
            feed_summary=summarize_backtest_feed(feed),
            dataset_fingerprint=dataset_fingerprint,
            development_fingerprint=development_fingerprint,
            holdout_fingerprint=holdout_fingerprint,
            candidate_spec_fingerprint=candidate_spec_fingerprint,
            development_bar_count=len(development_bars),
            holdout_bar_count=len(holdout_bars),
            folds=folds,
            walk_forward_summary=walk_forward_summary,
            holdout_partition_sealed_before_selection=True,
            warnings=list(dict.fromkeys(warnings)),
            errors=list(dict.fromkeys(errors)),
            final_status=ResearchWalkForwardStatus.FAILED,
        )

    development_executions = [
        _run_trial(
            feed,
            request,
            candidate,
            start=0,
            end=holdout_start,
            phase="full_development",
            fold_index=None,
        )
        for candidate in request.candidates
    ]
    selected_development = _select_trial(development_executions)
    if selected_development is None:
        errors.append("no eligible candidate on full development segment")
        return ResearchWalkForwardReport(
            ok=False,
            request=request,
            feed_summary=summarize_backtest_feed(feed),
            dataset_fingerprint=dataset_fingerprint,
            development_fingerprint=development_fingerprint,
            holdout_fingerprint=holdout_fingerprint,
            candidate_spec_fingerprint=candidate_spec_fingerprint,
            development_bar_count=len(development_bars),
            holdout_bar_count=len(holdout_bars),
            folds=folds,
            walk_forward_summary=walk_forward_summary,
            full_development_trials=[item.trial for item in development_executions],
            walk_forward_completed=True,
            holdout_partition_sealed_before_selection=True,
            warnings=list(dict.fromkeys(warnings)),
            errors=list(dict.fromkeys(errors)),
            final_status=ResearchWalkForwardStatus.FAILED,
        )

    # This is the only point where holdout bars enter a strategy evaluation.
    holdout_execution = _run_trial(
        feed,
        request,
        selected_development.trial.candidate,
        start=holdout_start,
        end=len(bars),
        phase="sealed_holdout",
        fold_index=None,
    )
    if not holdout_execution.trial.eligible:
        errors.append("sealed holdout did not meet research eligibility requirements")
    warnings.append(
        "Logical holdout isolation is enforced within this report, but operator reruns "
        "cannot be prevented; results remain non-promoting"
    )
    completed = not errors
    return ResearchWalkForwardReport(
        ok=completed,
        request=request,
        feed_summary=summarize_backtest_feed(feed),
        dataset_fingerprint=dataset_fingerprint,
        development_fingerprint=development_fingerprint,
        holdout_fingerprint=holdout_fingerprint,
        candidate_spec_fingerprint=candidate_spec_fingerprint,
        development_bar_count=len(development_bars),
        holdout_bar_count=len(holdout_bars),
        folds=folds,
        walk_forward_summary=walk_forward_summary,
        full_development_trials=[item.trial for item in development_executions],
        selected_candidate=selected_development.trial.candidate,
        selected_development_score=selected_development.trial.selection_score,
        holdout_trial=holdout_execution.trial,
        holdout_report=holdout_execution.report,
        walk_forward_completed=True,
        holdout_partition_sealed_before_selection=True,
        holdout_evaluation_count=1,
        sealed_holdout_completed=holdout_execution.report.ok,
        research_validation_completed=completed,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
        final_status=(
            ResearchWalkForwardStatus.COMPLETED
            if completed
            else ResearchWalkForwardStatus.FAILED
        ),
    )


def _run_trial(
    feed: BacktestDataFeed,
    request: ResearchWalkForwardRequest,
    candidate: ResearchWindowCandidate,
    *,
    start: int,
    end: int,
    phase: str,
    fold_index: int | None,
) -> _TrialExecution:
    warmup_start = 0 if start == 0 else max(0, start - candidate.long_window - 1)
    segment_feed = _slice_feed(feed, warmup_start, end)
    evaluation_start_index = start - warmup_start
    backtest_request = ResearchBacktestRequest(
        symbol=request.symbol,
        short_window=candidate.short_window,
        long_window=candidate.long_window,
        quantity=request.quantity,
        starting_cash=request.starting_cash,
        spread_bps=request.spread_bps,
        slippage_bps=request.slippage_bps,
        commission_per_share=request.commission_per_share,
        minimum_commission=request.minimum_commission,
        force_close_at_end=True,
        requested_bar_size=request.requested_bar_size,
        requested_what_to_show=request.requested_what_to_show,
        latest=request.latest,
        snapshot_timestamp=request.snapshot_timestamp,
        strict=request.strict,
        base_data_path=request.base_data_path,
    )
    report = build_research_backtest_report(
        segment_feed,
        backtest_request,
        evaluation_start_index=evaluation_start_index,
    )
    metrics = report.metrics
    closed_trades = metrics.closed_trade_count if metrics is not None else 0
    eligible = bool(
        report.ok
        and metrics is not None
        and closed_trades >= request.minimum_closed_trades
    )
    errors = list(report.errors)
    if report.ok and closed_trades < request.minimum_closed_trades:
        errors.append(
            f"closed trades {closed_trades}; expected at least "
            f"{request.minimum_closed_trades}"
        )
    score = None
    if eligible and metrics is not None:
        score = _percent(
            metrics.total_return_pct
            - request.drawdown_penalty * metrics.max_drawdown_pct
        )
    bars = _symbol_bars(feed, request.symbol)
    trial = ResearchCandidateTrial(
        phase=phase,
        fold_index=fold_index,
        candidate=candidate,
        segment_start=bars[start].timestamp,
        segment_end=bars[end - 1].timestamp,
        bar_count=end - start,
        eligible=eligible,
        selection_score=score,
        net_pnl=metrics.net_pnl if metrics is not None else None,
        total_return_pct=metrics.total_return_pct if metrics is not None else None,
        max_drawdown_pct=metrics.max_drawdown_pct if metrics is not None else None,
        closed_trade_count=closed_trades,
        fill_count=metrics.fill_count if metrics is not None else 0,
        final_status=report.final_status,
        warnings=report.warnings,
        errors=list(dict.fromkeys(errors)),
    )
    return _TrialExecution(trial=trial, report=report)


def _fold(
    bars: list[BacktestBar],
    *,
    fold_index: int,
    train_end: int,
    validation_start: int,
    validation_end: int,
    training_executions: list[_TrialExecution],
    validation_execution: _TrialExecution | None,
    errors: list[str],
) -> ResearchWalkForwardFold:
    selected = _select_trial(training_executions)
    return ResearchWalkForwardFold(
        fold_index=fold_index,
        train_start=bars[0].timestamp,
        train_end=bars[train_end - 1].timestamp,
        train_bar_count=train_end,
        validation_start=bars[validation_start].timestamp,
        validation_end=bars[validation_end - 1].timestamp,
        validation_bar_count=validation_end - validation_start,
        training_trials=[item.trial for item in training_executions],
        selected_candidate=selected.trial.candidate if selected is not None else None,
        selected_training_score=(
            selected.trial.selection_score if selected is not None else None
        ),
        validation_trial=(
            validation_execution.trial if validation_execution is not None else None
        ),
        ok=not errors,
        errors=errors,
    )


def _select_trial(executions: list[_TrialExecution]) -> _TrialExecution | None:
    eligible = [
        item
        for item in executions
        if item.trial.eligible and item.trial.selection_score is not None
    ]
    return max(eligible, key=_selection_score) if eligible else None


def _selection_score(execution: _TrialExecution) -> Decimal:
    score = execution.trial.selection_score
    assert score is not None
    return score


def _walk_forward_summary(
    folds: list[ResearchWalkForwardFold],
) -> ResearchWalkForwardSummary:
    completed = [
        fold
        for fold in folds
        if fold.ok
        and fold.selected_candidate is not None
        and fold.validation_trial is not None
        and fold.validation_trial.total_return_pct is not None
    ]
    growth = Decimal("1")
    worst_drawdown = Decimal("0")
    total_trades = 0
    selected_candidates: list[ResearchWindowCandidate] = []
    for fold in completed:
        trial = fold.validation_trial
        assert trial is not None
        assert trial.total_return_pct is not None
        growth *= Decimal("1") + trial.total_return_pct / Decimal("100")
        worst_drawdown = max(worst_drawdown, trial.max_drawdown_pct or Decimal("0"))
        total_trades += trial.closed_trade_count
        assert fold.selected_candidate is not None
        selected_candidates.append(fold.selected_candidate)
    unique = {
        (candidate.short_window, candidate.long_window)
        for candidate in selected_candidates
    }
    return ResearchWalkForwardSummary(
        completed_fold_count=len(completed),
        selected_candidates=selected_candidates,
        unique_selected_candidate_count=len(unique),
        compounded_validation_return_pct=(
            _percent((growth - Decimal("1")) * Decimal("100"))
            if completed
            else None
        ),
        worst_validation_drawdown_pct=worst_drawdown if completed else None,
        total_validation_closed_trades=total_trades,
    )


def _slice_feed(feed: BacktestDataFeed, start: int, end: int) -> BacktestDataFeed:
    frames = feed.frames[start:end]
    return feed.model_copy(
        update={
            "frames": frames,
            "total_bars": sum(
                1
                for frame in frames
                for bar in frame.bars_by_symbol.values()
                if bar is not None
            ),
            "frame_count": len(frames),
            "first_timestamp": frames[0].timestamp if frames else None,
            "last_timestamp": frames[-1].timestamp if frames else None,
            "missing_bars_by_symbol": {
                symbol: sum(1 for frame in frames if symbol in frame.missing_symbols)
                for symbol in feed.symbols
            },
        }
    )


def _symbol_bars(feed: BacktestDataFeed, symbol: str) -> list[BacktestBar]:
    return [
        bar
        for frame in feed.frames
        if (bar := frame.bars_by_symbol.get(symbol)) is not None
    ]


def _bars_fingerprint(bars: list[BacktestBar]) -> str:
    digest = hashlib.sha256()
    for bar in bars:
        record = "|".join(
            [
                bar.symbol,
                bar.timestamp.isoformat(),
                str(bar.open),
                str(bar.high),
                str(bar.low),
                str(bar.close),
                str(bar.volume),
            ]
        )
        digest.update(record.encode("utf-8"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def _candidate_spec_fingerprint(request: ResearchWalkForwardRequest) -> str:
    payload = request.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _failed_report(
    feed: BacktestDataFeed,
    request: ResearchWalkForwardRequest,
    *,
    warnings: list[str],
    errors: list[str],
) -> ResearchWalkForwardReport:
    return ResearchWalkForwardReport(
        ok=False,
        request=request,
        feed_summary=summarize_backtest_feed(feed),
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
        final_status=ResearchWalkForwardStatus.FAILED,
    )


def _percent(value: Decimal) -> Decimal:
    return value.quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)

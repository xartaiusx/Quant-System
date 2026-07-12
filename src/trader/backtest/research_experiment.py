"""Preregistered, catalog-only SPY experiment governance."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from statistics import NormalDist
from uuid import uuid4

from trader.backtest.research import build_research_backtest_report
from trader.data.research_catalog import load_research_catalog
from trader.data.research_store import CATALOG_RELATIVE_PATH, initialize_research_store
from trader.models import (
    BacktestDataFeed,
    ResearchBacktestReport,
    ResearchBacktestRequest,
    ResearchCatalogLoadReport,
    ResearchCatalogLoadRequest,
    ResearchExperimentCandidateResult,
    ResearchExperimentPhase,
    ResearchExperimentReport,
    ResearchExperimentRequest,
    ResearchExperimentSpec,
    ResearchExperimentValidationFold,
    ResearchStatisticalDiagnostics,
    ResearchWindowCandidate,
)

_PERCENT_QUANTUM = Decimal("0.0001")
_PROBABILITY_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class _CatalogBundle:
    signal: ResearchCatalogLoadReport
    execution: ResearchCatalogLoadReport
    benchmark: ResearchCatalogLoadReport

    @property
    def ok(self) -> bool:
        fingerprints = {
            item.action_fingerprint
            for item in (self.signal, self.execution, self.benchmark)
            if item.action_fingerprint is not None
        }
        return all(
            item.ok for item in (self.signal, self.execution, self.benchmark)
        ) and len(fingerprints) == 1

    @property
    def errors(self) -> list[str]:
        values = [
            error
            for item in (self.signal, self.execution, self.benchmark)
            for error in item.errors
        ]
        fingerprints = {
            item.action_fingerprint
            for item in (self.signal, self.execution, self.benchmark)
            if item.action_fingerprint is not None
        }
        if len(fingerprints) != 1:
            values.append("catalog action fingerprints differ across research views")
        return list(dict.fromkeys(values))


@dataclass(frozen=True)
class _DevelopmentResult:
    folds: list[ResearchExperimentValidationFold]
    candidates: list[ResearchExperimentCandidateResult]
    selected: ResearchWindowCandidate | None
    positive_years: int
    aggregate_base_return: Decimal | None
    aggregate_two_x_return: Decimal | None
    errors: list[str]


def run_research_experiment(
    request: ResearchExperimentRequest,
    *,
    require_spec_tracked: bool = True,
) -> ResearchExperimentReport:
    """Run development or consume one explicitly confirmed final holdout."""

    spec_path = Path(request.spec_path).expanduser().resolve()
    root = Path(request.root_path).expanduser().resolve()
    warnings = [
        "Research experiment is offline, broker-free, and never promotes execution"
    ]
    errors: list[str] = []
    spec: ResearchExperimentSpec | None = None
    spec_fingerprint: str | None = None
    commit_sha, spec_tracked = _git_evidence(spec_path)
    if require_spec_tracked and not spec_tracked:
        errors.append(
            "experiment specification must be committed to Git and match HEAD before use"
        )
    try:
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
        spec = ResearchExperimentSpec.model_validate(payload)
        spec_fingerprint = _fingerprint(spec.model_dump(mode="json"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"experiment specification failed validation: {exc}")
    catalog_path = root / CATALOG_RELATIVE_PATH
    if spec is not None and spec_fingerprint is not None and not errors:
        try:
            catalog_path = initialize_research_store(root)
            _register_spec(catalog_path, spec, spec_fingerprint)
        except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
            errors.append(f"experiment registration failed: {exc}")
    if spec is None or spec_fingerprint is None or errors:
        return _report(
            request,
            spec=spec,
            spec_path=spec_path,
            spec_fingerprint=spec_fingerprint,
            spec_tracked=spec_tracked,
            commit_sha=commit_sha,
            catalog_path=catalog_path,
            warnings=warnings,
            errors=errors,
        )

    development_bundle = _load_bundle(
        root,
        start=spec.training_start,
        end=f"{spec.validation_years[-1]}-12-31",
    )
    if not development_bundle.ok:
        errors.extend(development_bundle.errors)
        return _report(
            request,
            spec=spec,
            spec_path=spec_path,
            spec_fingerprint=spec_fingerprint,
            spec_tracked=spec_tracked,
            commit_sha=commit_sha,
            catalog_path=catalog_path,
            bundle=development_bundle,
            warnings=warnings,
            errors=errors,
        )
    development = _run_development(development_bundle, spec)
    errors.extend(development.errors)
    if request.phase == ResearchExperimentPhase.DEVELOPMENT or errors:
        completed = not errors and development.selected is not None
        run_id = _record_run(
            catalog_path,
            spec.experiment_id,
            phase=str(request.phase),
            dataset_fingerprint=development_bundle.signal.dataset_fingerprint or "unknown",
            status="completed" if completed else "failed",
        )
        return _report(
            request,
            spec=spec,
            spec_path=spec_path,
            spec_fingerprint=spec_fingerprint,
            spec_tracked=spec_tracked,
            commit_sha=commit_sha,
            catalog_path=catalog_path,
            bundle=development_bundle,
            development=development,
            run_id=run_id,
            warnings=warnings,
            errors=errors,
        )

    assert development.selected is not None
    if request.confirmation != spec.final_holdout_confirmation:
        errors.append(
            "final holdout requires the exact preregistered confirmation string"
        )
        return _report(
            request,
            spec=spec,
            spec_path=spec_path,
            spec_fingerprint=spec_fingerprint,
            spec_tracked=spec_tracked,
            commit_sha=commit_sha,
            catalog_path=catalog_path,
            bundle=development_bundle,
            development=development,
            warnings=warnings,
            errors=errors,
        )
    holdout_access_fingerprint = _fingerprint(
        {
            "experiment_id": spec.experiment_id,
            "holdout_start": spec.holdout_start,
            "holdout_end": spec.holdout_end,
            "spec_fingerprint": spec_fingerprint,
        }
    )
    try:
        _record_holdout_access(
            catalog_path,
            spec,
            holdout_access_fingerprint,
            request.confirmation,
        )
    except (sqlite3.Error, ValueError) as exc:
        errors.append(f"final holdout is already consumed or unavailable: {exc}")
        return _report(
            request,
            spec=spec,
            spec_path=spec_path,
            spec_fingerprint=spec_fingerprint,
            spec_tracked=spec_tracked,
            commit_sha=commit_sha,
            catalog_path=catalog_path,
            bundle=development_bundle,
            development=development,
            holdout_consumed=True,
            warnings=warnings,
            errors=errors,
        )

    holdout_bundle = _load_bundle(
        root,
        start=spec.holdout_start,
        end=spec.holdout_end,
    )
    if not holdout_bundle.ok:
        errors.extend(holdout_bundle.errors)
        return _report(
            request,
            spec=spec,
            spec_path=spec_path,
            spec_fingerprint=spec_fingerprint,
            spec_tracked=spec_tracked,
            commit_sha=commit_sha,
            catalog_path=catalog_path,
            bundle=holdout_bundle,
            development=development,
            holdout_recorded=True,
            holdout_consumed=True,
            warnings=warnings,
            errors=errors,
        )
    holdout_report = _run_period(
        holdout_bundle,
        spec,
        development.selected,
        start=spec.holdout_start,
        end=spec.holdout_end,
    )
    holdout_result = _compact_result(
        holdout_report,
        development.selected,
        period_start=spec.holdout_start,
        period_end=spec.holdout_end,
        minimum_closed_trades=spec.minimum_closed_trades,
    )
    if not holdout_result.eligible:
        errors.extend(holdout_result.errors or ["final holdout is not eligible"])
    diagnostics = _deflated_sharpe_diagnostics(
        development.candidates,
        holdout_result,
    )
    benchmark_drawdown = _benchmark_drawdown(holdout_bundle.benchmark.feed)
    validation_gate = (
        development.positive_years >= spec.required_positive_validation_years
    )
    two_x_gate = bool(
        development.aggregate_two_x_return is not None
        and development.aggregate_two_x_return >= 0
    )
    holdout_return_gate = bool(
        holdout_result.base_return_pct is not None
        and holdout_result.base_return_pct > 0
    )
    dsr_gate = bool(
        diagnostics.deflated_sharpe_probability is not None
        and diagnostics.deflated_sharpe_probability >= spec.minimum_dsr_probability
    )
    holdout_drawdown_gate = bool(
        holdout_result.max_drawdown_pct is not None
        and benchmark_drawdown is not None
        and holdout_result.max_drawdown_pct <= benchmark_drawdown
    )
    review_ready = all(
        (
            validation_gate,
            two_x_gate,
            holdout_return_gate,
            dsr_gate,
            holdout_drawdown_gate,
            holdout_result.eligible,
        )
    )
    run_id = _record_run(
        catalog_path,
        spec.experiment_id,
        phase=str(request.phase),
        dataset_fingerprint=holdout_bundle.signal.dataset_fingerprint or "unknown",
        status="completed" if holdout_result.eligible else "failed",
    )
    return _report(
        request,
        spec=spec,
        spec_path=spec_path,
        spec_fingerprint=spec_fingerprint,
        spec_tracked=spec_tracked,
        commit_sha=commit_sha,
        catalog_path=catalog_path,
        bundle=holdout_bundle,
        development=development,
        holdout_result=holdout_result,
        holdout_recorded=True,
        holdout_consumed=True,
        diagnostics=diagnostics,
        benchmark_drawdown=benchmark_drawdown,
        validation_gate=validation_gate,
        two_x_gate=two_x_gate,
        holdout_return_gate=holdout_return_gate,
        dsr_gate=dsr_gate,
        holdout_drawdown_gate=holdout_drawdown_gate,
        review_ready=review_ready,
        run_id=run_id,
        warnings=warnings,
        errors=errors,
    )


def _run_development(
    bundle: _CatalogBundle,
    spec: ResearchExperimentSpec,
) -> _DevelopmentResult:
    folds: list[ResearchExperimentValidationFold] = []
    errors: list[str] = []
    for year in spec.validation_years:
        training_end = f"{year - 1}-12-31"
        training_results = [
            _compact_result(
                _run_period(
                    bundle,
                    spec,
                    candidate,
                    start=spec.training_start,
                    end=training_end,
                ),
                candidate,
                period_start=spec.training_start,
                period_end=training_end,
                minimum_closed_trades=spec.minimum_closed_trades,
            )
            for candidate in spec.candidates
        ]
        selected_result = _select_candidate(training_results)
        fold_errors: list[str] = []
        validation_result: ResearchExperimentCandidateResult | None = None
        selected_candidate = (
            selected_result.candidate if selected_result is not None else None
        )
        if selected_candidate is None:
            fold_errors.append("no eligible training candidate")
        else:
            validation_result = _compact_result(
                _run_period(
                    bundle,
                    spec,
                    selected_candidate,
                    start=f"{year}-01-01",
                    end=f"{year}-12-31",
                ),
                selected_candidate,
                period_start=f"{year}-01-01",
                period_end=f"{year}-12-31",
                minimum_closed_trades=spec.minimum_closed_trades,
            )
            if not validation_result.eligible:
                fold_errors.append("selected candidate failed validation-year eligibility")
        folds.append(
            ResearchExperimentValidationFold(
                validation_year=year,
                training_start=spec.training_start,
                training_end=training_end,
                validation_start=f"{year}-01-01",
                validation_end=f"{year}-12-31",
                training_candidates=training_results,
                selected_candidate=selected_candidate,
                validation_result=validation_result,
                ok=not fold_errors,
                errors=fold_errors,
            )
        )
        errors.extend(f"validation {year}: {error}" for error in fold_errors)

    development_end = f"{spec.validation_years[-1]}-12-31"
    candidates = [
        _compact_result(
            _run_period(
                bundle,
                spec,
                candidate,
                start=spec.training_start,
                end=development_end,
            ),
            candidate,
            period_start=spec.training_start,
            period_end=development_end,
            minimum_closed_trades=spec.minimum_closed_trades,
        )
        for candidate in spec.candidates
    ]
    selected_result = _select_candidate(candidates)
    if selected_result is None:
        errors.append("no eligible full-development candidate")
    validation_results = [
        fold.validation_result
        for fold in folds
        if fold.validation_result is not None
    ]
    positive_years = sum(
        1
        for result in validation_results
        if result.base_return_pct is not None and result.base_return_pct > 0
    )
    return _DevelopmentResult(
        folds=folds,
        candidates=candidates,
        selected=selected_result.candidate if selected_result is not None else None,
        positive_years=positive_years,
        aggregate_base_return=_compound_returns(
            [result.base_return_pct for result in validation_results]
        ),
        aggregate_two_x_return=_compound_returns(
            [result.two_x_cost_return_pct for result in validation_results]
        ),
        errors=list(dict.fromkeys(errors)),
    )


def _run_period(
    bundle: _CatalogBundle,
    spec: ResearchExperimentSpec,
    candidate: ResearchWindowCandidate,
    *,
    start: str,
    end: str,
) -> ResearchBacktestReport:
    assert bundle.signal.feed is not None
    assert bundle.execution.feed is not None
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    indices = [
        index
        for index, frame in enumerate(bundle.signal.feed.frames)
        if start_date <= frame.timestamp.date() <= end_date
    ]
    if not indices:
        return build_research_backtest_report(
            _empty_slice(bundle.signal.feed),
            _backtest_request(spec, candidate),
        )
    first = indices[0]
    last = indices[-1] + 1
    warmup_start = max(0, first - candidate.long_window - 1)
    signal_feed = _slice_feed(bundle.signal.feed, warmup_start, last)
    execution_feed = _slice_feed(bundle.execution.feed, warmup_start, last)
    benchmark_feed = _slice_feed_by_date(bundle.benchmark.feed, start_date, end_date)
    return build_research_backtest_report(
        signal_feed,
        _backtest_request(spec, candidate),
        execution_feed=execution_feed,
        benchmark_feed=benchmark_feed,
        corporate_actions=bundle.signal.corporate_actions,
        evaluation_start_index=first - warmup_start,
    )


def _backtest_request(
    spec: ResearchExperimentSpec,
    candidate: ResearchWindowCandidate,
) -> ResearchBacktestRequest:
    return ResearchBacktestRequest(
        symbol=spec.symbol,
        short_window=candidate.short_window,
        long_window=candidate.long_window,
        sizing_mode=spec.sizing_mode,
        quantity=spec.quantity,
        target_allocation_pct=spec.target_allocation_pct,
        starting_cash=spec.starting_cash,
        spread_bps=spec.spread_bps,
        slippage_bps=spec.slippage_bps,
        commission_per_share=spec.commission_per_share,
        minimum_commission=spec.minimum_commission,
        tick_size=spec.tick_size,
        limit_buffer_bps=spec.limit_buffer_bps,
        max_volume_participation=spec.max_volume_participation,
        force_close_at_end=True,
    )


def _compact_result(
    report: ResearchBacktestReport,
    candidate: ResearchWindowCandidate,
    *,
    period_start: str,
    period_end: str,
    minimum_closed_trades: int,
) -> ResearchExperimentCandidateResult:
    metrics = report.metrics
    two_x = next(
        (item.metrics for item in report.cost_scenarios if item.multiplier == Decimal("2")),
        None,
    )
    closed_trades = metrics.closed_trade_count if metrics is not None else 0
    eligible = bool(report.ok and metrics and closed_trades >= minimum_closed_trades)
    errors = list(report.errors)
    if report.ok and closed_trades < minimum_closed_trades:
        errors.append(
            f"closed trades {closed_trades}; expected at least {minimum_closed_trades}"
        )
    score = (
        metrics.total_return_pct - metrics.max_drawdown_pct
        if eligible and metrics is not None
        else None
    )
    return ResearchExperimentCandidateResult(
        candidate=candidate,
        period_start=period_start,
        period_end=period_end,
        eligible=eligible,
        selection_score=_percent(score) if score is not None else None,
        base_return_pct=metrics.total_return_pct if metrics else None,
        two_x_cost_return_pct=two_x.total_return_pct if two_x else None,
        max_drawdown_pct=metrics.max_drawdown_pct if metrics else None,
        benchmark_return_pct=metrics.benchmark_return_pct if metrics else None,
        closed_trade_count=closed_trades,
        sharpe_ratio=metrics.sharpe_ratio if metrics else None,
        daily_returns_pct=[item.return_pct for item in report.daily_returns],
        errors=list(dict.fromkeys(errors)),
    )


def _select_candidate(
    candidates: list[ResearchExperimentCandidateResult],
) -> ResearchExperimentCandidateResult | None:
    eligible = [
        item for item in candidates if item.eligible and item.selection_score is not None
    ]
    return max(eligible, key=lambda item: item.selection_score or Decimal("-Infinity")) \
        if eligible else None


def _deflated_sharpe_diagnostics(
    trials: list[ResearchExperimentCandidateResult],
    holdout: ResearchExperimentCandidateResult,
) -> ResearchStatisticalDiagnostics:
    reasons = [
        "PBO requires a preregistered CSCV path matrix; annual folds alone are insufficient"
    ]
    holdout_returns = [float(item / Decimal("100")) for item in holdout.daily_returns_pct]
    trial_sharpes = [
        value
        for item in trials
        if (value := _daily_sharpe(item.daily_returns_pct)) is not None
    ]
    if len(holdout_returns) < 30:
        reasons.append("Deflated Sharpe requires at least 30 holdout daily observations")
    if len(trial_sharpes) < 2:
        reasons.append("Deflated Sharpe requires at least two valid candidate trials")
    if len(holdout_returns) < 30 or len(trial_sharpes) < 2:
        return ResearchStatisticalDiagnostics(
            trial_count=len(trials),
            holdout_observation_count=len(holdout_returns),
            unavailable_reasons=reasons,
        )
    trial_std = statistics.stdev(trial_sharpes)
    if trial_std == 0:
        reasons.append("Deflated Sharpe is undefined because trial Sharpe variance is zero")
        return ResearchStatisticalDiagnostics(
            trial_count=len(trials),
            holdout_observation_count=len(holdout_returns),
            unavailable_reasons=reasons,
        )
    normal = NormalDist()
    trial_count = len(trial_sharpes)
    euler_gamma = 0.5772156649015329
    expected_maximum = trial_std * (
        (1 - euler_gamma) * normal.inv_cdf(1 - 1 / trial_count)
        + euler_gamma * normal.inv_cdf(1 - 1 / (trial_count * math.e))
    )
    mean = statistics.mean(holdout_returns)
    sample_std = statistics.stdev(holdout_returns)
    if sample_std == 0:
        reasons.append("Deflated Sharpe is undefined because holdout variance is zero")
        return ResearchStatisticalDiagnostics(
            trial_count=len(trials),
            holdout_observation_count=len(holdout_returns),
            unavailable_reasons=reasons,
        )
    sharpe = mean / sample_std
    population_std = statistics.pstdev(holdout_returns)
    skewness = sum(
        ((value - mean) / population_std) ** 3 for value in holdout_returns
    ) / len(holdout_returns)
    kurtosis = sum(
        ((value - mean) / population_std) ** 4 for value in holdout_returns
    ) / len(holdout_returns)
    denominator_squared = (
        1 - skewness * sharpe + ((kurtosis - 1) / 4) * sharpe * sharpe
    )
    if denominator_squared <= 0:
        reasons.append("Deflated Sharpe denominator is not positive")
        return ResearchStatisticalDiagnostics(
            trial_count=len(trials),
            holdout_observation_count=len(holdout_returns),
            unavailable_reasons=reasons,
        )
    z_score = (
        (sharpe - expected_maximum)
        * math.sqrt(len(holdout_returns) - 1)
        / math.sqrt(denominator_squared)
    )
    probability = normal.cdf(z_score)
    return ResearchStatisticalDiagnostics(
        trial_count=len(trials),
        holdout_observation_count=len(holdout_returns),
        deflated_sharpe_available=True,
        deflated_sharpe_probability=Decimal(str(probability)).quantize(
            _PROBABILITY_QUANTUM,
            rounding=ROUND_HALF_UP,
        ),
        deflated_sharpe_threshold=Decimal(str(expected_maximum)).quantize(
            _PROBABILITY_QUANTUM,
            rounding=ROUND_HALF_UP,
        ),
        unavailable_reasons=reasons,
    )


def _daily_sharpe(returns_pct: list[Decimal]) -> float | None:
    if len(returns_pct) < 2:
        return None
    values = [float(value / Decimal("100")) for value in returns_pct]
    deviation = statistics.stdev(values)
    return statistics.mean(values) / deviation if deviation else None


def _benchmark_drawdown(feed: BacktestDataFeed | None) -> Decimal | None:
    if feed is None:
        return None
    peak = Decimal("0")
    maximum = Decimal("0")
    for frame in feed.frames:
        bar = frame.bars_by_symbol.get("SPY")
        if bar is None:
            continue
        peak = max(peak, bar.close)
        if peak > 0:
            maximum = max(maximum, (peak - bar.close) / peak * Decimal("100"))
    return _percent(maximum)


def _compound_returns(values: list[Decimal | None]) -> Decimal | None:
    if not values or any(value is None for value in values):
        return None
    growth = Decimal("1")
    for value in values:
        assert value is not None
        growth *= Decimal("1") + value / Decimal("100")
    return _percent((growth - Decimal("1")) * Decimal("100"))


def _load_bundle(root: Path, *, start: str, end: str) -> _CatalogBundle:
    def load(price_view: str, bar_size: str) -> ResearchCatalogLoadReport:
        return load_research_catalog(
            ResearchCatalogLoadRequest(
                root_path=root.as_posix(),
                price_view=price_view,
                bar_size=bar_size,
                start_date=start,
                end_date=end,
            )
        )

    return _CatalogBundle(
        signal=load("split_adjusted_signal", "5 mins"),
        execution=load("raw_execution", "5 mins"),
        benchmark=load("total_return_benchmark", "1 day"),
    )


def _slice_feed(feed: BacktestDataFeed, start: int, end: int) -> BacktestDataFeed:
    frames = feed.frames[start:end]
    return feed.model_copy(
        update={
            "frames": frames,
            "total_bars": len(frames),
            "frame_count": len(frames),
            "first_timestamp": frames[0].timestamp if frames else None,
            "last_timestamp": frames[-1].timestamp if frames else None,
            "missing_bars_by_symbol": {"SPY": 0},
        }
    )


def _slice_feed_by_date(
    feed: BacktestDataFeed | None,
    start: date,
    end: date,
) -> BacktestDataFeed | None:
    if feed is None:
        return None
    frames = [
        frame for frame in feed.frames if start <= frame.timestamp.date() <= end
    ]
    return _slice_feed(feed, 0, 0).model_copy(
        update={
            "frames": frames,
            "total_bars": len(frames),
            "frame_count": len(frames),
            "first_timestamp": frames[0].timestamp if frames else None,
            "last_timestamp": frames[-1].timestamp if frames else None,
            "feed_status": feed.feed_status if frames else "failed",
        }
    ) if frames else None


def _empty_slice(feed: BacktestDataFeed) -> BacktestDataFeed:
    return _slice_feed(feed, 0, 0).model_copy(update={"feed_status": "failed"})


def _register_spec(
    catalog_path: Path,
    spec: ResearchExperimentSpec,
    spec_fingerprint: str,
) -> None:
    with _connection(catalog_path) as connection:
        existing = connection.execute(
            "SELECT spec_fingerprint FROM experiment_specs WHERE experiment_id = ?",
            (spec.experiment_id,),
        ).fetchone()
        if existing is not None and str(existing[0]) != spec_fingerprint:
            raise ValueError("experiment_id is already registered to a different spec")
        if existing is None:
            connection.execute(
                """
                INSERT INTO experiment_specs(
                    experiment_id, spec_fingerprint, spec_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    spec.experiment_id,
                    spec_fingerprint,
                    json.dumps(spec.model_dump(mode="json"), sort_keys=True),
                    _utc_iso(),
                ),
            )


def _record_holdout_access(
    catalog_path: Path,
    spec: ResearchExperimentSpec,
    holdout_fingerprint: str,
    confirmation: str,
) -> None:
    with _connection(catalog_path) as connection:
        existing = connection.execute(
            "SELECT 1 FROM holdout_access WHERE experiment_id = ?",
            (spec.experiment_id,),
        ).fetchone()
        if existing is not None:
            raise ValueError("this experiment's final holdout was already accessed")
        connection.execute(
            """
            INSERT INTO holdout_access(
                experiment_id, holdout_fingerprint, confirmation, accessed_at
            ) VALUES (?, ?, ?, ?)
            """,
            (spec.experiment_id, holdout_fingerprint, confirmation, _utc_iso()),
        )


def _record_run(
    catalog_path: Path,
    experiment_id: str,
    *,
    phase: str,
    dataset_fingerprint: str,
    status: str,
) -> str:
    run_id = f"experiment-run-{uuid4().hex}"
    with _connection(catalog_path) as connection:
        connection.execute(
            """
            INSERT INTO experiment_runs(
                run_id, experiment_id, phase, dataset_fingerprint, status,
                report_path, created_at
            ) VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                run_id,
                experiment_id,
                phase,
                dataset_fingerprint,
                status,
                _utc_iso(),
            ),
        )
    return run_id


def _report(
    request: ResearchExperimentRequest,
    *,
    spec: ResearchExperimentSpec | None,
    spec_path: Path,
    spec_fingerprint: str | None,
    spec_tracked: bool,
    commit_sha: str | None,
    catalog_path: Path,
    bundle: _CatalogBundle | None = None,
    development: _DevelopmentResult | None = None,
    holdout_result: ResearchExperimentCandidateResult | None = None,
    holdout_recorded: bool = False,
    holdout_consumed: bool = False,
    diagnostics: ResearchStatisticalDiagnostics | None = None,
    benchmark_drawdown: Decimal | None = None,
    validation_gate: bool = False,
    two_x_gate: bool = False,
    holdout_return_gate: bool = False,
    dsr_gate: bool = False,
    holdout_drawdown_gate: bool = False,
    review_ready: bool = False,
    run_id: str | None = None,
    warnings: list[str],
    errors: list[str],
) -> ResearchExperimentReport:
    completed = not errors and development is not None and development.selected is not None
    return ResearchExperimentReport(
        ok=completed,
        request=request,
        spec=spec,
        experiment_id=spec.experiment_id if spec else None,
        run_id=run_id,
        phase=request.phase,
        spec_path=spec_path.as_posix(),
        spec_fingerprint=spec_fingerprint,
        spec_git_tracked=spec_tracked,
        commit_sha=commit_sha,
        catalog_path=catalog_path.as_posix(),
        signal_dataset_fingerprint=bundle.signal.dataset_fingerprint if bundle else None,
        execution_dataset_fingerprint=(
            bundle.execution.dataset_fingerprint if bundle else None
        ),
        benchmark_dataset_fingerprint=(
            bundle.benchmark.dataset_fingerprint if bundle else None
        ),
        action_fingerprint=bundle.signal.action_fingerprint if bundle else None,
        validation_folds=development.folds if development else [],
        development_candidates=development.candidates if development else [],
        selected_candidate=development.selected if development else None,
        holdout_result=holdout_result,
        holdout_access_recorded=holdout_recorded,
        holdout_access_consumed=holdout_consumed,
        positive_validation_year_count=development.positive_years if development else 0,
        aggregate_validation_base_return_pct=(
            development.aggregate_base_return if development else None
        ),
        aggregate_validation_two_x_return_pct=(
            development.aggregate_two_x_return if development else None
        ),
        holdout_benchmark_drawdown_pct=benchmark_drawdown,
        statistical_diagnostics=diagnostics,
        validation_year_gate_passed=validation_gate,
        two_x_cost_gate_passed=two_x_gate,
        holdout_return_gate_passed=holdout_return_gate,
        deflated_sharpe_gate_passed=dsr_gate,
        holdout_drawdown_gate_passed=holdout_drawdown_gate,
        research_review_ready=review_ready,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
        final_status="completed" if completed else "failed",
    )


def _git_evidence(spec_path: Path) -> tuple[str | None, bool]:
    try:
        root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=spec_path.parent,
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
        if root_result.returncode != 0:
            return None, False
        root = Path(root_result.stdout.strip()).resolve()
        relative = spec_path.relative_to(root)
        committed_result = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{relative.as_posix()}"],
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
        clean_result = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative.as_posix()],
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
        commit_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, False
    commit = commit_result.stdout.strip() if commit_result.returncode == 0 else None
    spec_matches_head = committed_result.returncode == 0 and clean_result.returncode == 0
    return commit or None, spec_matches_head


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _percent(value: Decimal) -> Decimal:
    return value.quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


class _connection:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        self.connection = connection
        return connection

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        assert self.connection is not None
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()


__all__ = ["run_research_experiment"]

"""Broker-free strategy contract diagnostics."""

from __future__ import annotations

from trader.backtest.data_adapter import iter_feed_frames, summarize_backtest_feed
from trader.models import (
    BacktestDataFeed,
    BacktestDataFeedSummary,
    BacktestFeedFrame,
    StrategyContractDiagnostic,
    StrategyContractReport,
    StrategyContractValidationRequest,
    StrategyContractValidationResult,
    StrategyFrameContext,
    StrategyMetadata,
)


class NoOpStrategyContract:
    """No-op contract implementation that records frame diagnostics only."""

    metadata = StrategyMetadata(
        strategy_name="noop_contract",
        strategy_version="0.1.0",
        description="No-op contract scaffold for future broker-free strategy integration.",
        supported_bar_sizes=["5 mins"],
        required_fields=["open", "high", "low", "close", "volume"],
        broker_required=False,
    )

    def observe(self, context: StrategyFrameContext) -> StrategyContractDiagnostic:
        errors = _required_field_errors(context, self.metadata.required_fields)
        return StrategyContractDiagnostic(
            strategy_name=self.metadata.strategy_name,
            strategy_version=self.metadata.strategy_version,
            timestamp=context.timestamp,
            frame_index=context.frame_index,
            available_symbols=context.available_symbols,
            missing_symbols=context.missing_symbols,
            diagnostics={
                "frame_observed": True,
                "available_symbol_count": len(context.available_symbols),
                "missing_symbol_count": len(context.missing_symbols),
            },
            errors=errors,
        )


def build_strategy_frame_context(
    frame: BacktestFeedFrame,
    feed_summary: BacktestDataFeedSummary,
    *,
    frame_index: int = 0,
) -> StrategyFrameContext:
    """Build a read-only context from one feed frame."""

    available_symbols = sorted(
        symbol for symbol, bar in frame.bars_by_symbol.items() if bar is not None
    )
    missing_symbols = sorted(frame.missing_symbols)
    return StrategyFrameContext(
        timestamp=frame.timestamp,
        frame_index=frame_index,
        available_symbols=available_symbols,
        missing_symbols=missing_symbols,
        bars_by_symbol=frame.bars_by_symbol,
        feed_symbols=feed_summary.symbols,
        alignment_mode=feed_summary.alignment_mode,
        feed_status=feed_summary.feed_status,
        feed_frame_count=feed_summary.frame_count,
        feed_summary=feed_summary,
    )


def validate_strategy_contract(metadata: StrategyMetadata) -> list[str]:
    """Validate strategy metadata required by the contract scaffold."""

    errors: list[str] = []
    if metadata.broker_required:
        errors.append("broker_required must remain false for this contract scaffold")
    if not metadata.strategy_name.strip():
        errors.append("strategy_name is required")
    if not metadata.strategy_version.strip():
        errors.append("strategy_version is required")
    if not metadata.required_fields:
        errors.append("required_fields must not be empty")
    if not metadata.supported_bar_sizes:
        errors.append("supported_bar_sizes must not be empty")
    return errors


def run_noop_strategy_contract_diagnostic(
    feed: BacktestDataFeed,
    request: StrategyContractValidationRequest | None = None,
) -> StrategyContractValidationResult:
    """Validate the no-op strategy contract against a broker-free feed."""

    validation_request = request or StrategyContractValidationRequest(symbols=feed.symbols)
    contract = NoOpStrategyContract()
    feed_summary = summarize_backtest_feed(feed)
    warnings = list(dict.fromkeys(feed.warnings))
    errors = list(dict.fromkeys([*feed.errors, *validate_strategy_contract(contract.metadata)]))
    diagnostics: list[StrategyContractDiagnostic] = []
    sample_context: StrategyFrameContext | None = None

    if not feed.frames:
        errors.append("source feed contains no frames")

    if not errors:
        for index, frame in enumerate(iter_feed_frames(feed)):
            context = build_strategy_frame_context(
                frame,
                feed_summary,
                frame_index=index,
            )
            if sample_context is None:
                sample_context = context
            diagnostic = contract.observe(context)
            diagnostics.append(diagnostic)
            errors.extend(diagnostic.errors)
            warnings.extend(diagnostic.warnings)

    unique_errors = list(dict.fromkeys(errors))
    unique_warnings = list(dict.fromkeys(warnings))
    ok = bool(diagnostics) and not unique_errors
    return StrategyContractValidationResult(
        ok=ok,
        request=validation_request,
        metadata=contract.metadata,
        feed_summary=feed_summary,
        frame_context_sample=sample_context,
        diagnostics=diagnostics,
        contexts_observed=len(diagnostics),
        warnings=unique_warnings,
        errors=unique_errors,
        final_status="validated" if ok else "failed",
    )


def build_strategy_contract_report(
    feed: BacktestDataFeed,
    request: StrategyContractValidationRequest,
) -> StrategyContractReport:
    """Build a serializable report for no-op contract validation."""

    result = run_noop_strategy_contract_diagnostic(feed, request)
    return StrategyContractReport(
        ok=result.ok,
        request=request,
        metadata=result.metadata,
        symbols_requested=request.symbols,
        feed_summary=result.feed_summary,
        frame_context_sample=result.frame_context_sample,
        result=result,
        diagnostics=result.diagnostics,
        warnings=result.warnings,
        errors=result.errors,
        final_status=result.final_status,
    )


def summarize_strategy_contract_report(
    result: StrategyContractValidationResult,
) -> StrategyContractValidationResult:
    """Return the compact validation result for reporting surfaces."""

    return result


def _required_field_errors(
    context: StrategyFrameContext,
    required_fields: list[str],
) -> list[str]:
    errors: list[str] = []
    for symbol in context.available_symbols:
        bar = context.bars_by_symbol.get(symbol)
        if bar is None:
            continue
        missing = [
            field_name
            for field_name in required_fields
            if getattr(bar, field_name, None) is None
        ]
        if missing:
            errors.append(
                f"{symbol} bar missing required fields: {', '.join(sorted(missing))}"
            )
    return errors

"""Broker-free disabled signal contract diagnostics."""

from __future__ import annotations

from trader.backtest.data_adapter import iter_feed_frames, summarize_backtest_feed
from trader.models import (
    BacktestDataFeed,
    BacktestDataFeedSummary,
    BacktestFeedFrame,
    SignalContractDiagnostic,
    SignalContractMetadata,
    SignalContractReport,
    SignalContractValidationRequest,
    SignalContractValidationResult,
    SignalEvaluationContext,
    SignalFieldRequirement,
    StrategyMetadata,
)
from trader.strategy.interface import NoOpStrategyContract


class DisabledSignalContract:
    """Disabled contract implementation that records frame diagnostics only."""

    def __init__(self, metadata: SignalContractMetadata | None = None) -> None:
        self.metadata = metadata or default_disabled_signal_contract_metadata()

    def observe(self, context: SignalEvaluationContext) -> SignalContractDiagnostic:
        errors = _required_field_errors(context, self.metadata.required_fields)
        return SignalContractDiagnostic(
            signal_contract_name=self.metadata.signal_contract_name,
            signal_contract_version=self.metadata.signal_contract_version,
            timestamp=context.timestamp,
            frame_index=context.frame_index,
            available_symbols=context.available_symbols,
            missing_symbols=context.missing_symbols,
            diagnostics={
                "context_observed": True,
                "evaluation_disabled": True,
                "available_symbol_count": len(context.available_symbols),
                "missing_symbol_count": len(context.missing_symbols),
                "signal_count": 0,
            },
            errors=errors,
        )


def default_disabled_signal_contract_metadata(
    *,
    supported_symbols: list[str] | None = None,
) -> SignalContractMetadata:
    """Return the disabled broker-free signal contract metadata."""

    return SignalContractMetadata(
        signal_contract_name="disabled_signal_contract",
        signal_contract_version="0.1.0",
        description=(
            "Disabled signal contract scaffold for future broker-free evaluation."
        ),
        supported_symbols=supported_symbols or [],
        supported_bar_sizes=["5 mins"],
        required_fields=[
            SignalFieldRequirement(name="open"),
            SignalFieldRequirement(name="high"),
            SignalFieldRequirement(name="low"),
            SignalFieldRequirement(name="close"),
            SignalFieldRequirement(name="volume"),
        ],
        broker_required=False,
        enabled=False,
    )


def build_signal_evaluation_context(
    frame: BacktestFeedFrame,
    feed_summary: BacktestDataFeedSummary,
    strategy_metadata: StrategyMetadata | None = None,
    signal_metadata: SignalContractMetadata | None = None,
    *,
    frame_index: int = 0,
) -> SignalEvaluationContext:
    """Build a read-only signal context from one feed frame."""

    available_symbols = sorted(
        symbol for symbol, bar in frame.bars_by_symbol.items() if bar is not None
    )
    missing_symbols = sorted(frame.missing_symbols)
    return SignalEvaluationContext(
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
        strategy_metadata=strategy_metadata,
        signal_contract_metadata=signal_metadata,
    )


def validate_signal_contract(metadata: SignalContractMetadata) -> list[str]:
    """Validate disabled signal contract metadata."""

    errors: list[str] = []
    if metadata.broker_required:
        errors.append("broker_required must remain false for this signal contract")
    if metadata.enabled:
        errors.append("enabled must remain false for this signal contract")
    if not metadata.signal_contract_name.strip():
        errors.append("signal_contract_name is required")
    if not metadata.signal_contract_version.strip():
        errors.append("signal_contract_version is required")
    if not metadata.required_fields:
        errors.append("required_fields must not be empty")
    if not metadata.supported_bar_sizes:
        errors.append("supported_bar_sizes must not be empty")
    return errors


def run_disabled_signal_contract_diagnostic(
    feed: BacktestDataFeed,
    request: SignalContractValidationRequest | None = None,
) -> SignalContractValidationResult:
    """Validate the disabled signal contract against a broker-free feed."""

    validation_request = request or SignalContractValidationRequest(symbols=feed.symbols)
    strategy_metadata = NoOpStrategyContract().metadata
    metadata = default_disabled_signal_contract_metadata(
        supported_symbols=validation_request.symbols or feed.symbols
    )
    metadata_errors = validate_signal_contract(metadata)
    contract_validated = not metadata_errors
    feed_summary = summarize_backtest_feed(feed)
    warnings = list(dict.fromkeys(feed.warnings))
    errors = list(dict.fromkeys([*feed.errors, *metadata_errors]))
    diagnostics: list[SignalContractDiagnostic] = []
    sample_context: SignalEvaluationContext | None = None

    if not feed.frames:
        errors.append("source feed contains no frames")

    if not errors:
        contract = DisabledSignalContract(metadata)
        for index, frame in enumerate(iter_feed_frames(feed)):
            context = build_signal_evaluation_context(
                frame,
                feed_summary,
                strategy_metadata,
                metadata,
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
    signal_count = sum(diagnostic.signal_count for diagnostic in diagnostics)
    ok = bool(diagnostics) and not unique_errors and contract_validated
    return SignalContractValidationResult(
        ok=ok,
        request=validation_request,
        metadata=metadata,
        feed_summary=feed_summary,
        frame_context_sample=sample_context,
        diagnostics=diagnostics,
        contexts_observed=len(diagnostics),
        warnings=unique_warnings,
        errors=unique_errors,
        final_status="validated" if ok else "failed",
        signal_contract_validated=contract_validated,
        signal_count=signal_count,
    )


def build_signal_contract_report(
    feed: BacktestDataFeed,
    request: SignalContractValidationRequest,
) -> SignalContractReport:
    """Build a serializable report for disabled signal contract validation."""

    result = run_disabled_signal_contract_diagnostic(feed, request)
    return SignalContractReport(
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
        signal_contract_validated=result.signal_contract_validated,
        signal_count=result.signal_count,
    )


def summarize_signal_contract_report(
    result: SignalContractValidationResult,
) -> SignalContractValidationResult:
    """Return the compact validation result for reporting surfaces."""

    return result


def _required_field_errors(
    context: SignalEvaluationContext,
    required_fields: list[SignalFieldRequirement],
) -> list[str]:
    errors: list[str] = []
    for symbol in context.available_symbols:
        bar = context.bars_by_symbol.get(symbol)
        if bar is None:
            continue
        missing = [
            requirement.name
            for requirement in required_fields
            if requirement.required and getattr(bar, requirement.name, None) is None
        ]
        if missing:
            errors.append(
                f"{symbol} bar missing required fields: {', '.join(sorted(missing))}"
            )
    return errors

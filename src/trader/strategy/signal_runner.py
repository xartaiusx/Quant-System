"""Broker-free disabled signal diagnostic runner."""

from __future__ import annotations

from trader.backtest.data_adapter import iter_feed_frames, summarize_backtest_feed
from trader.models import (
    BacktestDataFeed,
    BacktestFeedFrame,
    BacktestFeedStatus,
    DisabledSignalFrameDiagnostic,
    DisabledSignalRunnerDiagnostics,
    DisabledSignalRunnerReport,
    DisabledSignalRunnerRequest,
    DisabledSignalRunnerResult,
    DisabledSignalRunnerStatus,
    SignalContractDiagnostic,
)
from trader.strategy.signals import (
    DisabledSignalContract,
    build_signal_evaluation_context,
    default_disabled_signal_contract_metadata,
    validate_signal_contract,
)


def run_disabled_signal_runner(
    feed: BacktestDataFeed,
    request: DisabledSignalRunnerRequest,
) -> DisabledSignalRunnerResult:
    """Replay feed frames through the disabled signal contract only."""

    metadata = default_disabled_signal_contract_metadata(
        supported_symbols=request.symbols or feed.symbols
    )
    feed_summary = summarize_backtest_feed(feed)
    metadata_errors = validate_signal_contract(metadata)
    contract_validated = not metadata_errors
    warnings = list(feed.warnings)
    errors = list(dict.fromkeys([*feed.errors, *metadata_errors]))
    frame_diagnostics: list[DisabledSignalFrameDiagnostic] = []

    if feed.feed_status == BacktestFeedStatus.FAILED:
        errors.append("source feed status is failed")
    if not feed.frames:
        errors.append("source feed contains no frames")

    if not errors:
        contract = DisabledSignalContract(metadata)
        for index, frame in enumerate(iter_feed_frames(feed)):
            context = build_signal_evaluation_context(
                frame,
                feed_summary,
                signal_metadata=metadata,
                frame_index=index,
            )
            diagnostic = contract.observe(context)
            frame_diagnostics.append(
                _frame_diagnostic(frame, index=index, diagnostic=diagnostic)
            )
            warnings.extend(diagnostic.warnings)
            errors.extend(diagnostic.errors)

    unique_warnings = list(dict.fromkeys(warnings))
    unique_errors = list(dict.fromkeys(errors))
    if unique_errors:
        runner_status = DisabledSignalRunnerStatus.FAILED
    elif feed.feed_status == BacktestFeedStatus.PARTIAL:
        runner_status = DisabledSignalRunnerStatus.PARTIAL
    else:
        runner_status = DisabledSignalRunnerStatus.COMPLETED

    diagnostics = _diagnostics(
        feed,
        request,
        frame_diagnostics=frame_diagnostics,
        runner_status=runner_status,
        warnings=unique_warnings,
        errors=unique_errors,
        signal_contract_name=metadata.signal_contract_name,
        signal_contract_version=metadata.signal_contract_version,
    )
    return DisabledSignalRunnerResult(
        ok=runner_status != DisabledSignalRunnerStatus.FAILED,
        request=request,
        metadata=metadata,
        feed_summary=feed_summary,
        diagnostics=diagnostics,
        frame_diagnostics=frame_diagnostics,
        warnings=unique_warnings,
        errors=unique_errors,
        signal_contract_validated=contract_validated,
    )


def summarize_disabled_signal_runner(
    result: DisabledSignalRunnerResult,
) -> DisabledSignalRunnerDiagnostics:
    """Return runner diagnostics for report surfaces."""

    return result.diagnostics


def validate_disabled_signal_runner_result(
    result: DisabledSignalRunnerResult,
) -> list[str]:
    """Validate disabled signal runner output without external systems."""

    errors = list(result.errors)
    timestamps = [item.timestamp for item in result.frame_diagnostics]
    if timestamps != sorted(timestamps):
        errors.append("signal runner frame diagnostics are not sorted by timestamp")
    if result.ok and not result.frame_diagnostics:
        errors.append("successful signal runner has no frame diagnostics")
    if result.diagnostics.contexts_built != len(result.frame_diagnostics):
        errors.append("signal runner context count does not match frame diagnostics")
    if result.diagnostics.diagnostics_emitted != len(result.frame_diagnostics):
        errors.append("signal runner diagnostic count does not match frame diagnostics")
    if result.signal_count != 0:
        errors.append("signal runner signal_count must remain 0")
    if any(item.signal_count != 0 for item in result.frame_diagnostics):
        errors.append("signal runner frame signal_count must remain 0")
    return list(dict.fromkeys(errors))


def build_disabled_signal_runner_report(
    feed: BacktestDataFeed,
    request: DisabledSignalRunnerRequest,
) -> DisabledSignalRunnerReport:
    """Run disabled signal diagnostics and build a serializable report."""

    result = run_disabled_signal_runner(feed, request)
    validation_errors = validate_disabled_signal_runner_result(result)
    errors = list(dict.fromkeys([*result.errors, *validation_errors]))
    if errors != result.errors:
        result = result.model_copy(
            update={
                "ok": False,
                "errors": errors,
                "diagnostics": result.diagnostics.model_copy(
                    update={
                        "runner_status": DisabledSignalRunnerStatus.FAILED,
                        "errors": errors,
                    }
                ),
            }
        )
    diagnostics = summarize_disabled_signal_runner(result)
    return DisabledSignalRunnerReport(
        ok=result.ok,
        request=request,
        metadata=result.metadata,
        symbols_requested=request.symbols,
        feed_summary=result.feed_summary,
        result=result,
        diagnostics=diagnostics,
        frame_diagnostics=result.frame_diagnostics,
        warnings=result.warnings,
        errors=errors,
        final_status=_status_value(diagnostics.runner_status),
        signal_contract_validated=result.signal_contract_validated,
    )


class DisabledSignalRunner:
    """Small wrapper around the broker-free disabled signal diagnostic runner."""

    def run(
        self,
        feed: BacktestDataFeed,
        request: DisabledSignalRunnerRequest,
    ) -> DisabledSignalRunnerResult:
        return run_disabled_signal_runner(feed, request)


def _frame_diagnostic(
    frame: BacktestFeedFrame,
    *,
    index: int,
    diagnostic: SignalContractDiagnostic,
) -> DisabledSignalFrameDiagnostic:
    available_symbols = [
        symbol for symbol, bar in sorted(frame.bars_by_symbol.items()) if bar is not None
    ]
    return DisabledSignalFrameDiagnostic(
        signal_contract_name=diagnostic.signal_contract_name,
        signal_contract_version=diagnostic.signal_contract_version,
        timestamp=frame.timestamp,
        frame_index=index,
        available_symbols=available_symbols,
        missing_symbols=sorted(frame.missing_symbols),
        diagnostic=diagnostic,
    )


def _diagnostics(
    feed: BacktestDataFeed,
    request: DisabledSignalRunnerRequest,
    *,
    frame_diagnostics: list[DisabledSignalFrameDiagnostic],
    runner_status: DisabledSignalRunnerStatus,
    warnings: list[str],
    errors: list[str],
    signal_contract_name: str,
    signal_contract_version: str,
) -> DisabledSignalRunnerDiagnostics:
    missing_by_symbol = {
        symbol: sum(1 for item in frame_diagnostics if symbol in item.missing_symbols)
        for symbol in feed.symbols
    }
    return DisabledSignalRunnerDiagnostics(
        signal_contract_name=signal_contract_name,
        signal_contract_version=signal_contract_version,
        symbols=feed.symbols,
        alignment_mode=request.alignment_mode,
        feed_status=feed.feed_status,
        runner_status=runner_status,
        frame_count=len(frame_diagnostics),
        contexts_built=len(frame_diagnostics),
        diagnostics_emitted=len(frame_diagnostics),
        first_timestamp=frame_diagnostics[0].timestamp if frame_diagnostics else None,
        last_timestamp=frame_diagnostics[-1].timestamp if frame_diagnostics else None,
        missing_symbols_by_frame_count=sum(
            1 for item in frame_diagnostics if item.missing_symbols
        ),
        missing_symbols_by_symbol=missing_by_symbol,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
    )


def _status_value(value: DisabledSignalRunnerStatus | str) -> str:
    return str(getattr(value, "value", value))

# Status

## Implemented

- Milestone 2 complete: safe read-only TWS / IB Gateway broker-probe path.
- Milestone 3 implemented: optional IBKR API install checks and real probe readiness diagnostics.
- Empty repo inspection and recorded implementation plan.
- Python 3.11+ `src` layout.
- Safety-focused `pyproject.toml`, `.gitignore`, `.env.example`, and `AGENTS.md`.
- Strict config loader with live-mode and live-port rejection.
- Serializable domain models.
- Typer CLI shell.
- IBKR broker adapter with optional read-only TWS / IB Gateway current-time probe.
- Masked managed-account discovery and broker-probe JSON/Markdown reports.
- Milestone 3 broker readiness diagnostics with `connection_attempted`, `failure_stage`, `ibapi_import_error`, and `no_order_guarantee=true`.
- Broker-probe connection readiness based on IBKR callbacks and current-time response, not only the Python `ibapi` `connect()` return value.
- Non-fatal IBKR farm-status messages, including `2107`, are reported as warnings for current-time probing.
- Milestone 5 implemented: read-only IBKR market-data diagnostics for contract resolution, market-data type, quote ticks, spread/freshness checks, and optional historical bars.
- Optional `ibapi` dependency check script.
- Deterministic mock data.
- Momentum and mean-reversion strategy modules.
- Portfolio construction.
- Risk engine.
- Execution router.
- Simulator.
- Refusing paper executor.
- JSON and Markdown journal writer.
- Backtest placeholders.
- Tests and safe scripts, including `scripts/check-ibapi.sh`, `scripts/run-broker-preflight.sh`, and `scripts/run-broker-probe.sh`.

## Intentionally Blocked

- Live trading.
- Broker order submission.
- Market orders.
- Paper executor submission.
- Direct strategy-to-broker calls.
- TWS dependency in unit tests.
- Unmasked account-sensitive reports.
- Live ports `7496` and `4001`.
- Broker order routing from read-only probe commands.
- Broker market-data diagnostics feeding automated execution.

## Current Blockers

- Paper execution remains blocked by `PaperExecutor`.
- Live trading remains impossible.

## Current Local Validation

- `ibapi` is installed and importable in this checkout's `.venv`.
- IB Gateway paper on `127.0.0.1:4002` accepted a read-only broker probe.
- Latest successful broker-probe returned current server time, masked managed-account output, `order_routing_enabled=false`, and `no_order_guarantee=true`.
- Before market-data diagnostics in a new environment, rerun a successful read-only current-time broker probe.
- Market-data diagnostics may still be limited by IBKR data permissions, delayed-data availability, market hours, or pacing.

## Next Recommended Steps

1. Review market-probe reports across market hours and outside market hours.
2. Add historical-data snapshot ingestion with clear subscription/readiness diagnostics.
3. Write a paper-execution activation proposal before changing `PaperExecutor` to submit anything.

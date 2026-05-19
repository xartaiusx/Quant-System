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
- Milestone 6 implemented: read-only historical snapshot ingestion, local JSONL/manifests, and readiness reporting for future simulation inputs.
- Milestone 7 implemented: broker-free offline historical snapshot indexing, loading, normalization, validation, and loader reports.
- Milestone 8 implemented: broker-free backtest data feed scaffold with union/intersection alignment, missing-bar diagnostics, and feed reports.
- Milestone 9 implemented: broker-free backtest engine skeleton with deterministic frame replay diagnostics and run reports.
- Milestone 10 implemented: broker-free strategy interface contract scaffold with no-op frame diagnostics and contract reports.
- Milestone 11 implemented: broker-free inert strategy runner scaffold with per-frame no-op diagnostics and runner reports.
- Milestone 12 implemented: broker-free offline fixture stress suite covering partial, gapped, duplicate, malformed, missing, empty, and invalid historical datasets.
- Milestone 13 implemented: broker-free disabled signal contract scaffold with diagnostics-only validation and signal-contract reports.
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
- Historical snapshots feeding automated execution.
- Offline historical datasets feeding automated execution.
- Backtest feeds evaluating strategies, simulating orders, or calculating P&L.
- Backtest runs evaluating strategies, simulating orders, calculating fills, maintaining portfolio accounting, or calculating P&L.
- Strategy contract checks performing real signal generation, simulating orders, calculating fills, maintaining portfolio accounting, or calculating P&L.
- Strategy runner checks performing real strategy evaluation, generating buy/sell/hold signals, generating order intents, simulating orders or fills, maintaining portfolio accounting, or calculating P&L.
- Offline stress tests contacting brokers, using real broker data, evaluating real strategies, generating signals or order intents, simulating orders or fills, maintaining portfolio accounting, or calculating P&L.
- Signal contract checks performing real signal evaluation, generating buy/sell/hold outputs, generating order intents, simulating orders or fills, maintaining portfolio accounting, or calculating P&L.

## Current Blockers

- Paper execution remains blocked by `PaperExecutor`.
- Live trading remains impossible.

## Current Local Validation

- `ibapi` is installed and importable in this checkout's `.venv`.
- IB Gateway paper on `127.0.0.1:4002` accepted a read-only broker probe.
- Latest successful broker-probe returned current server time, masked managed-account output, `order_routing_enabled=false`, and `no_order_guarantee=true`.
- Before market-data diagnostics in a new environment, rerun a successful read-only current-time broker probe.
- Market-data and historical snapshot diagnostics may still be limited by IBKR data permissions, delayed-data availability, market hours, or pacing.
- Offline `history-index`, `history-load`, and `history-inspect` read local files only and do not contact IBKR.
- Offline `backtest-feed` reads local historical datasets only, reports `broker_contacted=false`, and does not evaluate strategies, simulate orders, or compute P&L.
- Offline `backtest-run` replays local feed frames only, reports `broker_contacted=false`, `strategy_evaluated=false`, `orders_simulated=false`, and `pnl_calculated=false`.
- Offline `strategy-contract` validates no-op interface metadata and frame contexts only, reports `broker_contacted=false`, `evaluated=false`, `generated_signals=false`, `generated_orders=false`, `orders_simulated=false`, and `pnl_calculated=false`.
- Offline `strategy-runner` routes local feed frames through no-op diagnostics only, reports `broker_contacted=false`, `diagnostic_only=true`, `noop_strategy_observed=true`, `real_strategy_evaluated=false`, `generated_signals=false`, `generated_orders=false`, `orders_simulated=false`, `fills_simulated=false`, `portfolio_accounting=false`, and `pnl_calculated=false`.
- Offline stress fixtures validate loader, feed adapter, backtest engine, strategy contract, and inert runner behavior against synthetic edge-case datasets without contacting IBKR.
- Offline `signal-contract` validates disabled signal schema and frame contexts only, reports `broker_contacted=false`, `signal_contract_validated=true`, `signal_evaluation_enabled=false`, `generated_signals=false`, `signal_count=0`, `generated_orders=false`, `orders_simulated=false`, `fills_simulated=false`, `portfolio_accounting=false`, and `pnl_calculated=false`.

## Next Recommended Steps

1. Review the disabled signal contract reports before adding real signal evaluation.
2. Design an explicitly approved signal-evaluation milestone without order intents or execution.
3. Write a paper-execution activation proposal before changing `PaperExecutor` to submit anything.

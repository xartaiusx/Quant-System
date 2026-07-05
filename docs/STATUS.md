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
- Non-fatal IBKR farm-status messages, including `2103`, `2105`, `2107`, and `2108`, are reported as warnings for current-time probing.
- Milestone 5 implemented: read-only IBKR market-data diagnostics for contract resolution, market-data type, quote ticks, spread/freshness checks, and optional historical bars.
- Milestone 6 implemented: read-only historical snapshot ingestion, local JSONL/manifests, and readiness reporting for future simulation inputs.
- Milestone 7 implemented: broker-free offline historical snapshot indexing, loading, normalization, validation, and loader reports.
- Milestone 8 implemented: broker-free backtest data feed scaffold with union/intersection alignment, missing-bar diagnostics, and feed reports.
- Milestone 9 implemented: broker-free backtest engine skeleton with deterministic frame replay diagnostics and run reports.
- Milestone 10 implemented: broker-free strategy interface contract scaffold with no-op frame diagnostics and contract reports.
- Milestone 11 implemented: broker-free inert strategy runner scaffold with per-frame no-op diagnostics and runner reports.
- Milestone 12 implemented: broker-free offline fixture stress suite covering partial, gapped, duplicate, malformed, missing, empty, and invalid historical datasets.
- Milestone 13 implemented: broker-free disabled signal contract scaffold with diagnostics-only validation and signal-contract reports.
- Milestone 14 implemented: broker-free disabled signal diagnostic runner with per-frame disabled-signal diagnostics and signal-runner reports.
- Milestone 15 implemented: broker-free analytical signal evaluator with non-actionable condition observations and signal-evaluation reports.
- Milestone 16 implemented: broker-free commodity research universe with commodity-linked security proxies only.
- Milestone 17 implemented: read-only paper readiness orchestration for first paper-client program testing.
- Milestone 18 implemented: broker-free data-quality gate for local historical snapshots.
- Milestone 19 implemented: broker-free analytical evaluator comparison diagnostics.
- GitHub Actions CI added for tests, lint, typecheck, whitespace, and safety scans.
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

## Tag-To-Stage Map

- `v0.1.0-safe-foundation`: safe repo foundation.
- `v0.2.0-readonly-gateway-probe`: read-only IB Gateway broker probe.
- `v0.3.0-readonly-market-data`: read-only market-data diagnostics.
- `v0.4.0-readonly-history-snapshots`: read-only historical snapshots and readiness.
- `v0.5.0-offline-history-loader`: offline historical loader.
- `v0.6.0-broker-free-backtest-feed`: broker-free backtest feed adapter.
- `v0.7.0-broker-free-backtest-engine`: broker-free backtest engine skeleton.
- `v0.8.0-broker-free-strategy-contract`: broker-free strategy contract scaffold.
- `v0.9.0-broker-free-inert-strategy-runner`: broker-free inert strategy runner.
- `v0.10.0-offline-fixture-stress-suite`: broker-free offline fixture stress suite.
- `v0.11.0-broker-free-signal-contract`: broker-free disabled signal contract scaffold.
- `v0.11.1-stage-gated-audit-polish`: stage-gated audit and polish.
- `v0.12.0-broker-free-disabled-signal-runner`: broker-free disabled signal diagnostic runner.
- `v0.13.0-signal-evaluation-design`: broker-free analytical signal evaluator design tag.
- `v0.13`: broker-free analytical signal evaluator scaffold implemented in working tree.
- `v0.14`: broker-free commodity research universe scaffold implemented in working tree.
- `v0.15`: read-only paper readiness orchestration implemented in working tree.
- `v0.16`: broker-free data-quality gate implemented in working tree.
- `v0.17`: broker-free analytical evaluator comparison implemented in working tree.

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
- Signal runner checks performing real signal evaluation, generating buy/sell/hold outputs, generating order intents, simulating orders or fills, maintaining portfolio accounting, or calculating P&L.
- Analytical signal-evaluation checks creating trading instructions, order intents, fills, portfolio accounting, P&L, broker routing, paper execution, or live trading.
- Commodity universe checks enabling direct futures contracts, futures data requests, futures margin or roll modeling, order intents, fills, portfolio accounting, P&L, broker routing, paper execution, or live trading.
- Paper readiness checks submitting orders, enabling paper orders, disabling the expected TWS Read-Only API setting, accepting mock account fallback as success, enabling direct futures contracts, or merging without review.
- Data-quality gates contacting IBKR, evaluating signals, generating order intents, simulating fills, calculating P&L, enabling direct futures contracts, or routing execution.
- Evaluator comparisons contacting IBKR, ranking trade recommendations, optimizing P&L, generating trading signals, creating order intents, simulating fills, enabling direct futures contracts, or routing execution.
- Paper reconciliation submitting, modifying, or canceling orders while collecting account, position, open-order, and execution evidence.

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
- Offline `signal-runner` routes local feed frames through the disabled signal contract only, reports `broker_contacted=false`, `disabled_signal_runner=true`, `signal_contract_validated=true`, `signal_evaluation_enabled=false`, `generated_signals=false`, `signal_count=0`, `generated_orders=false`, `order_intents_generated=false`, `orders_simulated=false`, `fills_simulated=false`, `portfolio_accounting=false`, and `pnl_calculated=false`.
- Offline `signal-evaluate` evaluates non-actionable moving-average relationship observations from local feed frames only, reports `broker_contacted=false`, `signal_evaluation_enabled=true`, `generated_signals=false`, `signal_count=0`, `generated_orders=false`, `order_intents_generated=false`, `orders_simulated=false`, `fills_simulated=false`, `portfolio_accounting=false`, and `pnl_calculated=false`.
- Offline `commodity-universe` lists commodity-linked security proxies only, reports `broker_contacted=false`, `futures_contracts_enabled=false`, `direct_futures_data_enabled=false`, `signal_evaluation_enabled=false`, `generated_signals=false`, `signal_count=0`, `order_intents_generated=false`, `orders_simulated=false`, `fills_simulated=false`, `portfolio_accounting=false`, and `pnl_calculated=false`.
- `paper-readiness-run` runs broker probe, broker account summary, historical snapshot, historical load, commodity universe, and analytical signal evaluation sequentially. It uses distinct broker-contact client IDs with a configurable pause, reports `submitted_orders=false`, `paper_orders_enabled=false`, `read_only_api_expected=true`, `order_routing_enabled=false`, and rejects mock account fallback as readiness success.
- Offline `data-quality-gate` validates local snapshots only, reports `broker_contacted=false`, `signal_evaluation_enabled=false`, `generated_signals=false`, `order_intents_generated=false`, `pnl_calculated=false`, `futures_contracts_enabled=false`, and `direct_futures_data_enabled=false`.
- Offline `evaluator-compare` compares approved moving-average diagnostic condition counts across explicit window candidates only, reports `broker_contacted=false`, `generated_signals=false`, `signal_count=0`, `order_intents_generated=false`, `orders_simulated=false`, `portfolio_accounting=false`, and `pnl_calculated=false`.
- Latest local data-quality check found `DBA` has `2` zero-volume bars; default gate fails closed, while an explicit `--max-zero-volume-bars 2` threshold documents the known partial symbol.
- Latest local `evaluator-compare` completed for `SPY,AAPL,GLD,USO,DBA` with window pairs `5:20,10:30`, `390` observations per candidate, and no generated signals or P&L.
- `paper-reconcile` distinguishes completed zero-position responses from unavailable positions, requests current-day execution/commission evidence, and writes a broker-state fingerprint while keeping `submitted_orders=false` and `order_api_invoked=false`.

## Next Recommended Steps

1. Run `paper-reconcile` after every paper-order window and review position-query completion, zero-position confirmation, execution order IDs, commission rows, and broker-state fingerprint before marking the next alpha window eligible.
2. Add campaign identity across alpha shadow, paper smoke, alpha paper, reconcile, and summary reports so one ignored local paper campaign can be verified end to end.
3. Create `alpha-campaign-run` to orchestrate read-only shadow, deliberate paper window, Read-Only restoration, reconciliation, and summary in a single sequential command.
4. Keep commodity research in security proxies until a futures-contract, rollover, margin, and risk-model milestone is explicitly approved.
5. Keep future signal-evaluation work free of expanded execution, fills, portfolio accounting, and P&L until explicitly approved.
6. Build the paper ledger and autonomous shadow daemon before any broader paper execution daemon.

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
- One versioned, fingerprinted, broker-free `SPYSmaPolicy` now supplies completed-
  bar FLAT/LONG target state to both research and alpha-shadow paths.
- Offline SPY vendor bake-off validates manually supplied Massive/Norgate samples,
  session alignment, corrections, overlap, corporate-action fixtures, checksums,
  and written data rights without network or credential access.
- Catalog schema v3 adds deterministic batch imports, corporate-action sets,
  immutable derived revisions, parent lineage, permanent holdout seals,
  experiment supersession/access records, and versioned SPY identity.
- Offline vendor decisions enforce written-rights and budget hard gates before
  weighted technical scoring; contracts and responses remain outside Git.
- Dual research views are implemented: raw five-minute execution bars,
  split-adjusted five-minute signal bars, and a daily total-return benchmark.
- Catalog loading fails closed on stale parents, inactive revisions, checksum
  drift, missing actions, incomplete five-minute groups, and incorrect XNYS
  normal/early-close coverage.
- Broker-free SPY simulation now models price-protected `LMT DAY` orders,
  trade-through, partial fills, cancellations, fixed/target-allocation sizing,
  splits, dividends, portfolio accounting, daily returns, base/2x/3x/5x crisis
  costs, and
  expanded performance/drawdown/turnover evidence.
- A tracked v2 2016-2025 experiment requires a clean hash-locked release,
  permanently seals 2024-2025 before import, rejects generic sealed-period
  loads, records consumption before capability-scoped access, and enforces
  phase-specific trade-count gates without automatic execution promotion.
- Strategy-driven alpha paper commands require fresh same-commit passing
  research and ten-session strict-live evidence. Lifecycle smoke remains exempt.
- Daily SPY history from inception retains an explicit 1993-2003 provenance gap
  until a licensed daily/action export passes the vendor bake-off.
- GitHub Actions CI uses hash-locked dependencies, Linux Python 3.11/3.12 and
  Windows Python 3.12, dependency audit, a 76% branch-coverage floor, lint,
  typecheck, whitespace, order-API allowlist, and sensitive-artifact scans.
- Optional `ibapi` dependency check script.
- Offline `ibapi` protocol compatibility check for the current official IBKR
  client, with a minimum supported server protocol of `163`.
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
- Research-backtest or walk-forward reports automatically promoting a signal;
  independent research review and strict-live shadow graduation remain required.
- Research commands reading ad hoc IBKR snapshot datasets instead of passing
  active catalog revisions.
- Autonomous SPY paper-daemon implementation before five clean strict-live
  sessions on five distinct XNYS dates.
- Any lifecycle engineering pilot before ten clean strict-live sessions across
  opening, midday, and closing windows.

## Current Blockers

- No vendor has yet supplied written rights and passing sample evidence for the
  required uses; standard published Massive/Norgate terms remain provisionally
  insufficient for post-cancellation retention.
- The canonical catalog has not yet been populated with licensed 2016-2025 SPY
  minute data and approved inception-through-2025 daily/corporate-action data.
- The preregistered development/final-holdout experiment cannot run until those
  passing active revisions exist.
- Strict-live shadow graduation still requires funded/subscribed IBKR live SPY
  API market data and repeated same-fingerprint evidence on distinct market dates.
- Autonomous paper execution remains blocked by the normal `PaperExecutor` and
  by research/strict-live gates. Only the existing manual paper smoke path may
  call paper order APIs.
- Live trading remains impossible.

## Current Local Validation

- `ibapi` is installed and importable in this checkout's `.venv`.
- Official `ibapi 10.48.1` is installed in this checkout's `.venv`, supports
  server protocol `225`, and passes the minimum protocol `163` compatibility
  check.
- The IBKR adapters accept both legacy and current timestamped error callbacks,
  use the current `OrderCancel` payload, and capture current
  `commissionAndFeesReport` callbacks.
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
- `paper-reconcile` distinguishes completed zero-position responses from unavailable positions, requests current-day execution/commission evidence, writes a broker-state fingerprint, and verifies source-report campaign IDs while keeping `submitted_orders=false` and `order_api_invoked=false`.
- Alpha shadow, paper smoke, alpha paper, reconcile, and alpha summary reports now carry a no-secret `campaign_id`; reconcile, alpha paper, and summary fail closed when source report campaign IDs do not match.
- `alpha-campaign-run` orchestrates the existing staged SPY paper-alpha workflow in `shadow` or `paper` mode, writes a top-level campaign report, and keeps order APIs confined to the existing paper execution boundary.
- `paper-ledger-update` reads ignored summary and reconciliation reports offline, validates current-commit same-campaign broker truth, and upserts one masked local JSONL campaign row under ignored `state/`.
- `alpha-shadow-run` assembles complete cached XNYS sessions with the current
  completed strict-live prefix, checks overlap/boundary agreement, and applies
  freshness only to the newest current bar.
- `alpha-shadow-daemon` writes ignored heartbeat plus release/config/strategy/data
  fingerprints, trading-date, and coverage-window evidence while keeping order
  APIs disabled. Graduating evidence requires a clean committed worktree and a
  unique campaign-specific immutable heartbeat.
- `alpha-shadow-daemon-summary` requires five clean strict-live sessions on five
  distinct XNYS dates for implementation graduation and ten clean sessions with
  opening/midday/closing coverage for lifecycle-pilot eligibility. Delayed
  reports never count.
- `ibkr-data-diagnostics` reads ignored local reports offline, verifies strict SPY `1 D` / `5 mins` / `TRADES` / `use_rth=1` data freshness and broker/account evidence, surfaces live market-data permission errors from `market-probe`, and keeps daemon startup blocked when latest-bar age exceeds the configured strict gate or live SPY API market data is unavailable.
- `ibkr-delayed-data-diagnostics` and `alpha-shadow-daemon-delayed` provide a read-only delayed-data engineering lane while live SPY API data is unavailable. Their reports are explicitly non-graduating and must not unlock paper-daemon design or paper execution.

## Next Recommended Steps

1. After this milestone is merged, migrate the empty external catalog to v3,
   register `research/instruments/spy_v1.json`, and register the committed v2
   experiment from a clean worktree so 2024-2025 is sealed before import.
2. Send the common RFI and complete the offline bake-off/vendor decision,
   including written rights and trial/export validation, before purchasing.
3. Import licensed 2016-2025 SPY minute files plus approved daily/action
   history, derive all views, and require passing catalog load/audit evidence.
4. Run v2 development only. Do not use the final-holdout confirmation until
   development, lineage, cost calibration, and independent review are complete.
5. Fund/subscribe the IBKR account for live SPY API market data and complete the
   required API acknowledgement; delayed mode remains non-graduating.
6. Collect five clean strict-live sessions on five XNYS dates to unlock a separate
   paper-daemon implementation milestone.
7. Collect ten clean strict-live sessions across opening, midday, and closing
   windows before any lifecycle engineering pilot.
8. Require `research_review_ready=true` in addition to operational evidence
   before any strategy-driven paper alpha mode.
9. Keep the paper daemon unimplemented until those gates pass. Continue manual
   reconciliation, summary, and ledger updates after every approved paper window.
10. Keep GLD/USO research-only, DBA excluded, and direct futures blocked until a
   separate contract/roll/margin/liquidity/permission/delivery-risk program exists.

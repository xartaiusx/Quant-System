# Quant System Agent Guide

## Purpose

This repository is a safety-first Python foundation for a quantitative trading system intended to integrate with Interactive Brokers Trader Workstation or IB Gateway in later phases.

The current project is infrastructure only. It must support research, signal generation, risk checks, simulation, reporting, and future paper execution. It must not place live orders.

## Safety Rules

- Default behavior is dry-run.
- Default broker mode is paper.
- Live trading is not implemented and must remain impossible in this version.
- Reject `TRADING_MODE=live`.
- Reject `ALLOW_LIVE_ORDERS=true`.
- `ALLOW_PAPER_ORDERS` defaults to `false`.
- Do not add a live executor.
- Do not submit market orders.
- Broker-probe commands may read broker state through read-only API requests, but they must not submit, modify, or cancel orders.
- Market-data diagnostics may request contract, quote, and historical data, but they must never route execution.
- Historical-data commands may request and store data but must never route execution.
- Offline data commands must not import broker clients or contact IBKR.
- Backtest data adapter commands must remain broker-free and must not evaluate strategies, simulate orders, or compute P&L.
- Backtest engine skeleton commands must remain broker-free and must not evaluate strategies, simulate orders, or calculate P&L until explicitly approved in a future milestone.
- `research-backtest` is the approved broker-free SPY simulator. Operator runs must load passing active catalog revisions: split-adjusted five-minute bars for signals, raw five-minute bars for simulated execution, and the daily total-return benchmark. It may use the shared SPY target-state policy, simulate price-protected `LMT DAY` orders, partial fills, cancellations, capital events, explicit costs, portfolio accounting, and P&L. It must not import broker or execution modules, contact IBKR, invoke order APIs, expand beyond SPY, or report automatic promotion eligibility.
- `research-walk-forward` may run predeclared SPY candidates over chronological folds, but tracked `research-experiment-register` plus `research-experiment-run` are the authoritative final-holdout gate. Registration requires a clean committed release and permanently seals holdout dates. Generic catalog loaders must reject sealed overlap. Final access requires the exact preregistered confirmation, records one append-only catalog access row before reading data, and uses only the capability-scoped final-holdout loader. A consumed experiment must never be rerun or tuned against.
- Research data-store commands must remain offline-only, SPY-only, and broker-free. They may register immutable instrument identity, run operator-supplied vendor bake-off/decision reports, archive licensed approved exports, create immutable raw and derived Parquet revisions, maintain catalog-v3 lineage and experiment records, and load only passing active revisions. They must never download data implicitly, read credentials, contact IBKR, route orders, or activate failed/incomplete partitions.
- Strategy interface scaffold commands must remain broker-free and must not generate real signals, simulate orders, or calculate P&L until explicitly approved in a future milestone.
- Strategy runner commands must remain inert/no-op until a future milestone explicitly approves real signal generation. They must not generate orders, simulate fills, calculate P&L, or contact brokers.
- Offline stress tests may generate synthetic fixture data only and must remain broker-free.
- Signal contract commands must remain disabled-by-default and diagnostics-only until a future milestone explicitly approves signal generation. They must not generate order intents, simulate fills, calculate P&L, or contact brokers.
- Disabled signal runner commands must remain diagnostics-only until a future milestone explicitly approves real signal evaluation. They must not generate trading signals, order intents, simulated fills, P&L, portfolio accounting, or contact brokers.
- Analytical signal evaluator commands must remain broker-free and non-actionable. They may emit approved diagnostic condition states only; they must not generate trading signals, order intents, simulated fills, P&L, portfolio accounting, or contact brokers.
- Commodity universe commands must remain broker-free and security-proxy-only. They must not enable direct futures contracts, futures data requests, futures margin or roll modeling, signal evaluation, order intents, simulated fills, P&L, portfolio accounting, or contact brokers.
- Paper readiness orchestration may contact IBKR through read-only broker, account-summary, and historical-data requests only. It must run stages sequentially, require a real broker account summary, reject mock fallback as readiness success, keep `ALLOW_PAPER_ORDERS=false`, report `submitted_orders=false`, and keep direct futures out of scope.
- Data-quality gate commands must remain broker-free and local-file-only. They may fail or warn on snapshot quality, but they must not contact IBKR, evaluate signals, generate order intents, simulate fills, compute P&L, or enable direct futures.
- Evaluator comparison commands must remain broker-free and diagnostic-only. They may compare approved analytical condition counts across parameter candidates, but they must not rank trade recommendations, optimize P&L, generate trading signals, create order intents, simulate fills, route orders, or contact brokers.
- `paper-order-smoke` is the only current production module allowed to call IBKR paper order APIs. It must require `TRADING_MODE=paper`, `ALLOW_PAPER_ORDERS=true`, `ALLOW_LIVE_ORDERS=false`, localhost, paper port `7497` or `4002`, its dedicated client ID, explicit confirmation, SPY only, quantity `1`, STK/SMART/USD, `LMT`, `DAY`, max notional `$1,000`, and no live route. Keep the normal `PaperExecutor` refusing submissions.
- `alpha-shadow-run` must assemble complete cached XNYS sessions with the current completed live-bar prefix, prove overlap or structural boundary agreement, and apply freshness only to the newest current-live bar. It must fail closed on forming bars, gaps, conflicting overlaps, stale current data, or missing prior-session evidence.
- `alpha-shadow-daemon-summary` must remain offline-only. Five clean strict-live sessions on five distinct XNYS dates with stable release/config/strategy fingerprints unlock paper-daemon implementation work. Ten clean sessions across at least five dates and opening, midday, and closing windows unlock engineering-pilot eligibility. Delayed sessions never count.
- Strategy-driven `alpha-paper-run` and `alpha-campaign-run --mode paper` must require a fresh same-commit final-holdout report with `research_review_ready=true` and a fresh same-commit strict-live daemon summary with `engineering_pilot_ready=true`. Lifecycle-only `paper-order-smoke` remains exempt. No research or shadow report may automatically promote execution.
- Production `placeOrder` and `cancelOrder` text is allowlisted only to `src/trader/execution/paper_order_smoke.py`; `reqGlobalCancel` is forbidden throughout `src`.
- Do not commit `.env`, secrets, account numbers, API credentials, tokens, or sensitive logs.
- Missing or invalid config must fail closed.

## Architecture Boundary

Every possible order must flow through:

```text
signal -> trade plan -> risk validation -> execution router -> simulator or paper executor -> journal
```

Strategy modules may emit `Signal` objects only. Strategy code must not import from `trader.broker` or `trader.execution`, and it must never call broker execution code directly.

Normal execution attempts must pass through risk and `trader.execution.router`. The router may use the simulator in this phase and its paper executor remains a refusing stub. The separately gated `paper-order-smoke` module is the only production order-API exception. There is no live executor or autonomous paper daemon.

## Layout

- `src/trader/config.py`: strict environment loading and fail-closed safety settings.
- `src/trader/models.py`: serializable domain models.
- `src/trader/broker/`: isolated IBKR adapter skeletons.
- `src/trader/data/`: deterministic universe, snapshots, and cache helpers.
- `src/trader/strategy/`: pure signal generation.
- `src/trader/portfolio/`: signal-to-trade-plan conversion.
- `src/trader/risk/`: explicit risk decisions and guards.
- `src/trader/execution/`: router, simulator, refusing paper executor, and the gated paper-order smoke executor.
- `src/trader/reporting/`: JSON and Markdown journals.
- `tests/`: unit tests that do not require TWS or IB Gateway.
- `scripts/`: safe helper commands.

## Commands

Install locally:

```bash
python -m pip install --only-binary=:all: --require-hashes -r requirements.lock
python -m pip install --no-deps -e .
```

Run tests:

```bash
python -m pytest -p no:cacheprovider
```

Run lint:

```bash
python -m ruff check --no-cache src tests scripts
```

Optional type check:

```bash
python -m mypy src
```

Run safety preflight:

```bash
python -m trader.cli preflight
```

Run read-only broker probe:

```bash
scripts/check-ibapi.sh
python -m trader.cli broker-probe
```

Run a dry plan:

```bash
python -m trader.cli plan --strategy momentum --dry-run
```

Run offline analytical signal evaluation:

```bash
python -m trader.cli signal-evaluate --symbols SPY,AAPL
scripts/run-signal-evaluate.sh
```

Run offline data-quality and evaluator comparison gates:

```bash
python -m trader.cli data-quality-gate --symbols SPY,AAPL,GLD,USO,DBA
scripts/run-data-quality-gate.sh
python -m trader.cli evaluator-compare --symbols SPY,AAPL,GLD,USO,DBA
scripts/run-evaluator-compare.sh
```

Run read-only paper readiness orchestration:

```bash
python -m trader.cli paper-readiness-run
scripts/run-paper-readiness-run.sh
```

Run read-only alpha shadow orchestration:

```bash
python -m trader.cli alpha-shadow-run
scripts/run-alpha-shadow-run.sh
python -m trader.cli alpha-shadow-daemon-summary --report-glob='reports/alpha_shadow_daemon_*.json' --min-clean-sessions 5 --max-report-age-hours 168 --require-same-commit true
```

Run broker-free SPY research infrastructure only with local licensed files:

```bash
python -m trader.cli research-data-bakeoff --manifest <local-manifest.json>
python -m trader.cli research-vendor-decision --manifest <local-decision.json>
python -m trader.cli research-instrument-register --manifest research/instruments/spy_v1.json
python -m trader.cli research-experiment-register --spec research/experiments/spy_sma_2016_2025_v2.json --supersedes-spec research/experiments/spy_sma_2016_2025_v1.json
python -m trader.cli research-data-import-batch --source-dir <licensed-files> --vendor massive --kind minute_bars
python -m trader.cli research-data-derive
python -m trader.cli research-catalog-load --price-view split_adjusted_signal
python -m trader.cli research-backtest --symbol SPY
python -m trader.cli research-experiment-run --spec research/experiments/spy_sma_2016_2025_v2.json --phase development
```

Run repository safety scans:

```bash
python scripts/check_order_api_allowlist.py
python scripts/check_no_sensitive_artifacts.py
```

Run the gated paper-order smoke rehearsal only after a passing alpha shadow run:

```bash
python -m trader.cli paper-order-smoke --symbol SPY --quantity 1 --transmit false --confirm PAPER_SMOKE_SPY_1
ALLOW_PAPER_ORDERS=true scripts/run-paper-order-smoke.sh
```

## Definition Of Done

- Repo state and existing files are inspected before edits.
- Safety boundaries remain intact.
- Strategy code stays pure and broker-free.
- Tests are added or updated for changed behavior.
- `python -m pytest -p no:cacheprovider` passes.
- `python -m ruff check --no-cache src tests scripts` passes.
- `python -m mypy src` passes.
- `git diff --check` passes.
- Global order-API and sensitive-artifact scans pass.
- CLI commands touched by the change are run.
- Docs are updated when workflow, config, or safety behavior changes.
- Broker connectivity changes prove clean disconnects, masked account output, no order routing, and continued paper-executor refusal.

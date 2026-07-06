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
- `paper-order-smoke` is the only current production command allowed to call IBKR paper order APIs. It must require `TRADING_MODE=paper`, `ALLOW_PAPER_ORDERS=true`, `ALLOW_LIVE_ORDERS=false`, `IBKR_HOST=127.0.0.1`, `IBKR_PORT=7497`, `IBKR_CLIENT_ID=21`, explicit confirmation, SPY only, quantity `1`, STK/SMART/USD, `LMT`, `DAY`, max notional `$1,000`, and no live route. Keep the existing `PaperExecutor` refusing submissions for all normal router paths.
- `alpha-shadow-daemon-summary` must remain offline-only. It may read ignored local `alpha_shadow_daemon` reports and heartbeat files, but it must not contact IBKR, enable paper orders, invoke order APIs, generate order intents, calculate P&L, or expand commodity execution.
- Do not commit `.env`, secrets, account numbers, API credentials, tokens, or sensitive logs.
- Missing or invalid config must fail closed.

## Architecture Boundary

Every possible order must flow through:

```text
signal -> trade plan -> risk validation -> execution router -> simulator or paper executor -> journal
```

Strategy modules may emit `Signal` objects only. Strategy code must not import from `trader.broker` or `trader.execution`, and it must never call broker execution code directly.

All execution attempts must pass through risk and `trader.execution.router`. The router may use the simulator in this phase. The paper executor is a refusing stub. There is no live executor.

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
python -m pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Run lint:

```bash
ruff check .
```

Optional type check:

```bash
mypy src
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
- `pytest` passes.
- `ruff check .` passes.
- CLI commands touched by the change are run.
- Docs are updated when workflow, config, or safety behavior changes.
- Broker connectivity changes prove clean disconnects, masked account output, no order routing, and continued paper-executor refusal.

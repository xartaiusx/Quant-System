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
- `src/trader/execution/`: router, simulator, and refusing paper executor.
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

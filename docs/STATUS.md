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

## Current Blockers

- Before a real broker connection: `ibapi` must be installed and importable.
- Before market-data diagnostics: a successful read-only current-time broker probe is required.
- Paper execution remains blocked by `PaperExecutor`.
- Live trading remains impossible.

## Next Recommended Steps

1. Install the optional broker extra and run a real paper TWS / IB Gateway `broker-probe`.
2. Add read-only market-data subscription diagnostics behind explicit flags after a successful current-time probe.
3. Write a paper-execution activation proposal before changing `PaperExecutor` to submit anything.

# Implementation Plan

## Repository Baseline

- Current repository: `/home/artaius/Documents/GitHub/Quant-System`
- Git state: initialized Git repository on `main` with no commits yet.
- Existing files before scaffold: `.git/` only.
- Project status: empty repository ready for initial foundation.

## Reference Design Inputs

- Interactive Brokers TWS API docs: TWS and IB Gateway expose a socket API after user login; TWS paper defaults to `127.0.0.1:7497`, TWS live defaults to `7496`, IB Gateway paper defaults to `4002`, and IB Gateway live defaults to `4001`.
- Interactive Brokers TWS API docs: TWS API access must be enabled in TWS settings; Read-Only API is an additional order-safety control.
- QuantConnect / LEAN Algorithm Framework: keep strategy responsibilities separated into universe selection, alpha/signal generation, portfolio construction, risk management, execution, and reporting.
- OpenAI Codex guidance: keep repo instructions explicit in `AGENTS.md`, provide runnable commands, and make controlled changes validated by tests.

## Core Safety Invariant

Strategy code may propose trades. Strategy code must never directly place orders. Every possible order must flow through:

```text
signal -> trade plan -> risk validation -> execution router -> simulator or paper executor -> journal
```

Initial version restrictions:

- Dry-run behavior is the default.
- Paper trading is the only trading mode represented by broker configuration.
- Live trading is explicitly rejected even if requested.
- `ALLOW_LIVE_ORDERS=true` is rejected.
- `ALLOW_PAPER_ORDERS` defaults to `false`.
- Paper executor exists only as a refusing stub.
- No live executor exists.
- Market orders are not supported.
- Missing or invalid config fails closed.
- Secrets, account numbers, credentials, tokens, `.env`, and sensitive logs are ignored and must not be committed.

## Implementation Order

1. Create the Python `src` layout, packaging metadata, `.gitignore`, `.env.example`, and package/module placeholders.
2. Add `AGENTS.md` with purpose, safety rules, command list, architecture boundaries, and definition of done.
3. Implement strict config loading and validation with masked reporting.
4. Implement serializable typed domain models.
5. Add a Typer CLI shell for preflight, account, probe, plan, simulate, and status commands.
6. Add isolated IBKR broker adapter skeletons that never place orders.
7. Add pure strategy modules that emit signals only.
8. Add portfolio construction that converts signals into trade plans without execution.
9. Add risk rules, sizing helpers, and fail-closed guards.
10. Add execution router, simulator, and refusing paper executor.
11. Add JSON and Markdown journaling/report helpers under `reports/`.
12. Add focused tests for config, models, strategy, portfolio, risk, router, simulator, and CLI import.
13. Add README and safety/runbook/broker/strategy/status docs.
14. Add safe shell scripts for test, lint, preflight, dry-plan, and market-probe workflows.
15. Run validation: `pytest`, `ruff check .`, `python -m trader.cli --help`, `python -m trader.cli status`, and `python -m trader.cli plan --strategy momentum --dry-run`.

## Completion Criteria

- All requested files exist.
- Unit tests pass without TWS or IB Gateway.
- Lint passes.
- CLI can run from an editable install.
- Reports never include secrets or full account identifiers.
- Documentation makes intentional limitations obvious.

## Milestone 2 - Read-only TWS / IB Gateway connection probe

Baseline before edits:

- Repository is already initialized with the safety-first Python scaffold.
- Current broker layer is a preflight skeleton and does not open a socket.
- Config already rejects live mode, live-order activation, and live ports `7496` and `4001`.
- Paper executor is a refusing stub and must remain blocked.
- Tests currently use deterministic mocks and do not require TWS or IB Gateway.

Implementation plan:

1. Extend config with broker kind and bounded IBKR connect/request timeouts while preserving localhost-only and live-port rejection.
2. Add typed broker diagnostic models that mask managed accounts and always report order routing disabled.
3. Replace the IBKR skeleton with a read-only `EClient` / `EWrapper` adapter that imports `ibapi` lazily, runs the network loop in a background thread, captures callbacks with thread-safe events, and times out cleanly.
4. Add broker-probe reporting that writes JSON and Markdown files under `reports/` with a no-order guarantee.
5. Update CLI commands so `preflight` can optionally connect, `broker-probe` performs the read-only current-time and account discovery probe, and account/positions commands clearly distinguish mock fallback from broker data.
6. Add tests for missing `ibapi`, timeout/unavailable socket handling, live-port rejection, account masking, report serialization, CLI behavior, static no-`placeOrder` guarantees, and continued paper-executor refusal.
7. Update broker setup, runbook, safety, status, README, AGENTS guidance, and safe helper scripts for the new read-only workflow.

Completion criteria:

- No order placement, order modification, or order cancellation APIs are invoked.
- Live trading and live ports remain rejected.
- Paper execution remains disabled.
- Unit tests pass without a real TWS or IB Gateway session.
- CLI broker failures are structured and readable, with no normal-path traceback.
- Validation includes editable install, tests, lint, typecheck, CLI smoke commands, broker probe, and whitespace check.

## Milestone 3 - IBKR API installation support and real read-only probe readiness

Baseline before edits:

- Milestone 2 added a safe read-only broker probe with optional `ibapi` imports.
- `pyproject.toml` already keeps `ibapi` in the optional `broker` extra rather than the default install.
- Default `.venv/bin/python -m pip install -e ".[dev]"` remains the required baseline install path.
- `ibapi` is not currently available in the local venv, so broker-probe stops before opening a socket.
- Paper execution remains blocked and live trading remains rejected.

Implementation plan:

1. Keep the default install free of broker dependencies and keep the optional `broker` extra as the documented official `ibapi` path.
2. Add explicit broker-probe report fields for `ibapi_import_error`, `connection_attempted`, `failure_stage`, boolean no-order guarantee, and order-routing-disabled status.
3. Improve broker-probe CLI output so operators can quickly distinguish missing dependency, socket/connect problems, timeout, current-time success, masked managed accounts, and the no-order guarantee.
4. Add helper scripts for checking `ibapi` and for running connection preflight plus broker-probe without installing anything automatically.
5. Update setup/runbook/status docs with exact paper TWS and paper IB Gateway readiness checklists, expected outputs, and troubleshooting.
6. Add tests for new report fields, missing dependency stage, mocked successful current-time and managed-account response, CLI behavior, masking, live-port rejection, paper-executor refusal, and static no-`placeOrder` usage.

Completion criteria:

- Default editable dev install still succeeds.
- Missing `ibapi` produces `failure_stage=dependency_check`, `connection_attempted=false`, and a written report.
- Mocked successful broker probe proves read-only current-time and managed-account handling without TWS.
- CLI output and reports say order routing is disabled and no order APIs are invoked.
- Tests, lint, typecheck, CLI smoke, broker-probe, helper scripts, and whitespace checks pass.

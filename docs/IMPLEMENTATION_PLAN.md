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

## Milestone 5 - Read-only market-data diagnostics

Baseline before edits:

- Milestone 4 / v0.2.0 completed the read-only IB Gateway broker-probe lifecycle.
- IB Gateway paper is expected on `IBKR_HOST=127.0.0.1`, `IBKR_PORT=4002`, `BROKER_KIND=ib_gateway`, `TRADING_MODE=paper`.
- `ALLOW_PAPER_ORDERS=false` and `ALLOW_LIVE_ORDERS=false` remain hard safety defaults.
- Broker-probe must pass before live market-data diagnostics are attempted.
- Unit tests must not require TWS or IB Gateway.

Exact files expected to change:

- `docs/IMPLEMENTATION_PLAN.md`
- `src/trader/models.py`
- `src/trader/broker/ibkr_client.py`
- `src/trader/cli.py`
- `tests/test_broker_client.py`
- `README.md`
- `docs/RUNBOOK.md`
- `docs/BROKER_SETUP.md`
- `docs/SAFETY.md`
- `docs/STATUS.md`
- `AGENTS.md`
- `scripts/run-market-probe.sh`

IBKR API calls to use:

- `reqContractDetails`
- `reqMarketDataType`
- `reqMktData`
- `cancelMktData`
- `reqHistoricalData`
- `cancelHistoricalData`
- `disconnect`

IBKR API calls explicitly forbidden:

- `placeOrder`
- `cancelOrder`
- `reqGlobalCancel`
- `exerciseOptions`
- `replaceFA`
- any order submission, order modification, order cancellation, or market-order API.

Callbacks to capture:

- `contractDetails`
- `contractDetailsEnd`
- `marketDataType`
- `tickPrice`
- `tickSize`
- `tickString` when useful
- `historicalData`
- `historicalDataEnd`
- `error`
- `connectionClosed` when available

New models to add in `src/trader/models.py`:

- `ContractResolutionResult`
- `MarketDataTick`
- `MarketDataTypeInfo`
- `QuoteSnapshot`
- `SpreadDiagnostic`
- `HistoricalBar`
- `HistoricalDataDiagnostic`
- `MarketDataDiagnosticReport`

CLI behavior:

- Add `python -m trader.cli market-probe`.
- Default symbols: `SPY,AAPL`.
- Default market data type: `delayed`.
- Supported data types: `live`, `frozen`, `delayed`, `delayed_frozen`.
- Map data types to IBKR codes: `live=1`, `frozen=2`, `delayed=3`, `delayed_frozen=4`.
- Do not request live data unless the user explicitly passes `--data-type live`.
- Add `--historical` for a small read-only historical bar request.
- Add `--timeout` for bounded connection/request waits.
- CLI output must show connection/config status, requested symbols/data type, contract resolution, received market-data type, bid/ask/last/close and sizes when available, spread and spread bps when available, quote timestamp/age/staleness, historical bar count, warnings/errors, report paths, and no-order guarantees.

Reporting behavior:

- Write `reports/market_probe_<timestamp>.json` and `.md`.
- Update `reports/latest_market_probe.json` and `.md`.
- Include config mode, host, port, client id, broker kind, symbols, requested data type, contract resolution, quote snapshots, spread diagnostics, historical summary, IBKR warnings/errors, final status, `order_routing_enabled=false`, and `no_order_guarantee=true`.
- Do not include secrets, full account identifiers, or broker credentials.

Read-only broker implementation:

- Reuse the existing `IBKRClient` connection lifecycle and safety checks.
- Add bounded contract resolution for SMART/USD stock contracts with optional primary exchange hints for `SPY`, `QQQ`, `AAPL`, `MSFT`, and `NVDA`.
- Continue probing remaining symbols when one symbol fails.
- Track active ticker and historical request ids and clean them up with `cancelMktData` and `cancelHistoricalData`.
- Keep historical defaults small: duration `1 D`, bar size `5 mins`, `TRADES`, `useRTH=1`, `keepUpToDate=false`.
- Treat IBKR farm/status codes `2104`, `2106`, `2107`, and `2158` as non-fatal warnings.
- Record permission, contract, timeout, and disconnect failures as structured diagnostics.

Tests to add:

- Market probe static scan proves no forbidden order APIs are called.
- Contract resolution success, failure, and ambiguity warning.
- Delayed market-data type request path and callback capture.
- Bid/ask/last/close tick aggregation and size capture.
- Spread and spread-bps calculation.
- Stale quote detection and missing bid/ask handling.
- Historical bars collection and `historicalDataEnd` completion.
- Timeout returns structured diagnostics.
- Non-fatal warnings do not fail the probe by themselves.
- Fatal contract/permission errors are recorded clearly.
- Report serialization.
- CLI `market-probe` runs with a mocked broker.
- Live ports remain rejected.
- Paper executor remains blocked.

Safety checks to preserve:

- No order APIs are added or invoked.
- `ALLOW_PAPER_ORDERS` remains `false` by default.
- `ALLOW_LIVE_ORDERS=true` remains rejected.
- Live ports `4001` and `7496` remain rejected and must not be used for connection attempts.
- Market-data diagnostics are explicit CLI actions only.
- Strategy, portfolio, risk, and execution paths must not consume broker market-data diagnostics automatically.

Validation commands:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/python -m trader.cli --help
.venv/bin/python -m trader.cli status
.venv/bin/python -m trader.cli broker-probe
.venv/bin/python -m trader.cli market-probe --symbols SPY,AAPL --data-type delayed || true
.venv/bin/python -m trader.cli market-probe --symbols SPY,AAPL --data-type delayed --historical || true
scripts/run-market-probe.sh || true
git diff --check
```

Completion criteria:

- Unit tests pass without TWS or IB Gateway.
- Broker-probe still succeeds when IB Gateway paper is running on `4002`.
- Market-probe writes JSON and Markdown reports.
- At least contract resolution plus one data path succeeds: quote data, market-data-type callback, or historical bars.
- Failures are structured and diagnostic.
- Order routing remains disabled, no-order guarantee remains true, paper execution remains blocked, and live trading remains rejected.

## Milestone 6 - Historical-data snapshot ingestion and readiness reporting

Baseline before edits:

- Milestone 5 / `v0.3.0-readonly-market-data` added read-only contract, quote, spread, and small historical-bar diagnostics.
- IB Gateway paper is expected on `IBKR_HOST=127.0.0.1`, `IBKR_PORT=4002`, `BROKER_KIND=ib_gateway`, `TRADING_MODE=paper`.
- `ALLOW_PAPER_ORDERS=false` and `ALLOW_LIVE_ORDERS=false` remain hard safety defaults.
- Broker-probe must pass before live historical snapshot ingestion is attempted.
- Unit tests must not require TWS or IB Gateway.

Files expected to change:

- `.gitignore`
- `data/.gitkeep`
- `docs/IMPLEMENTATION_PLAN.md`
- `src/trader/models.py`
- `src/trader/data/historical.py`
- `src/trader/broker/ibkr_client.py`
- `src/trader/cli.py`
- `src/trader/reporting/reports.py`
- `tests/test_broker_client.py`
- `README.md`
- `docs/RUNBOOK.md`
- `docs/BROKER_SETUP.md`
- `docs/SAFETY.md`
- `docs/STATUS.md`
- `AGENTS.md`
- `scripts/run-history-snapshot.sh`

New models to add in `src/trader/models.py`:

- `HistoricalSnapshotRequest`
- `HistoricalSnapshotBar`
- `HistoricalSnapshotManifest`
- `HistoricalSnapshotResult`
- `HistoricalDataQualityIssue`
- `HistoricalReadinessSummary`
- `HistoricalReadinessReport`

Broker methods:

- Add `request_historical_snapshot(symbol, duration, bar_size, what_to_show, use_rth, timeout)`.
- Add `request_historical_snapshots(symbols, duration, bar_size, what_to_show, use_rth, timeout)`.
- Reuse contract resolution, existing connection lifecycle, bounded timeouts, and historical callbacks.
- Use only `reqContractDetails`, `reqHistoricalData`, `cancelHistoricalData`, and `disconnect` for this milestone path.
- Call `cancelHistoricalData` only as cleanup for incomplete active historical requests.
- Keep requests sequential by default, with a small pacing delay between symbols.

CLI commands:

- `python -m trader.cli history-fetch --symbols SPY,AAPL --duration "1 D" --bar-size "5 mins" --what-to-show TRADES --use-rth 1`
- `python -m trader.cli history-readiness --latest`
- `python -m trader.cli history-snapshot --symbols SPY,AAPL --duration "1 D" --bar-size "5 mins" --what-to-show TRADES --use-rth 1`

Storage format:

- Store generated snapshots under `data/historical/<symbol>/<bar_size_slug>/<what_to_show>/<YYYYMMDDTHHMMSSZ>_bars.jsonl`.
- Store matching manifests beside each snapshot as `<YYYYMMDDTHHMMSSZ>_manifest.json`.
- JSONL bars include symbol, contract id, timestamp, open, high, low, close, volume, WAP when available, bar count when available, source, duration, bar size, what to show, and use RTH.
- Manifests include generated time, contract/config metadata, bar count, first/last bar time, timeout, IBKR messages, warnings, errors, `no_order_guarantee=true`, and `order_routing_enabled=false`.
- Generated snapshot files and reports remain ignored; only `data/.gitkeep` is tracked.

Validation checks:

- Timestamp parsing succeeds.
- Bars are sorted.
- Duplicate timestamps are counted.
- Timestamp gaps are summarized.
- OHLC values are numeric and internally consistent.
- Volume is non-negative.
- Bar count is above a minimal threshold.
- First and last timestamps are present.
- Snapshot recency is assessed.
- Empty or missing data is reported cleanly.

Report format:

- Write `reports/history_snapshot_<timestamp>.json` and `.md`.
- Write `reports/history_readiness_<timestamp>.json` and `.md`.
- Maintain `reports/latest_history_snapshot.json`, `.md`, `reports/latest_history_readiness.json`, and `.md`.
- Include mode, broker kind, host, port, client id, request parameters, symbols, snapshot paths, readiness summaries, per-symbol validation results, IBKR warnings/errors, `order_routing_enabled=false`, and `no_order_guarantee=true`.

Tests to add:

- Historical snapshot request, bar, and manifest serialization.
- Successful historical callback collection and `historicalDataEnd` completion.
- Timeout failure with structured diagnostics and cleanup cancellation.
- Static no-order API scan for historical paths.
- Readiness checks for sorted bars, duplicate timestamps, timestamp gaps, invalid OHLC, negative volume, empty bars, and partial success.
- Snapshot writer path and manifest creation.
- Report serialization and CLI mocked success paths.
- Live ports remain rejected and the paper executor remains blocked.

Safety scans:

```bash
grep -R "placeOrder" -n src tests docs scripts || true
grep -R "cancelOrder" -n src tests docs scripts || true
grep -R "reqGlobalCancel" -n src tests docs scripts || true
grep -R "ALLOW_PAPER_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "ALLOW_LIVE_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "4001\|7496" -n src tests docs scripts .env.example || true
git status --ignored --short
```

Validation commands:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/python -m trader.cli --help
.venv/bin/python -m trader.cli status
.venv/bin/python -m trader.cli broker-probe
.venv/bin/python -m trader.cli market-probe --symbols SPY,AAPL --data-type delayed --historical
.venv/bin/python -m trader.cli history-snapshot --symbols SPY,AAPL --duration "1 D" --bar-size "5 mins" --what-to-show TRADES --use-rth 1 || true
.venv/bin/python -m trader.cli history-readiness --latest || true
scripts/run-history-snapshot.sh || true
git diff --check
```

Completion criteria:

- Unit tests pass without TWS or IB Gateway.
- Broker-probe and market-probe still succeed when IB Gateway paper is running.
- `history-snapshot` requests bounded historical bars, writes local snapshots/manifests, and writes snapshot/readiness reports.
- `history-readiness --latest` produces a readiness report from latest local snapshots.
- Per-symbol readiness is `ready`, `partial`, or `failed` with structured warnings/errors.
- No order APIs are added or invoked.
- Paper execution remains blocked, live trading remains rejected, and generated snapshots/reports remain ignored.

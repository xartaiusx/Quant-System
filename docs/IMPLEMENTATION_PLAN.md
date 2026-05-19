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

## Milestone 7 - Offline historical snapshot loader and data adapter

Baseline before edits:

- Milestone 6 / `v0.4.0-readonly-history-snapshots` stores ignored JSONL bars and manifests under `data/historical/`.
- This milestone is broker-free and must not contact IBKR, import broker clients from loader code, or require IB Gateway.
- `ALLOW_PAPER_ORDERS=false`, `ALLOW_LIVE_ORDERS=false`, live-mode rejection, and live-port rejection remain unchanged.
- Unit tests must use fixture snapshot data and must not require `ibapi`, TWS, or IB Gateway.

Files expected to change:

- `docs/IMPLEMENTATION_PLAN.md`
- `src/trader/models.py`
- `src/trader/data/historical_loader.py`
- `src/trader/cli.py`
- `src/trader/reporting/reports.py`
- `tests/test_historical_loader.py`
- `README.md`
- `docs/RUNBOOK.md`
- `docs/SAFETY.md`
- `docs/STATUS.md`
- `AGENTS.md`
- `scripts/run-history-load.sh`

Loader design:

- Build a standard-library offline loader around stored snapshot JSONL and manifest files.
- Discover manifests and bars under `data/historical/<symbol>/<bar_size>/<what_to_show>/`.
- Load manifests first, then resolve and parse their matching bars files.
- Keep malformed lines as structured issues in non-strict mode and fail the dataset in strict mode.
- Normalize loaded bars into reusable in-memory records with parsed timestamps, numeric OHLCV values, typical price, dollar volume, and inferred interval seconds when possible.

Manifest discovery design:

- Scan `*_manifest.json` files beneath the historical root.
- Derive symbol, bar-size slug, what-to-show, and timestamp from the path and filename.
- Validate that the matching bars path exists and that manifest metadata is consistent with requested filters.
- Do not assume real local snapshots exist in tests; fixtures must create temporary manifests and JSONL files.

Latest snapshot selection rules:

- Default `history-load` behavior selects the latest matching snapshot per symbol.
- Selection can filter by `--symbols`, `--bar-size`, and `--what-to-show`.
- An explicit `--snapshot-timestamp` selects only that timestamp.
- Latest ordering prefers manifest `generated_at`, with path timestamp as a fallback.

Data validation rules:

- Required fields must be present for each bar.
- Timestamps must parse and datasets must be sorted after normalization.
- Duplicate timestamps, timestamp gaps, invalid OHLC, negative volume, empty datasets, stale snapshots, malformed JSONL lines, missing files, and bar-count mismatches produce structured diagnostics.
- Non-strict mode may return `partial` datasets; strict mode turns malformed or invalid records into failed loads.

Normalized dataset model:

- Add serializable models for snapshot index entries, load requests, normalized loaded bars, datasets, load issues, per-symbol load results, dataset summaries, and loader reports.
- Every loader report must include `broker_contacted=false`, `order_routing_enabled=false`, and `no_order_guarantee=true`.

CLI commands:

- `python -m trader.cli history-index`
- `python -m trader.cli history-load --symbols SPY,AAPL`
- `python -m trader.cli history-load --symbols SPY,AAPL --bar-size "5 mins" --what-to-show TRADES`
- `python -m trader.cli history-load --symbols SPY,AAPL --latest`
- `python -m trader.cli history-load --symbols SPY,AAPL --strict`
- `python -m trader.cli history-inspect --symbol SPY`

Reporting behavior:

- Write `reports/history_index_<timestamp>.json` and `.md`.
- Write `reports/history_load_<timestamp>.json` and `.md`.
- Maintain `reports/latest_history_index.json`, `.md`, `reports/latest_history_load.json`, and `.md`.
- Reports include requested symbols, base data path, selection filters, discovered snapshots, loaded datasets, validation issues, `broker_contacted=false`, `order_routing_enabled=false`, and `no_order_guarantee=true`.

Tests to add:

- Snapshot discovery, no-snapshot handling, latest selection, symbol/bar-size/what-to-show filtering, manifest loading, valid JSONL loading, missing manifest, missing bars file, malformed JSONL handling in strict and non-strict mode, duplicate timestamps, timestamp gaps, invalid OHLC, negative volume, bar-count mismatch, dataset summary, report serialization, CLI `history-index`, CLI `history-load`, CLI `history-inspect`, loader path no-broker import scan, no-order API scan, live-port rejection, and paper-executor refusal.

Safety checks:

- Do not add broker calls, socket connection attempts, order APIs, paper execution activation, or live trading.
- Confirm loader code and tests do not import `trader.broker`, `IBKRReadOnlyClient`, or `ibapi`.
- Keep generated reports and generated snapshots ignored.

Validation commands:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/python -m trader.cli --help
.venv/bin/python -m trader.cli status
.venv/bin/python -m trader.cli history-index || true
.venv/bin/python -m trader.cli history-load --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli history-inspect --symbol SPY || true
scripts/run-history-load.sh || true
grep -R "placeOrder" -n src tests docs scripts || true
grep -R "cancelOrder" -n src tests docs scripts || true
grep -R "reqGlobalCancel" -n src tests docs scripts || true
grep -R "ALLOW_PAPER_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "ALLOW_LIVE_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "4001\|7496" -n src tests docs scripts .env.example || true
grep -R "trader.broker" -n src/trader/data tests/test_historical_loader.py || true
grep -R "IBKRReadOnlyClient\|ibapi" -n src/trader/data tests/test_historical_loader.py || true
git diff --check
```

Completion criteria:

- Unit tests pass without IB Gateway.
- Loader tests use fixture snapshot data.
- `history-index`, `history-load`, and `history-inspect` work offline.
- Reports are written for local snapshot discovery and loading.
- Missing or malformed data produces structured diagnostics.
- No broker calls or order APIs are added.
- Paper execution remains blocked, live trading remains rejected, and generated reports/snapshots remain ignored.

## Milestone 8 - Broker-free backtest data adapter scaffold

Baseline before edits:

- Milestone 7 / `v0.5.0-offline-history-loader` loads ignored local JSONL snapshots into `HistoricalLoadedDataset` objects without contacting IBKR.
- This milestone remains broker-free and must not import broker clients, `ibapi`, or open any broker socket.
- It prepares normalized simulation-ready bar feeds only. It must not evaluate strategies, simulate orders, compute P&L, enable paper execution, or enable live trading.
- Unit tests must use fixture `HistoricalLoadedDataset` objects or temporary snapshot files and must not require IB Gateway.

Files expected to change:

- `docs/IMPLEMENTATION_PLAN.md`
- `src/trader/models.py`
- `src/trader/backtest/data_adapter.py`
- `src/trader/cli.py`
- `src/trader/reporting/reports.py`
- `tests/test_backtest_data_adapter.py`
- `README.md`
- `docs/RUNBOOK.md`
- `docs/SAFETY.md`
- `docs/STATUS.md`
- `AGENTS.md`
- `scripts/run-backtest-feed.sh`

Data adapter design:

- Consume one or more `HistoricalLoadedDataset` instances from the offline historical loader.
- Validate that inputs are loaded, non-empty, and broker-free.
- Normalize each loaded bar into a stable `BacktestBar` record with symbol, timestamp, OHLCV values, source snapshot timestamp, bars path, and manifest path.
- Build deterministic feed frames ordered by ascending timestamp.
- Preserve symbol identity and source metadata for every bar.
- Return structured diagnostics instead of throwing for empty or partial inputs.
- Keep the adapter independent from broker, strategy, execution, simulator, cost, and P&L modules.

Normalized bar/feed model:

- Add serializable models for `BacktestBar`, `BacktestFeedPoint`, `BacktestFeedFrame`, `BacktestDataFeed`, `BacktestDataAdapterRequest`, `BacktestDataAdapterIssue`, `BacktestDataFeedSummary`, and `BacktestDataAdapterReport`.
- Include `broker_contacted=false`, `order_routing_enabled=false`, and `no_order_guarantee=true` on feed summaries and reports.
- Include a report statement that no strategy evaluation, order simulation, or P&L calculation was performed.

Multi-symbol alignment rules:

- Default alignment mode is `union`, which includes every timestamp observed across all selected symbols.
- `intersection` includes only timestamps present for every selected symbol.
- Missing bars in `union` frames are explicit `null` values and counted in `missing_bars_by_symbol`.
- Duplicate timestamps are recorded per symbol as diagnostics and warnings.
- Frames and iteration order are deterministic.

Validation checks:

- Empty input fails cleanly.
- Empty datasets fail or produce partial status depending on the batch.
- Partial input datasets propagate partial feed status.
- Duplicate timestamps are counted by symbol.
- Frames must be sorted ascending.
- Bars must be keyed by requested symbol.
- Unsupported alignment modes are rejected by the CLI and model validation.

CLI commands:

- `python -m trader.cli backtest-feed --symbols SPY,AAPL`
- `python -m trader.cli backtest-feed --symbols SPY,AAPL --alignment union`
- `python -m trader.cli backtest-feed --symbols SPY,AAPL --alignment intersection`
- `python -m trader.cli backtest-feed --symbols SPY,AAPL --bar-size "5 mins" --what-to-show TRADES`

Reporting behavior:

- Write `reports/backtest_feed_<timestamp>.json` and `.md`.
- Maintain `reports/latest_backtest_feed.json` and `.md`.
- Reports include symbols requested, snapshot selection criteria, alignment mode, source datasets, total bars, frame count, first/last timestamp, missing bars by symbol, warnings/errors, feed status, and the explicit no-strategy/no-order/no-P&L statement.

Tests to add:

- Build feed from one dataset and multiple datasets.
- Verify union and intersection alignment behavior.
- Count missing bars by symbol and duplicate timestamps by symbol.
- Confirm frames are sorted and bars are keyed by symbol.
- Confirm empty and partial datasets produce structured diagnostics.
- Confirm summaries and reports serialize.
- Confirm `iter_feed_frames` is deterministic.
- Confirm CLI `backtest-feed` runs with fixture data.
- Confirm adapter path has no broker or `ibapi` imports and no order API usage.
- Confirm paper executor remains blocked and live ports remain rejected.

Safety checks:

- Do not add broker calls, socket connection attempts, `trader.broker` imports, `ibapi` imports, order APIs, strategy evaluation, order simulation, P&L calculation, paper execution activation, or live trading.
- Keep generated reports and generated snapshots ignored.

Validation commands:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/python -m trader.cli --help
.venv/bin/python -m trader.cli status
.venv/bin/python -m trader.cli history-index || true
.venv/bin/python -m trader.cli history-load --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli backtest-feed --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli backtest-feed --symbols SPY,AAPL --alignment intersection || true
scripts/run-backtest-feed.sh || true
grep -R "placeOrder" -n src tests docs scripts || true
grep -R "cancelOrder" -n src tests docs scripts || true
grep -R "reqGlobalCancel" -n src tests docs scripts || true
grep -R "ALLOW_PAPER_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "ALLOW_LIVE_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "4001\|7496" -n src tests docs scripts .env.example || true
grep -R "trader.broker" -n src/trader/backtest tests/test_backtest_data_adapter.py || true
grep -R "IBKRReadOnlyClient\|ibapi" -n src/trader/backtest tests/test_backtest_data_adapter.py || true
git diff --check
```

Completion criteria:

- Unit tests pass without IB Gateway.
- Adapter tests use fixture loaded datasets or temporary offline snapshots.
- `backtest-feed` works offline with local snapshots when present.
- Union and intersection alignment work.
- Missing bars are explicit and counted.
- Feed frames are deterministic and sorted.
- Reports are written and state that no strategy evaluation, order simulation, or P&L calculation was performed.
- No broker calls or order APIs are added.
- Paper execution remains blocked, live trading remains rejected, and generated reports remain ignored.

## Milestone 9 - Broker-free backtest engine skeleton

Baseline before edits:

- Milestone 8 / `v0.6.0-broker-free-backtest-feed` builds a broker-free `BacktestDataFeed` from local historical snapshots.
- This milestone remains offline-only and must not import broker clients, `ibapi`, strategy modules, execution modules, or open any broker socket.
- It creates the deterministic engine loop only. It must not evaluate strategies, create signals, simulate orders, compute fills, calculate P&L, maintain portfolio accounting, enable paper execution, or enable live trading.
- Unit tests must use fixture `BacktestDataFeed` objects or temporary offline snapshots and must not require IB Gateway.

Files expected to change:

- `docs/IMPLEMENTATION_PLAN.md`
- `src/trader/models.py`
- `src/trader/backtest/engine.py`
- `src/trader/cli.py`
- `src/trader/reporting/reports.py`
- `tests/test_backtest_engine.py`
- `README.md`
- `docs/RUNBOOK.md`
- `docs/SAFETY.md`
- `docs/STATUS.md`
- `AGENTS.md`
- `scripts/run-backtest-run.sh`

Engine loop design:

- Accept a `BacktestDataFeed` created by the offline adapter.
- Validate that the feed is ready or partial and contains frames before replay.
- Iterate frames using deterministic timestamp ordering.
- Record frame-level observations only: timestamp, frame index, symbols present, symbols missing, bar count, and missing bar count.
- Return structured diagnostics for empty or failed feeds without raising unhandled exceptions.
- Keep the engine independent from broker, strategy, execution, risk, portfolio, metrics, cost, and P&L modules.

Frame replay semantics:

- Replay every sorted frame exactly once.
- Treat `BacktestFeedStatus.READY` as a completed run when frames exist.
- Treat `BacktestFeedStatus.PARTIAL` as a completed run with warnings when frames exist.
- Treat `BacktestFeedStatus.FAILED` or empty frames as failed.
- Preserve feed warnings and missing-bar counts in the run diagnostics.
- Do not mutate the input feed.

Diagnostics model:

- Add serializable models for `BacktestRunRequest`, `BacktestFrameObservation`, `BacktestRunDiagnostics`, `BacktestRunResult`, and `BacktestRunReport`.
- Include `broker_contacted=false`, `order_routing_enabled=false`, `no_order_guarantee=true`, `strategy_evaluated=false`, `orders_simulated=false`, and `pnl_calculated=false`.
- Include run status values `completed`, `partial`, and `failed`.

CLI behavior:

- Add `python -m trader.cli backtest-run --symbols SPY,AAPL`.
- Support `--alignment union`, `--alignment intersection`, `--bar-size`, and `--what-to-show`.
- The command loads latest snapshots through `history-load`, builds a feed through `backtest-feed` internals, runs the engine loop, writes a report, and prints run diagnostics.
- The command must clearly state broker-free operation and that no strategy evaluation, order simulation, or P&L calculation was performed.

Reporting behavior:

- Write `reports/backtest_run_<timestamp>.json` and `.md`.
- Maintain `reports/latest_backtest_run.json` and `.md`.
- Reports include symbols requested, selection criteria, alignment mode, feed summary, run status, frame count, total bars observed, first/last timestamp, observations count, missing bars by symbol, frames with missing bars, warnings/errors, and safety flags.
- Reports include the explicit statement: "This run replayed data frames only. No strategy evaluation, order simulation, broker routing, or P&L calculation was performed."

Tests to add:

- Engine runs on ready feed.
- Engine handles partial feed with warnings.
- Engine fails cleanly on empty feed.
- Engine fails cleanly on failed feed.
- Frame observations are sorted by timestamp.
- Frame observations record present and missing symbols.
- Run diagnostics record frame count, total bars observed, first/last timestamp, missing bars by symbol, and frames with missing bars.
- Result and report serialize cleanly.
- CLI `backtest-run` runs with fixture data.
- Engine path has no broker, `ibapi`, or strategy imports.
- Engine path contains no forbidden order API usage.
- Safety flags remain false for strategy evaluation, order simulation, and P&L calculation.
- Paper executor remains blocked and live ports remain rejected.

Safety checks:

- Do not add broker calls, socket connection attempts, `trader.broker` imports, `ibapi` imports, strategy imports, order APIs, strategy evaluation, order simulation, fill simulation, P&L calculation, portfolio accounting, risk-based execution logic, paper execution activation, or live trading.
- Keep generated reports and generated snapshots ignored.

Validation commands:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/python -m trader.cli --help
.venv/bin/python -m trader.cli status
.venv/bin/python -m trader.cli history-index || true
.venv/bin/python -m trader.cli history-load --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli backtest-feed --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli backtest-run --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli backtest-run --symbols SPY,AAPL --alignment intersection || true
scripts/run-backtest-run.sh || true
grep -R "placeOrder" -n src tests docs scripts || true
grep -R "cancelOrder" -n src tests docs scripts || true
grep -R "reqGlobalCancel" -n src tests docs scripts || true
grep -R "ALLOW_PAPER_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "ALLOW_LIVE_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "4001\|7496" -n src tests docs scripts .env.example || true
grep -R "trader.broker" -n src/trader/backtest tests/test_backtest_engine.py || true
grep -R "IBKRReadOnlyClient\|ibapi" -n src/trader/backtest tests/test_backtest_engine.py || true
grep -R "trader.strategy" -n src/trader/backtest tests/test_backtest_engine.py || true
grep -R "place_order\|submit_order\|fill\|portfolio\|pnl\|P&L\|profit\|loss" -n src/trader/backtest tests/test_backtest_engine.py || true
git diff --check
```

Completion criteria:

- Unit tests pass without IB Gateway.
- Engine tests use fixture `BacktestDataFeed` objects.
- `backtest-run` works offline with local snapshots when present.
- Engine iterates frames deterministically and records frame observations.
- Run diagnostics and reports are written.
- No broker calls or order APIs are added.
- No strategy evaluation, order simulation, fill simulation, P&L calculation, portfolio accounting, or risk-based execution logic is added.
- Paper execution remains blocked, live trading remains rejected, and generated reports remain ignored.

## Milestone 10 - Broker-free strategy interface contract scaffold

Baseline before edits:

- Milestone 9 / `v0.7.0-broker-free-backtest-engine` replays offline `BacktestDataFeed` frames and reports diagnostics with `strategy_evaluated=false`.
- This milestone is interface design only. It must not wire real strategies into `backtest-run`, emit trading signals, create order intents, simulate fills, compute P&L, maintain portfolio accounting, call broker code, activate paper execution, or enable live trading.
- Unit tests must use fixture `BacktestFeedFrame` / `BacktestDataFeed` objects or temporary offline snapshots and must not require IB Gateway or `ibapi`.

Files expected to change:

- `docs/IMPLEMENTATION_PLAN.md`
- `src/trader/models.py`
- `src/trader/strategy/interface.py`
- `src/trader/cli.py`
- `src/trader/reporting/reports.py`
- `tests/test_strategy_interface.py`
- `README.md`
- `docs/RUNBOOK.md`
- `docs/SAFETY.md`
- `docs/STATUS.md`
- `AGENTS.md`
- `scripts/run-strategy-contract.sh`

Strategy protocol/interface design:

- Define immutable metadata for future strategies: name, version, description, parameters, supported bar sizes, required fields, and `broker_required=false`.
- Define a frame context that mirrors a single `BacktestFeedFrame`: timestamp, frame index, available symbols, missing symbols, bars keyed by symbol, feed metadata, and alignment mode.
- Define a diagnostic response that records a frame observation and hard-codes safety flags: `evaluated=false`, `generated_signals=false`, `generated_orders=false`, `orders_simulated=false`, `pnl_calculated=false`, `broker_contacted=false`, `order_routing_enabled=false`, and `no_order_guarantee=true`.
- Keep the interface path independent from `trader.broker`, `ibapi`, execution, portfolio, risk, and existing signal-generating strategies.

Frame context model:

- Build contexts from feed frames without mutating the feed.
- Preserve timestamp, frame index, available symbols, missing symbols, bars by symbol, feed status, alignment mode, feed frame count, and source summary.
- Validate that required bar fields are present in available bars and report missing fields as diagnostics only.

No-op strategy behavior:

- Provide a `NoOpStrategyContract` that accepts frame contexts and emits diagnostics only.
- The no-op contract records that the frame was observed, reports available and missing symbols, and emits no signals or orders.
- The no-op contract performs no P&L calculation, fill simulation, order simulation, or portfolio accounting.

Diagnostics model:

- Add serializable models for `StrategyParameterSpec`, `StrategyMetadata`, `StrategyFrameContext`, `StrategyContractDiagnostic`, `StrategyContractValidationRequest`, `StrategyContractValidationResult`, and `StrategyContractReport`.
- Include warnings/errors and all safety flags on both per-frame diagnostics and report-level results.

CLI behavior:

- Add `python -m trader.cli strategy-contract --symbols SPY,AAPL`.
- Support `--alignment union`, `--alignment intersection`, `--bar-size`, and `--what-to-show`.
- The command loads local snapshots through the offline historical loader, builds a broker-free feed, validates the no-op strategy contract, writes a report, and prints contract diagnostics.
- The command must clearly state that it validates the interface contract only and does not perform real strategy evaluation.

Reporting behavior:

- Write `reports/strategy_contract_<timestamp>.json` and `.md`.
- Maintain `reports/latest_strategy_contract.json` and `.md`.
- Reports include strategy metadata, symbols requested, feed summary, frame context sample summary, validation result, diagnostics, warnings/errors, and all safety flags.
- Reports include the explicit statement: "This command validates the strategy interface contract only. No real strategy evaluation, signal generation, order simulation, broker routing, or P&L calculation was performed."

Tests to add:

- Strategy metadata, frame context, diagnostic, result, and report models serialize cleanly.
- No-op metadata validates.
- No-op strategy accepts a frame context and emits diagnostics only.
- Safety flags remain false for evaluation, signal generation, order generation, order simulation, and P&L calculation.
- Frame context construction preserves timestamps, available symbols, and missing symbols.
- CLI `strategy-contract` runs with fixture data.
- Strategy interface path has no broker or `ibapi` imports.
- Strategy interface path contains no forbidden order API usage.
- Paper executor remains blocked and live ports remain rejected.

Safety checks:

- Do not add broker calls, socket connection attempts, `trader.broker` imports, `ibapi` imports, order APIs, real strategy evaluation, buy/sell/hold signal generation, order simulation, fill simulation, P&L calculation, portfolio accounting, paper execution activation, or live trading.
- Keep generated reports and generated snapshots ignored.

Validation commands:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/python -m trader.cli --help
.venv/bin/python -m trader.cli status
.venv/bin/python -m trader.cli history-index || true
.venv/bin/python -m trader.cli history-load --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli backtest-feed --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli backtest-run --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli strategy-contract --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli strategy-contract --symbols SPY,AAPL --alignment intersection || true
scripts/run-strategy-contract.sh || true
grep -R "placeOrder" -n src tests docs scripts || true
grep -R "cancelOrder" -n src tests docs scripts || true
grep -R "reqGlobalCancel" -n src tests docs scripts || true
grep -R "ALLOW_PAPER_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "ALLOW_LIVE_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "4001\|7496" -n src tests docs scripts .env.example || true
grep -R "trader.broker" -n src/trader/strategy tests/test_strategy_interface.py || true
grep -R "IBKRReadOnlyClient\|ibapi" -n src/trader/strategy tests/test_strategy_interface.py || true
grep -R "place_order\|submit_order\|fill\|portfolio\|pnl\|P&L\|profit\|loss" -n src/trader/strategy tests/test_strategy_interface.py || true
git diff --check
```

Completion criteria:

- Unit tests pass without IB Gateway.
- Strategy interface tests use fixture frames or feeds.
- `strategy-contract` works offline with local snapshots when present.
- The no-op strategy emits diagnostics only.
- Reports are written and state that no real strategy evaluation, signal generation, order simulation, broker routing, or P&L calculation was performed.
- No broker calls or order APIs are added.
- Paper execution remains blocked, live trading remains rejected, and generated reports remain ignored.

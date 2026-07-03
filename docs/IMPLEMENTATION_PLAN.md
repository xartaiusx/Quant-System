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

## Milestone 11 - Broker-free inert strategy runner scaffold

Baseline before edits:

- Milestone 10 / `v0.8.0-broker-free-strategy-contract` defines the broker-free no-op strategy contract and `strategy-contract` CLI.
- `backtest-run` and `strategy-contract` are offline-only and operate from local historical snapshots.
- This milestone adds runner plumbing only. It must not evaluate real strategies, generate buy/sell/hold signals, create order intents, simulate orders or fills, calculate P&L, perform portfolio accounting, call brokers, activate paper execution, or enable live trading.
- Unit tests must use fixture `BacktestDataFeed` objects or temporary offline snapshots and must not require IB Gateway or `ibapi`.

Files expected to change:

- `docs/IMPLEMENTATION_PLAN.md`
- `src/trader/models.py`
- `src/trader/strategy/runner.py`
- `src/trader/cli.py`
- `src/trader/reporting/reports.py`
- `tests/test_strategy_runner.py`
- `README.md`
- `docs/RUNBOOK.md`
- `docs/SAFETY.md`
- `docs/STATUS.md`
- `AGENTS.md`
- `scripts/run-strategy-runner.sh`

Inert runner design:

- Consume a broker-free `BacktestDataFeed`.
- Iterate feed frames in deterministic timestamp order.
- Build a `StrategyFrameContext` for each frame using the existing no-op contract context helper.
- Invoke only the `NoOpStrategyContract.observe()` diagnostic path.
- Record per-frame diagnostic results and runner-level counts for frame count, contexts built, diagnostics emitted, first/last timestamp, and missing-symbol summaries.
- Keep the runner path independent from `trader.broker`, `ibapi`, execution, portfolio, risk, and real signal-generating strategy modules.

No-op strategy diagnostic flow:

- The runner calls only the existing no-op strategy contract.
- Each frame emits diagnostics that say the frame was observed.
- Required report/result flags are fixed: `diagnostic_only=true`, `noop_strategy_observed=true`, `real_strategy_evaluated=false`, `generated_signals=false`, `generated_orders=false`, `orders_simulated=false`, `fills_simulated=false`, `pnl_calculated=false`, `portfolio_accounting=false`, `broker_contacted=false`, `order_routing_enabled=false`, and `no_order_guarantee=true`.
- No real strategy hooks, signals, order intents, simulated fills, portfolio accounting, or P&L fields beyond explicit false safety flags are introduced.

Frame context handling:

- Preserve timestamp, frame index, available symbols, missing symbols, bars by symbol, feed status, alignment mode, feed frame count, and feed summary.
- Missing symbols are recorded per frame and aggregated by symbol.
- Partial feeds may run with warnings; failed or empty feeds fail cleanly with structured errors.
- The runner must not mutate the source feed.

Result and report models:

- Add serializable models for `InertStrategyRunnerRequest`, `InertStrategyFrameResult`, `InertStrategyRunnerDiagnostics`, `InertStrategyRunnerResult`, and `InertStrategyRunnerReport`.
- Include strategy metadata, requested symbols, alignment mode, counts, timestamps, missing-symbol summaries, warnings/errors, final status, and all required safety flags.

CLI behavior:

- Add `python -m trader.cli strategy-runner --symbols SPY,AAPL`.
- Support `--alignment union`, `--alignment intersection`, `--bar-size`, and `--what-to-show`.
- The command loads local snapshots through the offline historical loader, builds a broker-free feed, runs the inert no-op diagnostic runner, writes a report, and prints runner diagnostics.
- The command must clearly state that it is diagnostic-only and does not perform real strategy evaluation.

Reporting behavior:

- Write `reports/strategy_runner_<timestamp>.json` and `.md`.
- Maintain `reports/latest_strategy_runner.json` and `.md`.
- Reports include symbols requested, snapshot criteria, alignment mode, source feed summary, strategy metadata, runner status, frame count, contexts built, diagnostics emitted, first/last timestamp, missing-symbol summaries, warnings/errors, and all safety flags.
- Reports include the explicit statement: "This run exercised the no-op strategy contract only. No real strategy evaluation, signal generation, order simulation, broker routing, portfolio accounting, or P&L calculation was performed."

Tests to add:

- Runner runs on ready feed and handles partial feed warnings.
- Runner fails cleanly on empty and failed feeds.
- Runner builds one frame context and emits one diagnostic per frame.
- Runner records first/last timestamp and missing symbols.
- Result and report serialize cleanly.
- CLI `strategy-runner` runs with fixture data.
- Runner path has no broker or `ibapi` imports.
- Runner path contains no forbidden order API usage and does not generate real signals, orders, fills, portfolio accounting, or P&L.
- Required safety flags remain fixed.
- Paper executor remains blocked and live ports remain rejected.

Safety checks:

- Do not add broker calls, socket connection attempts, `trader.broker` imports, `ibapi` imports, order APIs, real strategy evaluation, buy/sell/hold signal generation, order-intent generation, order simulation, fill simulation, P&L calculation, portfolio accounting, paper execution activation, or live trading.
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
.venv/bin/python -m trader.cli strategy-runner --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli strategy-runner --symbols SPY,AAPL --alignment intersection || true
scripts/run-strategy-runner.sh || true
grep -R "placeOrder" -n src tests docs scripts || true
grep -R "cancelOrder" -n src tests docs scripts || true
grep -R "reqGlobalCancel" -n src tests docs scripts || true
grep -R "ALLOW_PAPER_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "ALLOW_LIVE_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "4001\|7496" -n src tests docs scripts .env.example || true
grep -R "trader.broker" -n src/trader/strategy src/trader/backtest tests/test_strategy_runner.py || true
grep -R "IBKRReadOnlyClient\|ibapi" -n src/trader/strategy src/trader/backtest tests/test_strategy_runner.py || true
grep -R "place_order\|submit_order\|order_intent\|fill\|portfolio\|pnl\|P&L\|profit\|loss" -n src/trader/strategy tests/test_strategy_runner.py || true
grep -R "buy\|sell\|hold\|signal" -n src/trader/strategy/runner.py tests/test_strategy_runner.py || true
git diff --check
```

Completion criteria:

- Unit tests pass without IB Gateway.
- Strategy runner tests use fixture feeds.
- `strategy-runner` works offline with local snapshots when present.
- No-op diagnostics run once per frame.
- Reports are written and state that no real strategy evaluation, signal generation, order simulation, broker routing, portfolio accounting, or P&L calculation was performed.
- No broker calls or order APIs are added.
- No order-intent generation, fill simulation, P&L calculation, or portfolio accounting is added.
- Paper execution remains blocked, live trading remains rejected, and generated reports remain ignored.

## Milestone 12 - Broker-free offline fixture stress suite

Baseline before edits:

- Milestone 11 / `v0.9.0-broker-free-inert-strategy-runner` completed the offline no-op strategy runner.
- The existing real local SPY/AAPL snapshots are clean, so they do not exercise missing, malformed, duplicate, invalid, or failed data paths.
- This milestone is robustness validation only. It must not contact IBKR, evaluate real strategies, generate signals or order intents, simulate orders or fills, calculate P&L, perform portfolio accounting, activate paper execution, or enable live trading.
- Unit tests must use temporary synthetic snapshot fixtures or fixture feed objects and must not require IB Gateway or `ibapi`.

Files expected to change:

- `docs/IMPLEMENTATION_PLAN.md`
- `tests/fixtures/__init__.py`
- `tests/fixtures/historical_snapshots.py`
- `tests/test_offline_stress_loader.py`
- `tests/test_offline_stress_backtest_feed.py`
- `tests/test_offline_stress_backtest_engine.py`
- `tests/test_offline_stress_strategy_runner.py`
- `README.md`
- `docs/RUNBOOK.md`
- `docs/SAFETY.md`
- `docs/STATUS.md`
- `AGENTS.md`

Fixture dataset scenarios:

- `clean_two_symbol_dataset`: two symbols, matching timestamps, valid OHLCV, expected ready/loaded status.
- `single_symbol_missing_bars`: one symbol has a skipped timestamp, expected timestamp-gap diagnostics.
- `multi_symbol_partial_overlap`: symbol A has timestamps 1,2,3,4 while symbol B has timestamps 2,3; union shows explicit missing bars and intersection keeps only shared timestamps.
- `duplicate_timestamps`: one symbol has a duplicate timestamp and records duplicate diagnostics.
- `invalid_ohlc`: one bar has inconsistent OHLC values and fails loader validation.
- `negative_volume`: one bar has negative volume and fails loader validation.
- `malformed_jsonl_line`: invalid JSONL is partial in non-strict mode and failed in strict mode.
- `missing_manifest`: bars exist without a manifest and fail cleanly.
- `missing_bars_file`: manifest exists without bars and fails cleanly.
- `empty_dataset`: manifest and empty bars file produce structured empty-dataset diagnostics.

Loader stress tests:

- Load each fixture scenario through the offline historical loader.
- Assert clean fixtures load, gapped/duplicate/malformed non-strict fixtures are partial, and invalid/missing/empty fixtures fail cleanly.
- Assert structured counts for gaps, duplicates, invalid OHLC, negative volume, malformed lines, missing manifests, missing bars files, empty bars, and manifest mismatch where applicable.
- Assert reports serialize and retain `broker_contacted=false`, `order_routing_enabled=false`, and `no_order_guarantee=true`.

Feed adapter stress tests:

- Build feeds from fixture-loaded datasets rather than real local snapshots.
- Assert union alignment includes all observed timestamps and makes missing bars explicit.
- Assert intersection alignment includes only timestamps shared by all symbols.
- Assert partial datasets produce partial feed status and failed datasets fail cleanly.
- Assert deterministic frame ordering, missing-bar counts, duplicate diagnostics, and safety flags.
- Assert no strategy evaluation, order simulation, or P&L calculation is introduced.

Engine stress tests:

- Run the broker-free engine over ready, partial, and failed feeds built from fixtures.
- Assert ready feeds complete, partial feeds complete with warnings, and failed feeds fail cleanly.
- Assert missing bars and frames with missing bars are counted.
- Assert frame observations remain deterministic and sorted.
- Assert `strategy_evaluated=false`, `orders_simulated=false`, `pnl_calculated=false`, and `broker_contacted=false`.

Strategy contract and inert runner stress tests:

- Build strategy frame contexts from partial feeds with missing symbols.
- Assert available and missing symbols are preserved in context diagnostics.
- Run the inert no-op runner over partial feeds and assert one diagnostic per frame.
- Assert missing symbols are aggregated by frame and symbol.
- Assert all runner safety flags remain diagnostic-only and false for real strategy evaluation, signal generation, order generation, order simulation, fill simulation, P&L, portfolio accounting, and broker contact.

Report and diagnostic expectations:

- This milestone will remain test-only plus documentation.
- The optional `offline-stress-report` CLI will be skipped to avoid adding unnecessary reporting surface area before it is needed.
- Existing model/report serialization paths will be exercised through the stress tests.

Safety checks:

- Do not add broker calls, socket connection attempts, `trader.broker` imports, `ibapi` imports, order APIs, real strategy evaluation, signal generation, order-intent generation, order simulation, fill simulation, P&L calculation, portfolio accounting, paper execution activation, or live trading.
- New stress helper paths must remain independent from broker and `ibapi`.
- Generated reports and generated snapshots remain ignored.

Validation commands:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy src
.venv/bin/python -m trader.cli --help
.venv/bin/python -m trader.cli status
.venv/bin/python -m trader.cli history-index || true
.venv/bin/python -m trader.cli history-load --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli backtest-feed --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli backtest-run --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli strategy-contract --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli strategy-runner --symbols SPY,AAPL || true
grep -R "placeOrder" -n src tests docs scripts || true
grep -R "cancelOrder" -n src tests docs scripts || true
grep -R "reqGlobalCancel" -n src tests docs scripts || true
grep -R "ALLOW_PAPER_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "ALLOW_LIVE_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "4001\|7496" -n src tests docs scripts .env.example || true
grep -R "trader.broker" -n tests/fixtures tests/test_offline_stress*.py src/trader || true
grep -R "IBKRReadOnlyClient\|ibapi" -n tests/fixtures tests/test_offline_stress*.py src/trader || true
git diff --check
```

Completion criteria:

- Unit tests pass without IB Gateway.
- Synthetic fixture builders exist.
- Loader stress tests cover clean, partial, duplicate, invalid, malformed, missing, and empty datasets.
- Feed adapter stress tests cover union/intersection and missing-bar behavior.
- Engine stress tests cover ready/partial/failed feeds.
- Strategy contract and inert runner stress tests cover missing symbols and no-op diagnostics.
- No broker calls or order APIs are added.
- No real strategy evaluation, signal generation, order-intent generation, order simulation, fill simulation, P&L calculation, or portfolio accounting is added.
- Paper execution remains blocked, live trading remains rejected, and generated reports remain ignored.

## Milestone 13 - Broker-free signal contract scaffold

Baseline before edits:

- Milestone 12 / `v0.10.0-offline-fixture-stress-suite` completed broker-free stress coverage across loader, feed adapter, engine, strategy contract, and inert strategy runner paths.
- The next approved step is contract design only: a disabled signal contract that validates context shape and emits diagnostics without producing trading outputs.
- This milestone must not contact IBKR, import broker clients in the signal path, generate real signals, create order-intent outputs, simulate orders or fills, calculate P&L, perform portfolio accounting, activate paper execution, or enable live trading.
- Unit tests must use fixture feed/frame objects or temporary synthetic snapshots and must not require IB Gateway or `ibapi`.

Files expected to change:

- `docs/IMPLEMENTATION_PLAN.md`
- `src/trader/models.py`
- `src/trader/strategy/signals.py`
- `src/trader/cli.py`
- `src/trader/reporting/reports.py`
- `scripts/run-signal-contract.sh`
- `tests/test_signal_contract.py`
- `tests/test_offline_stress_signal_contract.py`
- `README.md`
- `docs/RUNBOOK.md`
- `docs/SAFETY.md`
- `docs/STATUS.md`
- `AGENTS.md`

Signal contract schema design:

- Add serializable metadata for a disabled broker-free signal contract: name, version, description, supported symbols, supported bar sizes, required bar fields, `broker_required=false`, and `enabled=false`.
- Add field requirement metadata so future evaluators can declare required bar fields without introducing trading actions.
- Add a signal evaluation context that wraps a broker-free feed frame with timestamp, frame index, available symbols, missing symbols, bars by symbol, feed metadata, strategy metadata, and alignment mode.
- Add per-frame signal contract diagnostics with fixed safety fields: `signal_evaluation_enabled=false`, `generated_signals=false`, `signal_count=0`, `generated_orders=false`, `orders_simulated=false`, `fills_simulated=false`, `pnl_calculated=false`, `portfolio_accounting=false`, `broker_contacted=false`, `order_routing_enabled=false`, and `no_order_guarantee=true`.

Disabled signal evaluator design:

- Implement `src/trader/strategy/signals.py` as a broker-free module that imports only offline feed/strategy contract models and helpers.
- Provide `default_disabled_signal_contract_metadata()`, `build_signal_evaluation_context(...)`, `validate_signal_contract(...)`, `run_disabled_signal_contract_diagnostic(...)`, and `build_signal_contract_report(...)`.
- The disabled evaluator validates metadata and required bar fields, records that signal evaluation is disabled, and emits diagnostics only.
- The disabled evaluator must not mutate the input feed and must not produce signals, order intents, simulated orders, simulated fills, portfolio accounting, or P&L.

Signal evaluation context model:

- Preserve frame timestamp, frame index, available symbols, missing symbols, bars by symbol, feed symbols, alignment mode, feed status, feed frame count, feed summary, and strategy metadata.
- Missing symbols remain explicit in context diagnostics.
- Partial feeds may produce diagnostics with warnings; failed or empty feeds fail cleanly with structured errors.

Diagnostics model:

- Add serializable models for `SignalContractMetadata`, `SignalFieldRequirement`, `SignalEvaluationContext`, `SignalContractDiagnostic`, `SignalContractValidationRequest`, `SignalContractValidationResult`, and `SignalContractReport`.
- Include request criteria, feed summary, a frame context sample, diagnostics, warning/error lists, final status, and all required false safety flags.
- Reports include `signal_contract_validated=true` only when metadata validation succeeds.

CLI behavior:

- Add `python -m trader.cli signal-contract --symbols SPY,AAPL`.
- Support `--alignment union`, `--alignment intersection`, `--bar-size`, `--what-to-show`, `--latest`, `--strict`, `--snapshot-timestamp`, and `--base-path`.
- The command loads local snapshots through the offline historical loader, builds a broker-free feed, validates the disabled signal contract, writes a report, and prints diagnostic-only status.
- The command must clearly state `signal_evaluation_enabled=false`, `generated_signals=false`, `signal_count=0`, `generated_orders=false`, `orders_simulated=false`, `fills_simulated=false`, `pnl_calculated=false`, `portfolio_accounting=false`, and `broker_contacted=false`.

Reporting behavior:

- Write `reports/signal_contract_<timestamp>.json` and `.md`.
- Maintain `reports/latest_signal_contract.json` and `.md`.
- Reports include signal contract metadata, symbols requested, feed summary, frame context sample, validation result, diagnostics, warnings/errors, and all required safety flags.
- Reports include the explicit statement: "This command validates the signal contract only. Signal evaluation is disabled. No trading signals, order intents, order simulation, broker routing, fills, portfolio accounting, or P&L calculation were produced."

Tests to add:

- Signal contract metadata, field requirement, context, diagnostic, validation result, and report models serialize cleanly.
- Disabled signal contract metadata validates.
- Disabled signal contract accepts a frame context and emits diagnostics only.
- Required safety flags remain fixed: no signal evaluation, no generated signals, zero signal count, no generated orders, no simulated orders, no simulated fills, no P&L, no portfolio accounting, no broker contact, order routing disabled, and no-order guarantee true.
- Context builder preserves timestamps, available symbols, and missing symbols.
- CLI `signal-contract` runs with fixture snapshot data.
- Signal path has no broker or `ibapi` imports and no forbidden order API usage.
- Paper executor remains blocked and live ports remain rejected.

Stress tests:

- Add `tests/test_offline_stress_signal_contract.py`.
- Use existing synthetic fixture scenarios to prove partial feeds, missing symbols, duplicate/gapped fixture contexts, and diagnostic-only output.
- Assert `signal_evaluation_enabled=false`, `generated_signals=false`, `signal_count=0`, `generated_orders=false`, `orders_simulated=false`, `fills_simulated=false`, `pnl_calculated=false`, `portfolio_accounting=false`, and `broker_contacted=false`.

Safety checks:

- Do not add broker calls, socket connection attempts, `trader.broker` imports, `ibapi` imports, order APIs, real signal generation, order-intent generation, order simulation, fill simulation, P&L calculation, portfolio accounting, paper execution activation, or live trading.
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
.venv/bin/python -m trader.cli strategy-runner --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli signal-contract --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli signal-contract --symbols SPY,AAPL --alignment intersection || true
scripts/run-signal-contract.sh || true
grep -R "placeOrder" -n src tests docs scripts || true
grep -R "cancelOrder" -n src tests docs scripts || true
grep -R "reqGlobalCancel" -n src tests docs scripts || true
grep -R "ALLOW_PAPER_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "ALLOW_LIVE_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "4001\|7496" -n src tests docs scripts .env.example || true
grep -R "trader.broker" -n src/trader/strategy tests/test_signal_contract.py tests/test_offline_stress_signal_contract.py || true
grep -R "IBKRReadOnlyClient\|ibapi" -n src/trader/strategy tests/test_signal_contract.py tests/test_offline_stress_signal_contract.py || true
grep -R "place_order\|submit_order\|order_intent\|fill\|portfolio\|pnl\|P&L\|profit\|loss" -n src/trader/strategy tests/test_signal_contract.py tests/test_offline_stress_signal_contract.py || true
grep -R "buy\|sell\|hold" -n src/trader/strategy/signals.py tests/test_signal_contract.py tests/test_offline_stress_signal_contract.py || true
git diff --check
```

Completion criteria:

- Unit tests pass without IB Gateway.
- Signal contract tests use fixture frames/feeds.
- `signal-contract` works offline with local snapshots when present.
- Disabled signal contract emits diagnostics only.
- Reports are written and state that signal evaluation is disabled and no trading outputs, broker routing, fills, portfolio accounting, or P&L were produced.
- No broker calls or order APIs are added.
- No real signal generation, order-intent generation, order simulation, fill simulation, P&L calculation, or portfolio accounting is added.
- Paper execution remains blocked, live trading remains rejected, and generated reports remain ignored.

## Milestone 14 - Broker-free disabled signal diagnostic runner

Baseline before edits:

- Milestone 13 / `v0.11.0-broker-free-signal-contract` added the disabled signal contract scaffold.
- The stage-gated audit polish tag `v0.11.1-stage-gated-audit-polish` confirmed milestones `v0.1` through `v0.11` are complete or fixed-and-complete.
- This milestone implements `v0.12` as diagnostic plumbing only: historical feed frames are routed through the existing disabled signal contract and recorded per frame.
- Paper execution remains blocked, live trading remains rejected, and no broker contact is allowed.

Files expected to change:

- `docs/IMPLEMENTATION_PLAN.md`
- `src/trader/models.py`
- `src/trader/strategy/signal_runner.py`
- `src/trader/cli.py`
- `src/trader/reporting/reports.py`
- `scripts/run-signal-runner.sh`
- `tests/test_signal_runner.py`
- `tests/test_offline_stress_signal_runner.py`
- `README.md`
- `docs/RUNBOOK.md`
- `docs/SAFETY.md`
- `docs/STATUS.md`
- `docs/STAGE_AUDIT.md`
- `AGENTS.md`

Disabled signal runner design:

- Add a broker-free runner that consumes a `BacktestDataFeed`, builds a `SignalEvaluationContext` for each deterministic feed frame, and invokes only `DisabledSignalContract.observe(...)`.
- Record one per-frame `DisabledSignalFrameDiagnostic` for each feed frame and runner-level diagnostics for frame count, contexts built, diagnostics emitted, first/last timestamp, missing symbols by frame, and missing symbols by symbol.
- Treat ready feeds as completed, partial feeds as completed with partial status and warnings, empty feeds as failed, and failed feeds as failed with precise errors.
- The runner must not mutate the input feed.

Dependency boundaries:

- The signal runner module may depend on `trader.backtest.data_adapter`, `trader.models`, `trader.strategy.interface`, and `trader.strategy.signals`.
- The signal runner path must not import `trader.broker`, `trader.execution`, `ibapi`, portfolio construction, risk routing, or broker clients.
- CLI integration must reuse the offline historical loader and backtest feed adapter, matching the `signal-contract` command.

Per-frame diagnostic flow:

- Load offline datasets through `load_historical_snapshots(...)`.
- Build a `BacktestDataFeed` with union or intersection alignment.
- Summarize the feed.
- For each frame yielded by `iter_feed_frames(...)`, build a `SignalEvaluationContext`.
- Invoke the disabled signal contract and store the resulting diagnostic.
- Aggregate missing symbols, warnings, errors, and runner status.

Result and report models:

- Add `DisabledSignalRunnerRequest`.
- Add `DisabledSignalFrameDiagnostic`.
- Add `DisabledSignalRunnerDiagnostics`.
- Add `DisabledSignalRunnerResult`.
- Add `DisabledSignalRunnerReport`.
- Include `disabled_signal_runner=true`, `signal_contract_validated=true`, `signal_evaluation_enabled=false`, `generated_signals=false`, `signal_count=0`, `generated_orders=false`, `order_intents_generated=false`, `orders_simulated=false`, `fills_simulated=false`, `pnl_calculated=false`, `portfolio_accounting=false`, `broker_contacted=false`, `order_routing_enabled=false`, and `no_order_guarantee=true` in relevant result/report surfaces.

CLI behavior:

- Add `python -m trader.cli signal-runner --symbols SPY,AAPL`.
- Support `--alignment union`, `--alignment intersection`, `--bar-size`, `--what-to-show`, `--latest`, `--strict`, `--snapshot-timestamp`, and `--base-path`.
- Print a diagnostic-only summary with runner status, frame count, contexts built, diagnostics emitted, missing symbols, and explicit false safety flags.
- The command must state that no trading signals, order intents, order simulation, broker routing, fills, portfolio accounting, or P&L calculation were performed.

Reporting behavior:

- Write `reports/signal_runner_<timestamp>.json` and `.md`.
- Maintain `reports/latest_signal_runner.json` and `.md`.
- Reports include timestamp, symbols requested, snapshot selection criteria, alignment mode, feed summary, disabled signal contract metadata, runner status, frame count, context/diagnostic counts, first/last timestamp, missing symbols summary, warnings/errors, and all required safety flags.
- Reports include the explicit statement: "This run exercised the disabled signal contract only. Signal evaluation is disabled. No trading signals, order intents, order simulation, broker routing, fills, portfolio accounting, or P&L calculation was performed."

Fixture and stress tests:

- Add fixture-feed unit tests for ready, partial, empty, and failed feeds.
- Assert one signal context and one disabled-signal diagnostic per frame.
- Assert first/last timestamp and missing-symbol aggregation.
- Assert JSON serialization for result/report models.
- Add CLI fixture snapshot coverage that does not depend on real `data/historical` contents.
- Add stress tests using synthetic historical snapshot fixtures for partial overlap, gapped, duplicate, and clean feeds.
- Add static tests that the runner path has no broker, `ibapi`, or forbidden order API dependencies.

Safety checks:

- No broker calls, socket connection attempts, `trader.broker` imports, `ibapi` imports, order APIs, real signal evaluation, buy/sell/hold outputs, order-intent generation, order simulation, fill simulation, P&L calculation, portfolio accounting, paper execution activation, or live trading.
- Generated reports and generated snapshots remain ignored.
- Paper executor remains blocked and live ports remain rejected.

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
.venv/bin/python -m trader.cli strategy-runner --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli signal-contract --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli signal-runner --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli signal-runner --symbols SPY,AAPL --alignment intersection || true
scripts/run-signal-runner.sh || true
grep -R "placeOrder" -n src tests docs scripts || true
grep -R "cancelOrder" -n src tests docs scripts || true
grep -R "reqGlobalCancel" -n src tests docs scripts || true
grep -R "ALLOW_PAPER_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "ALLOW_LIVE_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "4001\|7496" -n src tests docs scripts .env.example || true
grep -R "trader.broker" -n src/trader/strategy tests/test_signal_runner.py tests/test_offline_stress_signal_runner.py || true
grep -R "IBKRReadOnlyClient\|ibapi" -n src/trader/strategy tests/test_signal_runner.py tests/test_offline_stress_signal_runner.py || true
grep -R "place_order\|submit_order\|order_intent\|fill\|portfolio\|pnl\|P&L\|profit\|loss" -n src/trader/strategy tests/test_signal_runner.py tests/test_offline_stress_signal_runner.py || true
grep -R "buy\|sell\|hold" -n src/trader/strategy tests/test_signal_runner.py tests/test_offline_stress_signal_runner.py || true
git diff --check
```

Explicit non-goals:

- No real signal evaluation.
- No buy/sell/hold signal generation.
- No order intents.
- No order simulation.
- No fill simulation.
- No P&L.
- No portfolio accounting.
- No broker calls.
- No paper or live execution.

Completion criteria:

- Unit tests pass without IB Gateway.
- `signal-runner` works offline with local snapshots when present or fails cleanly when they are absent.
- Disabled signal diagnostics run once per frame.
- `disabled_signal_runner=true`, `signal_contract_validated=true`, `signal_evaluation_enabled=false`, `generated_signals=false`, `signal_count=0`, `generated_orders=false`, `order_intents_generated=false`, `orders_simulated=false`, `fills_simulated=false`, `pnl_calculated=false`, `portfolio_accounting=false`, and `broker_contacted=false` are present in relevant reports.
- Reports are written and remain ignored.
- No broker calls or order APIs are added.
- Paper execution remains blocked and live trading remains rejected.

## Milestone 15 - Broker-free analytical signal evaluator scaffold

Objective:

- Implement `v0.13` as the first broker-free analytical signal evaluator scaffold.
- The evaluator calculates non-actionable diagnostic observations from offline
  historical feed frames.
- The evaluator must not produce trading instructions, order-shaped records,
  portfolio decisions, fills, accounting, or performance claims.

Current baseline:

- Latest completed tag is `v0.12.0-broker-free-disabled-signal-runner`.
- The offline loader, feed adapter, backtest engine, strategy contract, inert
  strategy runner, signal contract, and disabled signal runner are operational.
- `signal-runner` still reports `signal_evaluation_enabled=false`,
  `generated_signals=false`, `signal_count=0`, `generated_orders=false`,
  `order_intents_generated=false`, `orders_simulated=false`,
  `fills_simulated=false`, `pnl_calculated=false`,
  `portfolio_accounting=false`, and `broker_contacted=false`.
- `signal-evaluate` reports `signal_evaluation_enabled=true`,
  `generated_signals=false`, `signal_count=0`, `generated_orders=false`,
  `order_intents_generated=false`, `orders_simulated=false`,
  `fills_simulated=false`, `pnl_calculated=false`,
  `portfolio_accounting=false`, and `broker_contacted=false`.

Non-goals:

- No broker calls, broker imports, socket connections, or `ibapi` dependency.
- No buy/sell/hold, long/short, enter/exit, order, position, allocation, or
  rebalance output vocabulary.
- No order intents, order simulation, fill simulation, P&L, portfolio
  accounting, paper execution activation, or live trading.
- No profitability, tradability, alpha-quality, or performance claims.
- No changes to execution, portfolio, risk, broker, or paper-executor behavior.

Allowed behavior:

- Load local historical snapshots through the offline loader.
- Build a `BacktestDataFeed` with the existing broker-free feed adapter.
- Iterate feed frames in deterministic timestamp order.
- Build a read-only per-symbol analytical context from bars with timestamps at
  or before the current frame timestamp.
- Emit analytical observations that use only the approved diagnostic vocabulary.
- Write JSON/Markdown reports for the approved `signal-evaluate` command only.

Forbidden behavior:

- Do not import `trader.broker`, `trader.execution`, `ibapi`, broker clients,
  portfolio construction, risk routing, or execution routing from the evaluator
  path.
- Do not call order APIs, including `placeOrder`, `cancelOrder`, or
  `reqGlobalCancel`.
- Do not create order-intent schemas beyond explicit false safety flags.
- Do not interpret an observation as a trade recommendation.

Implemented model/schema:

- `AnalyticalSignalConditionState` has exactly:
  `condition_met`, `condition_not_met`, `insufficient_data`, and
  `invalid_data`.
- `AnalyticalSignalObservation` includes:
  `evaluator_name`, `evaluator_version`, `symbol`, `timestamp`,
  `frame_index`, `condition_name`, `condition_state`, `numeric_value`,
  `threshold_or_reference_value`, `required_lookback_bars`,
  `warmup_complete`, `data_valid`, `explanation`, `generated_signals=false`,
  `signal_count=0`, `order_intents_generated=false`,
  `broker_contacted=false`, `pnl_calculated=false`, and
  `portfolio_accounting=false`.
- `AnalyticalSignalEvaluatorMetadata` includes:
  `name`, `version`, `description`, `required_fields`,
  `required_lookback_bars`, `supported_bar_sizes`, `broker_required=false`,
  `emits_trading_actions=false`, and `emits_order_intents=false`.
- Run/report models preserve
  `generated_signals=false`, `signal_count=0`, `generated_orders=false`,
  `order_intents_generated=false`, `orders_simulated=false`,
  `fills_simulated=false`, `pnl_calculated=false`,
  `portfolio_accounting=false`, `broker_contacted=false`,
  `order_routing_enabled=false`, and `no_order_guarantee=true`.

Evaluator interface:

- Module: `src/trader/strategy/signal_evaluation.py`.
- Public evaluation interface:
  `evaluate_moving_average_relationship(context, history_by_symbol, metadata, ...) -> list[AnalyticalSignalObservation]`.
- The interface accepts read-only frame context plus bounded historical bars for
  each symbol.
- The interface returns observations only. It must not return `Signal`,
  `TradePlan`, risk decisions, order intents, fills, positions, allocations, or
  P&L values.
- The implementation should expose validation helpers that reject unsupported
  condition states or forbidden vocabulary in observation fields.

First evaluator:

- Name: `moving_average_relationship_diagnostic`.
- Purpose: compare a short moving average with a long moving average using close
  prices available at the current frame timestamp.
- Default windows: short window `5`, long window `20`.
- Required lookback bars: `max(short_window, long_window)`.
- The evaluator may calculate short average, long average, difference, and a
  safe ratio when the long average is non-zero.
- It may return `condition_met` when the configured relationship is true,
  `condition_not_met` when the relationship is false, `insufficient_data` during
  warm-up, and `invalid_data` for missing or invalid OHLCV fields.

No-lookahead rule:

- At frame timestamp `T`, the evaluator may only use bars with
  `bar.timestamp <= T`.
- Future bars must not be inspected, cached into the frame, or used for warm-up.
- Tests must include a sentinel future bar whose value would change the moving
  average if accidentally read.

Warm-up rule:

- If fewer than `required_lookback_bars` valid bars are available for a symbol,
  return `condition_state=insufficient_data`.
- Warm-up observations must include `warmup_complete=false`,
  `generated_signals=false`, and `signal_count=0`.

Invalid-data rule:

- If required OHLCV fields are missing, non-numeric, non-finite, or internally
  invalid, return `condition_state=invalid_data`.
- Invalid-data observations must include `data_valid=false`,
  `generated_signals=false`, and `signal_count=0`.

Output vocabulary:

- Allowed condition states:
  `condition_met`, `condition_not_met`, `insufficient_data`, `invalid_data`.
- Forbidden vocabulary in observation states, condition names, explanations, CLI
  summaries, and reports when describing outputs:
  `buy`, `sell`, `hold`, `long`, `short`, `enter`, `exit`, `order`,
  `position`, `allocation`, and `rebalance`.
- Documentation may list forbidden words only as safety boundaries.

Report fields:

- Proposed future report files:
  `reports/signal_evaluation_<timestamp>.json`,
  `reports/signal_evaluation_<timestamp>.md`,
  `reports/latest_signal_evaluation.json`, and
  `reports/latest_signal_evaluation.md`.
- Reports must state that observations are non-actionable diagnostics.
- `signal_evaluation_enabled=true` may be used only if the implementation
  milestone explicitly approves analytical evaluation execution. Even then,
  `generated_signals=false` and `signal_count=0` remain required for this
  scaffold.
- Reports must include `order_intents_generated=false`,
  `broker_contacted=false`, `orders_simulated=false`,
  `fills_simulated=false`, `pnl_calculated=false`,
  `portfolio_accounting=false`, `order_routing_enabled=false`, and
  `no_order_guarantee=true`.
- Reports must avoid profitability, performance, or tradability claims.

CLI proposal:

```bash
python -m trader.cli signal-evaluate --symbols SPY,AAPL
python -m trader.cli signal-evaluate --symbols SPY,AAPL --evaluator moving_average_relationship
python -m trader.cli signal-evaluate --symbols SPY,AAPL --short-window 5 --long-window 20
```

- The command must remain offline only.
- It should reuse loader and feed-adapter options from `signal-runner`,
  including `--alignment`, `--bar-size`, `--what-to-show`, `--latest`,
  `--strict`, `--snapshot-timestamp`, and `--base-path`.
- It must print that observations are diagnostic-only and non-actionable.

Test plan:

- Metadata, observation, result, and report models serialize cleanly.
- Invalid condition states are rejected.
- Forbidden output vocabulary is rejected in condition states and output labels.
- Moving-average observation returns `insufficient_data` before warm-up.
- Moving-average observation returns `invalid_data` for missing or invalid bars.
- No-lookahead sentinel test proves future bars are not used.
- Ready feed produces deterministic observations in frame/symbol order.
- Partial feed records missing-symbol diagnostics without generating signals.
- Empty and failed feeds fail cleanly.
- CLI fixture test runs with temporary local snapshots only.
- Static scans prove no broker, `ibapi`, execution, portfolio, risk, or order API
  dependency in the evaluator path.
- Paper executor remains blocked and live ports remain rejected.

Stress-test plan:

- Use the existing synthetic fixture families for clean, partial overlap,
  gapped, duplicate, malformed, invalid, missing, and empty datasets.
- Assert all stress scenarios keep `generated_signals=false`, `signal_count=0`,
  `order_intents_generated=false`, `orders_simulated=false`,
  `fills_simulated=false`, `pnl_calculated=false`,
  `portfolio_accounting=false`, and `broker_contacted=false`.
- Include a future-bar sentinel fixture for no-lookahead proof.

Safety scans:

```bash
grep -R "placeOrder" -n src tests docs scripts || true
grep -R "cancelOrder" -n src tests docs scripts || true
grep -R "reqGlobalCancel" -n src tests docs scripts || true
grep -R "ALLOW_PAPER_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "ALLOW_LIVE_ORDERS=true" -n . --exclude-dir=.git --exclude-dir=.venv || true
grep -R "trader.broker" -n src/trader/strategy tests/test_signal_evaluation.py tests/test_offline_stress_signal_evaluation.py || true
grep -R "IBKRReadOnlyClient\|ibapi" -n src/trader/strategy tests/test_signal_evaluation.py tests/test_offline_stress_signal_evaluation.py || true
grep -R "place_order\|submit_order\|order_intent\|fill\|portfolio\|pnl\|P&L\|profit\|loss" -n src/trader/strategy tests/test_signal_evaluation.py tests/test_offline_stress_signal_evaluation.py || true
```

Acceptance criteria:

- Unit tests pass without IB Gateway.
- The evaluator works from fixture feeds or local snapshots only.
- Observations are generated once per evaluated symbol/frame and use only the
  allowed condition states.
- No lookahead is possible by construction and verified by tests.
- Warm-up and invalid-data states are explicit.
- `generated_signals=false`, `signal_count=0`, `order_intents_generated=false`,
  `generated_orders=false`, `orders_simulated=false`, `fills_simulated=false`,
  `pnl_calculated=false`, `portfolio_accounting=false`, and
  `broker_contacted=false` remain fixed.
- No order APIs, broker calls, paper execution, or live trading are added.
- Generated reports remain ignored.

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
.venv/bin/python -m trader.cli signal-runner --symbols SPY,AAPL || true
.venv/bin/python -m trader.cli signal-evaluate --symbols SPY,AAPL || true
.venv/bin/python -m pytest tests/test_signal_evaluation.py tests/test_offline_stress_signal_evaluation.py
git diff --check
```

Future v0.14 boundary:

- `v0.14` must not be assumed from this design.
- A future milestone may broaden analytical observation coverage or add
  evaluator comparison, but it still must not add order intents, execution,
  fills, P&L, portfolio accounting, paper execution, or live trading unless a
  separate explicit plan approves those behaviors.

## Milestone 16 - Broker-free commodity research universe scaffold

Objective:

- Add an offline commodity research universe that lists commodity-linked
  security proxies only.
- Keep direct futures contracts, futures data requests, rollover modeling,
  margin modeling, signal evaluation, order intents, fills, portfolio
  accounting, P&L, and broker contact disabled.

Implemented behavior:

- `python -m trader.cli commodity-universe`
- `python -m trader.cli commodity-universe --symbols GLD,USO,DBA`
- `scripts/run-commodity-universe.sh`
- JSON/Markdown reports under `reports/commodity_universe_<timestamp>.*`.
- Report flags include `commodity_proxy_universe=true`,
  `futures_contracts_enabled=false`, `direct_futures_data_enabled=false`,
  `broker_contacted=false`, `signal_evaluation_enabled=false`,
  `generated_signals=false`, `signal_count=0`, `order_intents_generated=false`,
  `orders_simulated=false`, `fills_simulated=false`,
  `pnl_calculated=false`, and `portfolio_accounting=false`.

Futures boundary:

- Before direct futures support, add explicit IBKR futures contract descriptors,
  exchange/month/multiplier validation, rollover rules, margin/risk models,
  data-permission checks, and paper-only execution activation review.
- Until then, commodity research remains limited to security proxies supported
  by the existing SMART/USD stock-data path.

## Milestone 17 - Read-only paper readiness orchestration

Objective:

- Add one sequential command for the first IBKR paper-client program run.
- Keep the run read-only and require a real broker account summary.
- Use commodity-linked security proxies only: `SPY,AAPL,GLD,USO,DBA`.
- Keep paper execution blocked and direct futures out of scope.

Implemented behavior:

- `python -m trader.cli paper-readiness-run`
- `scripts/run-paper-readiness-run.sh`
- JSON/Markdown reports under `reports/paper_readiness_run_<timestamp>.*`.
- Stage reports for broker probe, account summary, historical snapshot,
  historical readiness, historical load, commodity universe, and signal
  evaluation.
- Final report flags include `broker_connected`,
  `account_summary_verified`, `history_snapshot_written`,
  `signal_evaluation_completed`, `submitted_orders=false`,
  `paper_orders_enabled=false`, `read_only_api_expected=true`, and
  `order_routing_enabled=false`.

Stage order:

```text
broker-probe --timeout 15
account --connect --timeout 15
history-snapshot --symbols SPY,AAPL,GLD,USO,DBA --duration "1 D" --bar-size "5 mins" --what-to-show TRADES --use-rth 1 --timeout 30
history-load --symbols SPY,AAPL,GLD,USO,DBA --bar-size "5 mins" --what-to-show TRADES
commodity-universe --symbols GLD,USO,DBA
signal-evaluate --symbols SPY,AAPL,GLD,USO,DBA --bar-size "5 mins" --what-to-show TRADES --short-window 5 --long-window 20
```

Final statuses:

- `completed`: all required stages pass with ready data.
- `completed_with_warnings`: broker/account verified and evaluation completed,
  but one or more symbols are partial.
- `failed`: broker probe fails, broker account summary is unavailable, no
  usable snapshots load, or signal evaluation fails.

Safety boundary:

- `ALLOW_PAPER_ORDERS` must remain `false`.
- Mock account fallback is not readiness success.
- The paper executor remains a refusing stub.
- Direct futures require a separate milestone for contract descriptors,
  expiry/multiplier validation, rollover, margin/risk modeling, and
  paper-order gating.

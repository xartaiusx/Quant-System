# Runbook

## First-Time Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

For real read-only broker probes:

```bash
python -m pip install -e ".[dev,broker]"
scripts/check-ibapi.sh
```

If `ibapi` is unavailable from your package index, install the official IBKR TWS API Python client manually and rerun `scripts/check-ibapi.sh`.

Optional local config:

```bash
cp .env.example .env
```

Keep `.env` local.

## Test Commands

```bash
pytest
ruff check .
mypy src
```

## Broker Dependency Check

```bash
source .venv/bin/activate
scripts/check-ibapi.sh
```

Expected missing-dependency result:

```text
ibapi package: missing
Next step: activate the repo venv and install the optional broker extra:
  python -m pip install -e ".[dev,broker]"
No packages were installed by this script.
```

Expected success result:

```text
ibapi import: ok
ibapi readiness: ok
```

## Preflight

```bash
python -m trader.cli preflight
```

Expected behavior:

- reports config
- reports whether `ibapi` is installed
- does not open a broker socket
- does not place orders
- reports `connection_attempted=false`

To include a harmless current-time connection probe:

```bash
python -m trader.cli preflight --connect --timeout 10
```

## Broker Probe

```bash
python -m trader.cli broker-probe --timeout 10
scripts/run-broker-probe.sh --timeout 10
```

Expected success output:

```text
Read-only broker probe
Order routing: disabled.
No order APIs invoked.
Final status: connected
Server time: <broker timestamp>
Managed accounts: DUXX****99
```

Expected `ibapi` missing output:

```text
Read-only broker probe
Order routing: disabled.
No order APIs invoked.
Failure stage: dependency_check
connection_attempted: false
```

Expected failure output:

```text
Read-only broker probe
Order routing: disabled.
No order APIs invoked.
Final status: failed
Errors
- socket unavailable; confirm TWS/Gateway is running...
```

Expected paper TWS success prerequisites:

- Paper TWS is open and logged in.
- `Global Configuration -> API -> Settings -> Enable ActiveX and Socket Clients` is enabled.
- Socket port is `7497`.
- `Read-Only API` remains enabled.
- `IBKR_CLIENT_ID` is not already in use.

Combined readiness command:

```bash
scripts/run-broker-preflight.sh --timeout 10
```

Reports are written to:

```text
reports/broker_probe_<timestamp>.json
reports/broker_probe_<timestamp>.md
reports/latest_broker_probe.json
reports/latest_broker_probe.md
```

## Read-Only Market-Data Diagnostics

```bash
python -m trader.cli market-probe --symbols SPY,AAPL --data-type delayed --timeout 15
python -m trader.cli market-probe --symbols SPY,AAPL --data-type delayed --historical
scripts/run-market-probe.sh
```

Expected behavior:

- connects through the same safe broker lifecycle as `broker-probe`
- defaults to delayed data
- resolves SMART/USD stock contracts
- requests market-data type before quote ticks
- captures bid, ask, last, close, sizes, quote timestamp, spread, spread bps, and staleness when available
- optionally requests a small historical-bar sample
- cleans up data subscriptions with `cancelMktData` and `cancelHistoricalData`
- places no orders and invokes no order APIs

Reports are written to:

```text
reports/market_probe_<timestamp>.json
reports/market_probe_<timestamp>.md
reports/latest_market_probe.json
reports/latest_market_probe.md
```

Common outcomes:

- No market-data subscription: retry with `--data-type delayed`, or change account permissions manually if live data is required.
- IBKR `10167`: live market data is not subscribed and IBKR is displaying delayed data; this is expected in delayed diagnostics when quote data still arrives.
- Delayed data unavailable: confirm IBKR delayed-data settings and try during market hours.
- Contract ambiguity: the probe selects a listed USD equity match and records an ambiguity warning.
- Missing bid/ask outside market hours: the probe may still capture last, close, market-data type, or historical bars.
- Stale quotes: quote age is reported and stale quotes are flagged.
- Historical data pacing or permission issue: the historical section records IBKR errors or timeout diagnostics.

## Historical Snapshot Ingestion

```bash
python -m trader.cli history-fetch --symbols SPY,AAPL --duration "1 D" --bar-size "5 mins" --what-to-show TRADES --use-rth 1
python -m trader.cli history-readiness --latest
python -m trader.cli history-snapshot --symbols SPY,AAPL --duration "1 D" --bar-size "5 mins" --what-to-show TRADES --use-rth 1
scripts/run-history-snapshot.sh
```

Expected behavior:

- connects through the same safe broker lifecycle as `broker-probe`
- resolves SMART/USD stock contracts before requesting bars
- requests bounded historical bars sequentially
- stores JSONL bars and JSON manifests under `data/historical/<symbol>/<bar_size>/<what_to_show>/`
- writes snapshot and readiness reports under `reports/`
- cleans up incomplete requests with `cancelHistoricalData`
- places no orders and invokes no order APIs

Reports are written to:

```text
reports/history_snapshot_<timestamp>.json
reports/history_snapshot_<timestamp>.md
reports/latest_history_snapshot.json
reports/latest_history_snapshot.md
reports/history_readiness_<timestamp>.json
reports/history_readiness_<timestamp>.md
reports/latest_history_readiness.json
reports/latest_history_readiness.md
```

Generated snapshots are ignored by Git:

```text
data/historical/**/*.jsonl
data/historical/**/*_manifest.json
```

Common outcomes:

- No historical permissions: the report records the IBKR code and the symbol continues to the next request.
- Pacing limitation: wait before retrying and avoid widening the symbol list.
- Empty bars: readiness marks the symbol failed or partial rather than inventing data.
- Contract ambiguity: contract resolution records the ambiguity and selected listed USD equity.
- Outside market hours: latest RTH bars may still be valid; readiness focuses on stored bar quality.
- Gateway disconnected: the CLI fails cleanly with connection diagnostics.

## Offline Historical Loader

```bash
python -m trader.cli history-index
python -m trader.cli history-load --symbols SPY,AAPL
python -m trader.cli history-load --symbols SPY,AAPL --bar-size "5 mins" --what-to-show TRADES
python -m trader.cli history-load --symbols SPY,AAPL --strict
python -m trader.cli history-inspect --symbol SPY
scripts/run-history-load.sh
```

Expected behavior:

- opens no broker socket
- does not import broker clients or require `ibapi`
- discovers ignored JSONL snapshots and manifests under `data/historical/`
- selects the latest matching snapshot per symbol by default
- supports symbol, bar-size, what-to-show, and timestamp filters
- normalizes bars into in-memory datasets with parsed timestamps, numeric OHLCV, typical price, dollar volume, and interval seconds
- validates duplicates, gaps, malformed lines, invalid OHLC, negative volume, bar-count mismatches, empty datasets, and stale snapshots
- writes index/load reports under `reports/`
- places no orders and invokes no order APIs

Reports are written to:

```text
reports/history_index_<timestamp>.json
reports/history_index_<timestamp>.md
reports/latest_history_index.json
reports/latest_history_index.md
reports/history_load_<timestamp>.json
reports/history_load_<timestamp>.md
reports/latest_history_load.json
reports/latest_history_load.md
```

Generate snapshots first with `history-snapshot` if `history-index` reports no
local files. Non-strict loading keeps good bars and reports malformed lines as a
partial load; `--strict` marks malformed records as failed. Common failures:

- No snapshots found: run a bounded `history-snapshot` request first.
- Missing manifest: regenerate the snapshot pair.
- Missing bars file: remove the orphan manifest or regenerate the pair.
- Malformed JSONL line: inspect the line number in the loader report.
- Bar-count mismatch: compare the manifest `bar_count` with loaded JSONL records.
- Duplicate timestamps or timestamp gaps: treat the dataset as partial until reviewed.
- Invalid OHLC or negative volume: treat the dataset as failed for simulation input.
- Stale snapshot: refresh historical data when a current dataset is required.

## Offline Backtest Feed

```bash
python -m trader.cli backtest-feed --symbols SPY,AAPL
python -m trader.cli backtest-feed --symbols SPY,AAPL --alignment union
python -m trader.cli backtest-feed --symbols SPY,AAPL --alignment intersection
python -m trader.cli backtest-feed --symbols SPY,AAPL --bar-size "5 mins" --what-to-show TRADES
scripts/run-backtest-feed.sh
```

Expected behavior:

- opens no broker socket
- uses the offline historical loader to read local snapshots
- adapts `HistoricalLoadedDataset` records into normalized feed frames
- preserves symbol identity, source snapshot paths, and source manifest paths
- writes `reports/backtest_feed_<timestamp>.json` and `.md`
- updates `reports/latest_backtest_feed.json` and `.md`
- places no orders and invokes no order APIs
- does not evaluate strategies, simulate orders, or compute P&L

Alignment modes:

- `union` includes every timestamp observed across the selected symbols. Missing
  symbol bars are explicit empty values in those frames and are counted by symbol.
- `intersection` includes only timestamps present for every selected symbol.

Use `history-index` and `history-load` first if `backtest-feed` reports no local
snapshots. Common failures:

- No snapshots found: run `history-snapshot` in a separate broker-read-only task.
- Empty dataset: inspect the source JSONL and manifest pair.
- Partial dataset: review loader warnings before using the feed for future simulation.
- Duplicate timestamps: the adapter keeps deterministic first-bar ordering and records the duplicate count.
- Missing bars: use `intersection` when future analysis needs only shared timestamps.

## Offline Backtest Run

```bash
python -m trader.cli backtest-run --symbols SPY,AAPL
python -m trader.cli backtest-run --symbols SPY,AAPL --alignment union
python -m trader.cli backtest-run --symbols SPY,AAPL --alignment intersection
python -m trader.cli backtest-run --symbols SPY,AAPL --bar-size "5 mins" --what-to-show TRADES
scripts/run-backtest-run.sh
```

Expected behavior:

- opens no broker socket
- loads local snapshots through the offline historical loader
- builds an aligned feed with the broker-free data adapter
- replays feed frames in deterministic timestamp order
- records frame observations and run diagnostics
- writes `reports/backtest_run_<timestamp>.json` and `.md`
- updates `reports/latest_backtest_run.json` and `.md`
- places no orders and invokes no order APIs
- does not evaluate strategies, simulate orders, calculate fills, maintain portfolio accounting, or compute P&L

Workflow relationship:

```text
history-snapshot -> history-load -> backtest-feed -> backtest-run
```

`history-snapshot` is the only step in that chain that contacts IBKR, and only
when explicitly run. `history-load`, `backtest-feed`, and `backtest-run` are
offline local-file workflows. Common failures:

- No snapshots found: run or review `history-index` and `history-load`.
- Empty feed: inspect the snapshot and loader reports.
- Failed feed: fix loader errors before replay.
- Partial feed: review missing-bar diagnostics in the run report.

## Offline Strategy Contract

```bash
python -m trader.cli strategy-contract --symbols SPY,AAPL
python -m trader.cli strategy-contract --symbols SPY,AAPL --alignment union
python -m trader.cli strategy-contract --symbols SPY,AAPL --alignment intersection
python -m trader.cli strategy-contract --symbols SPY,AAPL --bar-size "5 mins" --what-to-show TRADES
scripts/run-strategy-contract.sh
```

Expected behavior:

- opens no broker socket
- loads local snapshots through the offline historical loader
- builds an aligned feed with the broker-free data adapter
- validates the no-op strategy interface contract
- records frame context samples and per-frame diagnostics
- writes `reports/strategy_contract_<timestamp>.json` and `.md`
- updates `reports/latest_strategy_contract.json` and `.md`
- places no orders and invokes no order APIs
- does not perform real strategy evaluation, generate signals, simulate orders, calculate fills, maintain portfolio accounting, or compute P&L

Workflow relationship:

```text
history-snapshot -> history-load -> backtest-feed -> backtest-run -> strategy-contract
```

`strategy-contract` is a contract validation command only. It proves the shape of
future strategy inputs and diagnostics without connecting strategies to the
engine loop. Common failures:

- No snapshots found: run or review `history-index` and `history-load`.
- Empty feed: inspect the snapshot and loader reports.
- Missing bar fields: review the contract report before future strategy work.
- Partial feed: review missing-symbol diagnostics in the frame context sample.

## Offline Inert Strategy Runner

```bash
python -m trader.cli strategy-runner --symbols SPY,AAPL
python -m trader.cli strategy-runner --symbols SPY,AAPL --alignment union
python -m trader.cli strategy-runner --symbols SPY,AAPL --alignment intersection
python -m trader.cli strategy-runner --symbols SPY,AAPL --bar-size "5 mins" --what-to-show TRADES
scripts/run-strategy-runner.sh
```

Expected behavior:

- opens no broker socket
- loads local snapshots through the offline historical loader
- builds an aligned feed with the broker-free data adapter
- builds a strategy frame context for each feed frame
- invokes only the no-op strategy diagnostic contract
- records one diagnostic result per frame
- writes `reports/strategy_runner_<timestamp>.json` and `.md`
- updates `reports/latest_strategy_runner.json` and `.md`
- places no orders and invokes no order APIs
- does not perform real strategy evaluation, generate buy/sell/hold signals,
  generate order intents, simulate orders, simulate fills, maintain portfolio
  accounting, or compute P&L

Workflow relationship:

```text
history-snapshot -> history-load -> backtest-feed -> backtest-run -> strategy-contract -> strategy-runner
```

`strategy-runner` exercises only the no-op contract. It is runner plumbing for a
future explicitly approved strategy-evaluation milestone; it is not a trading
decision engine. Common failures:

- No snapshots found: run or review `history-index` and `history-load`.
- Empty feed: inspect the snapshot and loader reports.
- Failed feed: fix loader/feed errors before running the diagnostic path.
- Partial feed: review missing-symbol summaries in the runner report.

## Offline Signal Contract

```bash
python -m trader.cli signal-contract --symbols SPY,AAPL
python -m trader.cli signal-contract --symbols SPY,AAPL --alignment union
python -m trader.cli signal-contract --symbols SPY,AAPL --alignment intersection
python -m trader.cli signal-contract --symbols SPY,AAPL --bar-size "5 mins" --what-to-show TRADES
scripts/run-signal-contract.sh
```

Expected behavior:

- opens no broker socket
- loads local snapshots through the offline historical loader
- builds an aligned feed with the broker-free data adapter
- validates the disabled signal contract schema and required bar fields
- records signal evaluation contexts and per-frame diagnostics
- writes `reports/signal_contract_<timestamp>.json` and `.md`
- updates `reports/latest_signal_contract.json` and `.md`
- places no orders and invokes no order APIs
- reports `signal_contract_validated=true`, `signal_evaluation_enabled=false`,
  `generated_signals=false`, `signal_count=0`, `generated_orders=false`,
  `orders_simulated=false`, `fills_simulated=false`, `portfolio_accounting=false`,
  and `pnl_calculated=false`
- does not perform real signal evaluation, generate trading signals, create
  order intents, simulate orders or fills, maintain portfolio accounting, or
  compute P&L

Workflow relationship:

```text
history-snapshot -> history-load -> backtest-feed -> backtest-run -> strategy-contract -> strategy-runner -> signal-contract
```

`signal-contract` validates schema and diagnostics only. It is not connected to
real strategy evaluation and does not produce trading outputs. Common failures:

- No snapshots found: run or review `history-index` and `history-load`.
- Empty feed: inspect the snapshot and loader reports.
- Missing required bar fields: review the signal contract report before future signal work.
- Partial feed: review missing-symbol summaries in the frame context sample.

## Offline Fixture Stress Tests

```bash
python -m pytest tests/test_offline_stress_loader.py
python -m pytest tests/test_offline_stress_backtest_feed.py
python -m pytest tests/test_offline_stress_backtest_engine.py
python -m pytest tests/test_offline_stress_strategy_runner.py
python -m pytest tests/test_offline_stress_signal_contract.py
```

Expected behavior:

- opens no broker socket
- uses temporary synthetic historical snapshots only
- does not read real broker data or require local `data/historical/` files
- validates clean, partial, gapped, duplicate, malformed, missing, empty, and invalid datasets
- verifies loader diagnostics for malformed JSONL, missing manifests, missing bars files, duplicate timestamps, timestamp gaps, invalid OHLC, negative volume, and empty datasets
- verifies `backtest-feed` union/intersection alignment and explicit missing-bar counts
- verifies `backtest-run` ready, partial, and failed feed diagnostics
- verifies `strategy-contract`, `strategy-runner`, and `signal-contract` missing-symbol handling and diagnostics-only behavior
- places no orders and invokes no order APIs
- does not perform real strategy evaluation, generate signals, generate order intents, simulate orders, simulate fills, maintain portfolio accounting, or compute P&L

The stress suite is intentionally test-only for now. It does not add an
operator-facing CLI report, which keeps the offline diagnostic surface small
until a future milestone needs fixture reports.

## Dry-Run Plan

```bash
python -m trader.cli plan --strategy momentum --dry-run
```

Expected behavior:

- uses deterministic mock quotes
- emits strategy signals
- builds trade plans
- runs risk checks
- writes JSON and Markdown reports
- places no orders

## Market Probe

```bash
python -m trader.cli probe --symbols SPY,QQQ,AAPL
```

Expected behavior:

- prints deterministic mock quote data
- opens no broker socket

## Troubleshooting

If config is rejected, inspect environment variables first:

- `TRADING_MODE` must be `paper`, `dry_run`, or `backtest`.
- `ALLOW_LIVE_ORDERS` must be `false`.
- `IBKR_PORT` must not be `7496` or `4001`.
- Paper TWS normally uses `IBKR_PORT=7497`.
- Paper IB Gateway normally uses `IBKR_PORT=4002`.
- Risk limits must be positive.
- `UNIVERSE` must contain at least one valid symbol.

If `python -m trader.cli ...` cannot import `trader`, install the project:

```bash
python -m pip install -e .
```

If `broker-probe` fails:

- Install the optional broker dependency: `python -m pip install -e ".[dev,broker]"`.
- Run `scripts/check-ibapi.sh`.
- Confirm TWS or IB Gateway is running and logged in.
- In TWS, open `Global Configuration -> API -> Settings`.
- Enable `ActiveX and Socket Clients`.
- Keep `Read-Only API` enabled.
- Match the configured socket port to `IBKR_PORT`.
- Try a unique `IBKR_CLIENT_ID` if another API client is connected.
- Keep the host on `127.0.0.1` or `localhost`.
- Remember that market data subscriptions are not required for current-time probing.
- The Python `ibapi` `connect()` call may return `None` even when the API session is healthy; readiness is confirmed by callbacks such as `connectAck`, `nextValidId`, or a successful current-time response.
- IBKR farm-status messages such as `2104`, `2106`, `2107`, and `2158` are non-fatal for the current-time probe. `2107` means the historical-data farm is inactive until needed and should not block this read-only check.

## Safe Next Milestones

1. Review the new stress coverage and choose a first explicitly approved signal-evaluation contract.
2. Add read-only market-data subscription diagnostics behind explicit flags.
3. Write a paper-execution activation proposal before changing `PaperExecutor` to submit anything.

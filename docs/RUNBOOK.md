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

Expected paper broker success prerequisites:

- Paper TWS or paper IB Gateway is open and logged in.
- API socket clients are enabled.
- Socket port is `7497` for TWS paper or `4002` for IB Gateway paper.
- `Read-Only API` remains enabled.
- `IBKR_CLIENT_ID` is not already in use.
- Broker-contact commands are run sequentially, not in parallel, when gathering
  acceptance evidence. Use fresh client IDs for retries and leave a short pause
  between broker stages.

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

## First Alpha Paper-Order Smoke

Run this only after `alpha-shadow-run` has completed against paper TWS or paper IB Gateway with no
orders submitted. Keep normal development defaults at `ALLOW_PAPER_ORDERS=false`
and IBKR Read-Only API enabled until the exact smoke window.

For IB Gateway paper, first refresh same-commit read-only evidence sequentially
on port `4002`:

```bash
export TRADING_MODE=paper
export ALLOW_PAPER_ORDERS=false
export ALLOW_LIVE_ORDERS=false
export IBKR_HOST=127.0.0.1
export IBKR_PORT=4002
export BROKER_KIND=ib_gateway
export MAX_TRADE_NOTIONAL=1000
export MAX_OPEN_POSITIONS=1
export CAMPAIGN_ID=campaign-YYYYMMDD-spy-001

export IBKR_CLIENT_ID=53
python -m trader.cli broker-probe --timeout 30

export IBKR_CLIENT_ID=61
python -m trader.cli alpha-shadow-run --campaign-id "$CAMPAIGN_ID" --broker-timeout 30 --history-timeout 45 --broker-stage-pause 2
```

Required operator setup for the smoke window:

- Paper TWS or paper IB Gateway is open and logged in.
- API socket clients are enabled.
- Socket port is `7497` for TWS paper or `4002` for IB Gateway paper.
- IBKR Read-Only API is disabled only while running this command.
- Environment is paper-only:

```bash
export TRADING_MODE=paper
export ALLOW_PAPER_ORDERS=true
export ALLOW_LIVE_ORDERS=false
export IBKR_HOST=127.0.0.1
export IBKR_PORT=4002
export IBKR_CLIENT_ID=21
export MAX_TRADE_NOTIONAL=1000
```

First run the untransmitted rehearsal:

```bash
python -m trader.cli paper-order-smoke --campaign-id "$CAMPAIGN_ID" --symbol SPY --quantity 1 --transmit false --confirm PAPER_SMOKE_SPY_1
```

Then run one transmitted non-marketable paper limit order and cancel it if
unfilled:

```bash
python -m trader.cli paper-order-smoke --campaign-id "$CAMPAIGN_ID" --symbol SPY --quantity 1 --transmit true --allow-fill false --cancel-after-seconds 30 --confirm PAPER_SMOKE_SPY_1
```

Expected behavior:

- refuses unless `TRADING_MODE=paper`, paper port `7497` or `4002`, and client
  ID `21` are configured
- refuses unless `ALLOW_PAPER_ORDERS=true` and `ALLOW_LIVE_ORDERS=false`
- refuses symbols other than SPY, quantities other than `1`, market orders,
  futures, options, shorts, fractional/cash quantity stock orders, and batches
- writes masked JSON and Markdown reports under `reports/`
- records the no-secret `campaign_id`; later reconcile and summary fail closed
  if source report campaign IDs differ
- records `openOrder`, `orderStatus`, `execDetails`, API errors, and cancel
  status when callbacks are available

After the smoke run:

```bash
export ALLOW_PAPER_ORDERS=false
```

Re-enable IBKR Read-Only API unless actively running a gated paper execution
command.

## First Strategy-Gated Alpha Paper Run

Run this only after a same-commit read-only alpha shadow report and a
same-commit transmitted paper-order smoke report have passed within 24 hours.
Keep normal development defaults at `ALLOW_PAPER_ORDERS=false` and IBKR
Read-Only API enabled until the exact alpha paper window.

Required operator setup for the alpha paper window:

- Paper TWS or paper IB Gateway is open and logged in.
- API socket clients are enabled.
- Socket port is `7497` for TWS paper or `4002` for IB Gateway paper.
- IBKR Read-Only API is disabled only while running this command.
- Environment is paper-only:

```bash
export TRADING_MODE=paper
export ALLOW_PAPER_ORDERS=true
export ALLOW_LIVE_ORDERS=false
export IBKR_HOST=127.0.0.1
export IBKR_PORT=4002
export IBKR_CLIENT_ID=21
export MAX_TRADE_NOTIONAL=1000
```

Then run:

```bash
python -m trader.cli alpha-paper-run --campaign-id "$CAMPAIGN_ID" --symbol SPY --quantity 1 --allow-fill false --cancel-after-seconds 30 --confirm ALPHA_PAPER_SPY_1
```

Expected behavior:

- refuses unless prerequisite reports include `commit_sha` matching current
  `HEAD` and are within the freshness window
- refuses when prerequisite reports carry different `campaign_id` values
- refuses unless the transmitted `paper-order-smoke` report proves paper-only
  order lifecycle handling
- returns `no_trade` without an order when the shadow signal is HOLD/no-signal
  or risk did not approve
- submits at most one SPY BUY 1 `LMT DAY` paper order only when the shadow
  signal is BUY and risk approved
- writes masked JSON and Markdown reports under `reports/`

After the alpha paper run:

```bash
export ALLOW_PAPER_ORDERS=false
```

Re-enable IBKR Read-Only API unless actively running a gated paper execution
command.

## Post-Paper-Run Reconciliation

Run this immediately after `paper-order-smoke` or `alpha-paper-run`, once the
paper execution window is closed.

Required operator setup:

- Re-enable IBKR Read-Only API.
- Set `ALLOW_PAPER_ORDERS=false`.
- Keep `ALLOW_LIVE_ORDERS=false`.
- Keep paper IB Gateway on `127.0.0.1:4002` or paper TWS on
  `127.0.0.1:7497`; live ports `4001` and `7496` remain rejected.
- Run the commands sequentially, not in parallel.

For IB Gateway paper:

```bash
export TRADING_MODE=paper
export ALLOW_PAPER_ORDERS=false
export ALLOW_LIVE_ORDERS=false
export IBKR_HOST=127.0.0.1
export IBKR_PORT=4002
export BROKER_KIND=ib_gateway
export IBKR_CLIENT_ID=11
```

Then reconcile current broker state:

```bash
python -m trader.cli paper-reconcile --campaign-id "$CAMPAIGN_ID" --timeout 30
```

Expected behavior:

- contacts IBKR through read-only account, positions, open-order, and
  current-day execution requests
- reads latest ignored `paper-order-smoke` and `alpha-paper-run` reports for
  order ID and perm ID evidence
- derives or verifies the same no-secret `campaign_id` across source reports
  and fails closed on mismatches
- reports masked account IDs, open-order count, latest order IDs, latest perm
  IDs, position-query completion, zero-position confirmation, execution order
  IDs, commission rows, broker-state fingerprint, warnings, and errors
- reports `submitted_orders=false`, `paper_orders_enabled=false`,
  `order_routing_enabled=false`, and `order_api_invoked=false`
- fails if filled order evidence lacks a matching broker execution row
- fails if a real broker account summary is unavailable; mock fallback data is
  not accepted as success

Finally summarize the local campaign evidence:

```bash
python -m trader.cli alpha-test-summary --campaign-id "$CAMPAIGN_ID"
python -m trader.cli paper-ledger-update --campaign-id "$CAMPAIGN_ID"
```

Expected behavior:

- runs offline only and does not contact IBKR
- verifies same-commit, fresh `alpha-shadow-run`, transmitted
  `paper-order-smoke`, `alpha-paper-run`, and `paper-reconcile` reports
- verifies source reports share the same `campaign_id`
- fails closed if `paper-reconcile` is older than the latest submitted paper
  smoke or alpha paper report
- records fill/cancel outcome, order IDs, perm IDs, open-order count, masked
  account evidence, source report paths, warnings, errors, and next eligibility
- writes ignored JSON and Markdown reports under `reports/`

`paper-ledger-update` runs offline after the summary. It upserts one masked
campaign row into ignored local `state/paper_ledger.jsonl` and writes an ignored
update report under `reports/`. It fails closed when the summary or
reconciliation is not from the current commit, the campaign IDs differ, broker
account evidence is unavailable, broker positions were not queried, open orders
remain, the broker-state fingerprint is missing, or summary order/perm IDs are
missing from broker-state evidence.

## Sequential Alpha Campaign Runner

After the individual stages are understood, use `alpha-campaign-run` to reduce
manual report stitching while keeping the same safety boundaries.

Shadow mode runs only the read-only shadow path:

```bash
export ALLOW_PAPER_ORDERS=false
export IBKR_CLIENT_ID=61
python -m trader.cli alpha-campaign-run --mode shadow --campaign-id "$CAMPAIGN_ID" --broker-timeout 30 --history-timeout 45 --broker-stage-pause 2
```

Paper mode runs the existing strategy-gated alpha paper runner, then switches
its post-run config view to `ALLOW_PAPER_ORDERS=false`, runs reconciliation,
and writes the alpha test summary:

```bash
export ALLOW_PAPER_ORDERS=true
export IBKR_CLIENT_ID=21
python -m trader.cli alpha-campaign-run --mode paper --campaign-id "$CAMPAIGN_ID" --read-only-off-confirm READ_ONLY_OFF_FOR_ALPHA_PAPER --allow-fill false --cancel-after-seconds 30
```

Paper mode still requires the operator to disable IBKR Read-Only API only for
the execution window and re-enable it immediately afterward. It does not add new
order routes; any order submission still flows through the existing SPY-only
`alpha-paper-run` and paper-smoke executor boundary.

## Controlled Alpha Shadow Daemon

Run this only after individual read-only shadow campaigns are stable. It is the
first autonomous mode, but it remains shadow-only: no paper orders, no live
ports, no market orders, no direct futures, no options, no P&L, and no
portfolio accounting.

Required operator setup:

- IBKR Read-Only API remains enabled.
- `ALLOW_PAPER_ORDERS=false`.
- `ALLOW_LIVE_ORDERS=false`.
- Paper IB Gateway remains on `127.0.0.1:4002` or paper TWS on
  `127.0.0.1:7497`.
- Use a broker client ID dedicated to shadow daemon cycles.
- Run with a finite `--max-cycles` until repeated sessions are clean.

For IB Gateway paper:

```bash
export TRADING_MODE=paper
export ALLOW_PAPER_ORDERS=false
export ALLOW_LIVE_ORDERS=false
export IBKR_HOST=127.0.0.1
export IBKR_PORT=4002
export BROKER_KIND=ib_gateway
export IBKR_CLIENT_ID=61
export MAX_TRADE_NOTIONAL=1000
export MAX_OPEN_POSITIONS=1
export CAMPAIGN_ID=campaign-YYYYMMDD-spy-shadow-daemon-001

python -m trader.cli alpha-shadow-daemon --campaign-id "$CAMPAIGN_ID" --max-cycles 5 --interval-seconds 300 --stale-after-minutes 1440
```

Expected behavior:

- runs bounded read-only SPY shadow cycles through the existing
  `alpha-shadow-run` path
- writes per-cycle shadow reports and an ignored heartbeat file at
  `state/alpha_shadow_daemon_heartbeat.json`
- stops failed on stale source bars, broker/account failures, or safety
  violations
- halts safely before a cycle when `state/alpha_shadow_daemon.kill` exists
- reports clean-cycle count and `graduation_ready=true` only after the
  configured clean-session threshold is met
- reports `submitted_orders=false`, `paper_orders_enabled=false`,
  `order_routing_enabled=false`, and `order_api_invoked=false`

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

## Offline Data Quality Gate

```bash
python -m trader.cli data-quality-gate --symbols SPY,AAPL,GLD,USO,DBA --bar-size "5 mins" --what-to-show TRADES
python -m trader.cli data-quality-gate --symbols DBA --max-zero-volume-bars 1
scripts/run-data-quality-gate.sh
```

Expected behavior:

- opens no broker socket
- reads local historical snapshots through the offline loader and readiness checks
- validates minimum bars, zero-volume bars, duplicate timestamps, missing gaps,
  malformed records, invalid OHLC, negative volume, and stale snapshots
- writes `reports/data_quality_gate_<timestamp>.json` and `.md`
- updates `reports/latest_data_quality_gate.json` and `.md`
- reports `broker_contacted=false`, `signal_evaluation_enabled=false`,
  `generated_signals=false`, `signal_count=0`, `order_intents_generated=false`,
  `orders_simulated=false`, `fills_simulated=false`,
  `portfolio_accounting=false`, `pnl_calculated=false`,
  `futures_contracts_enabled=false`, and `direct_futures_data_enabled=false`
- does not contact IBKR, evaluate signals, create order intents, simulate fills,
  maintain portfolio accounting, compute P&L, or route orders

Use the default gate before interpreting `signal-evaluate` or
`evaluator-compare` output. Known partial symbols such as a low-volume
commodity-linked proxy can be documented with an explicit threshold override,
but the default command should fail closed until the data issue is reviewed.
Common failures:

- No snapshots found: run `history-snapshot` while TWS paper is available.
- Minimum bars failed: collect a longer or more liquid historical sample.
- Zero-volume bars: inspect the symbol, market hours, and product liquidity before using the data.
- Duplicate timestamps or missing gaps: regenerate the snapshot or document the partial data boundary.
- Invalid OHLC, malformed lines, or negative volume: treat the snapshot as failed input.
- Stale snapshot: refresh historical data before current readiness claims.

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
history-snapshot -> history-load -> backtest-feed -> backtest-run -> strategy-contract -> strategy-runner -> signal-contract -> signal-runner
```

`signal-contract` validates schema and diagnostics only. It is not connected to
real strategy evaluation and does not produce trading outputs. Common failures:

- No snapshots found: run or review `history-index` and `history-load`.
- Empty feed: inspect the snapshot and loader reports.
- Missing required bar fields: review the signal contract report before future signal work.
- Partial feed: review missing-symbol summaries in the frame context sample.

## Offline Disabled Signal Runner

```bash
python -m trader.cli signal-runner --symbols SPY,AAPL
python -m trader.cli signal-runner --symbols SPY,AAPL --alignment union
python -m trader.cli signal-runner --symbols SPY,AAPL --alignment intersection
python -m trader.cli signal-runner --symbols SPY,AAPL --bar-size "5 mins" --what-to-show TRADES
scripts/run-signal-runner.sh
```

Expected behavior:

- opens no broker socket
- loads local snapshots through the offline historical loader
- builds an aligned feed with the broker-free data adapter
- routes each feed frame through the disabled signal contract
- records one signal evaluation context and one diagnostic per frame
- writes `reports/signal_runner_<timestamp>.json` and `.md`
- updates `reports/latest_signal_runner.json` and `.md`
- places no orders and invokes no order APIs
- reports `disabled_signal_runner=true`, `signal_contract_validated=true`,
  `signal_evaluation_enabled=false`, `generated_signals=false`,
  `signal_count=0`, `generated_orders=false`,
  `order_intents_generated=false`, `orders_simulated=false`,
  `fills_simulated=false`, `portfolio_accounting=false`, and
  `pnl_calculated=false`
- does not perform real signal evaluation, generate trading signals, create
  order intents, simulate orders or fills, maintain portfolio accounting, or
  compute P&L

Workflow relationship:

```text
history-snapshot -> history-load -> backtest-feed -> backtest-run -> strategy-contract -> strategy-runner -> signal-contract -> signal-runner
```

`signal-runner` exercises only the disabled signal contract. It is not connected
to real signal evaluation and does not produce trading outputs. Common failures:

- No snapshots found: run or review `history-index` and `history-load`.
- Empty feed: inspect the snapshot and loader reports.
- Failed feed: inspect loader and feed adapter errors before rerunning.
- Partial feed: review missing-symbol summaries in the runner report.

## Offline Analytical Signal Evaluation

```bash
python -m trader.cli signal-evaluate --symbols SPY,AAPL
python -m trader.cli signal-evaluate --symbols SPY,AAPL --alignment union
python -m trader.cli signal-evaluate --symbols SPY,AAPL --alignment intersection
python -m trader.cli signal-evaluate --symbols SPY,AAPL --short-window 5 --long-window 20
scripts/run-signal-evaluate.sh
```

Expected behavior:

- opens no broker socket
- loads local snapshots through the offline historical loader
- builds an aligned feed with the broker-free data adapter
- evaluates the `moving_average_relationship_diagnostic` condition using bars available at or before each frame timestamp
- writes `reports/signal_evaluation_<timestamp>.json` and `.md`
- updates `reports/latest_signal_evaluation.json` and `.md`
- reports `signal_evaluation_enabled=true`, `generated_signals=false`,
  `signal_count=0`, `generated_orders=false`,
  `order_intents_generated=false`, `orders_simulated=false`,
  `fills_simulated=false`, `portfolio_accounting=false`, and
  `pnl_calculated=false`
- does not contact IBKR, generate trading signals, create order intents,
  simulate orders or fills, maintain portfolio accounting, or compute P&L

Workflow relationship:

```text
history-snapshot -> history-load -> backtest-feed -> backtest-run -> strategy-contract -> strategy-runner -> signal-contract -> signal-runner -> signal-evaluate
```

`signal-evaluate` is analytical diagnostics only. Its condition states are
`condition_met`, `condition_not_met`, `insufficient_data`, and `invalid_data`.
Common failures:

- No snapshots found: run or review `history-index` and `history-load`.
- Empty feed: inspect the snapshot and loader reports.
- Failed feed: inspect loader and feed adapter errors before rerunning.
- Warm-up observations: collect more local bars before interpreting condition counts.
- Invalid data observations: inspect OHLCV quality in the source snapshot.

## Offline Evaluator Comparison

```bash
python -m trader.cli evaluator-compare --symbols SPY,AAPL,GLD,USO,DBA --window-pairs 5:20,10:30
python -m trader.cli evaluator-compare --symbols SPY,AAPL --window-pairs 5:20,10:20 --train-fraction 0.7
scripts/run-evaluator-compare.sh
```

Expected behavior:

- opens no broker socket
- loads local snapshots through the offline historical loader
- builds a broker-free feed
- reruns the approved `moving_average_relationship_diagnostic` evaluator for
  each `short:long` candidate pair
- compares chronological train/test condition counts and condition-met rates
- writes `reports/evaluator_comparison_<timestamp>.json` and `.md`
- updates `reports/latest_evaluator_comparison.json` and `.md`
- reports `broker_contacted=false`, `signal_evaluation_enabled=true`,
  `generated_signals=false`, `signal_count=0`, `order_intents_generated=false`,
  `orders_simulated=false`, `fills_simulated=false`,
  `portfolio_accounting=false`, and `pnl_calculated=false`
- does not rank a trade recommendation, optimize P&L, create order intents,
  simulate fills, contact IBKR, or route orders

Run `data-quality-gate` first. Treat comparison output as research diagnostics
only; it is not evidence of profitability or readiness to submit paper orders.
Common failures:

- Bad `--window-pairs`: use comma-separated `short:long` pairs such as `5:20,10:30`.
- No snapshots or empty feed: run `history-index`, `history-load`, and the data-quality gate.
- Warm-up-heavy output: collect more bars or use smaller windows for diagnostics.
- Failed data feed: fix loader and data-quality errors before comparing candidates.

## Offline Commodity Research Universe

```bash
python -m trader.cli commodity-universe
python -m trader.cli commodity-universe --symbols GLD,USO,DBA
scripts/run-commodity-universe.sh
```

Expected behavior:

- opens no broker socket
- lists configured commodity-linked security proxies only
- writes `reports/commodity_universe_<timestamp>.json` and `.md`
- updates `reports/latest_commodity_universe.json` and `.md`
- reports `commodity_proxy_universe=true`, `futures_contracts_enabled=false`,
  `direct_futures_data_enabled=false`, `broker_contacted=false`,
  `signal_evaluation_enabled=false`, `generated_signals=false`,
  `signal_count=0`, `order_intents_generated=false`,
  `orders_simulated=false`, `fills_simulated=false`,
  `portfolio_accounting=false`, and `pnl_calculated=false`
- does not enable direct futures contracts, request futures data, model futures
  roll or margin, evaluate signals, create order intents, simulate fills, or
  compute P&L

Use this command before adding commodity symbols to snapshot or evaluation runs.
It keeps the current program in commodity-linked securities until a separate
futures-contract, rollover, margin, and risk-model milestone is explicitly
approved.

## Read-Only Paper Readiness Run

Prerequisites:

- Paper TWS or paper IB Gateway is open and logged in.
- API socket clients are enabled on paper port `7497` for TWS or `4002` for
  IB Gateway.
- Read-Only API remains enabled.
- `TRADING_MODE=paper`.
- `ALLOW_PAPER_ORDERS=false`.
- The paper account has a broker account summary available through IBKR.

```bash
python -m trader.cli paper-readiness-run
python -m trader.cli paper-readiness-run --symbols SPY,AAPL,GLD,USO,DBA --commodity-symbols GLD,USO,DBA
python -m trader.cli paper-readiness-run --broker-stage-pause 2
scripts/run-paper-readiness-run.sh
```

The command runs these stages sequentially:

```text
broker-probe --timeout 15
pause between broker-contact stages, default 1 second
account --connect --timeout 15
pause between broker-contact stages, default 1 second
history-snapshot --symbols SPY,AAPL,GLD,USO,DBA --duration "1 D" --bar-size "5 mins" --what-to-show TRADES --use-rth 1 --timeout 30
history-load --symbols SPY,AAPL,GLD,USO,DBA --bar-size "5 mins" --what-to-show TRADES
commodity-universe --symbols GLD,USO,DBA
signal-evaluate --symbols SPY,AAPL,GLD,USO,DBA --bar-size "5 mins" --what-to-show TRADES --short-window 5 --long-window 20
```

Expected behavior:

- contacts IBKR only through read-only broker, account-summary, and historical-data requests
- uses distinct IBKR client IDs for broker-contact stages: base ID, base ID + 1, and base ID + 2
- rejects mock account fallback as readiness success
- writes stage reports under `reports/`
- writes `reports/paper_readiness_run_<timestamp>.json` and `.md`
- updates `reports/latest_paper_readiness_run.json` and `.md`
- reports `submitted_orders=false`, `paper_orders_enabled=false`,
  `read_only_api_expected=true`, and `order_routing_enabled=false`
- uses commodity-linked security proxies only and keeps direct futures out of scope
- keeps signal evaluation diagnostic-only with `generated_signals=false` and
  `signal_count=0`

Final statuses:

- `completed`: broker/account verified, snapshots loaded, and evaluator completed with ready data.
- `completed_with_warnings`: broker/account verified and evaluator completed, but at least one symbol is partial.
- `failed`: broker probe failed, broker account summary was unavailable, no usable snapshots loaded, or signal evaluation failed.

Common failures:

- Account stage falls back to mock data: keep the paper broker logged in, confirm API socket settings, and rerun.
- No historical snapshots: check market-data permissions, symbol availability, market hours, and pacing.
- Partial symbol readiness: inspect `reports/latest_history_readiness.json` and
  `reports/latest_history_load.json` before expanding the universe.
- Signal evaluation failed: inspect loader/feed errors before changing evaluator logic.

## Offline Fixture Stress Tests

```bash
python -m pytest tests/test_offline_stress_loader.py
python -m pytest tests/test_offline_stress_backtest_feed.py
python -m pytest tests/test_offline_stress_backtest_engine.py
python -m pytest tests/test_offline_stress_strategy_runner.py
python -m pytest tests/test_offline_stress_signal_contract.py
python -m pytest tests/test_offline_stress_signal_runner.py
python -m pytest tests/test_offline_stress_signal_evaluation.py
python -m pytest tests/test_commodity_universe.py
python -m pytest tests/test_paper_readiness_run.py
python -m pytest tests/test_data_quality_gate.py
python -m pytest tests/test_evaluator_comparison.py
```

Expected behavior:

- opens no broker socket
- uses temporary synthetic historical snapshots only
- does not read real broker data or require local `data/historical/` files
- validates clean, partial, gapped, duplicate, malformed, missing, empty, and invalid datasets
- verifies loader diagnostics for malformed JSONL, missing manifests, missing bars files, duplicate timestamps, timestamp gaps, invalid OHLC, negative volume, and empty datasets
- verifies `backtest-feed` union/intersection alignment and explicit missing-bar counts
- verifies `backtest-run` ready, partial, and failed feed diagnostics
- verifies `strategy-contract`, `strategy-runner`, `signal-contract`, `signal-runner`, and `signal-evaluate` missing-symbol handling and diagnostics-only behavior
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
- IBKR farm-status messages such as `2103`, `2104`, `2105`, `2106`, `2107`, `2108`, and `2158` are non-fatal for the current-time probe. Request-specific timeouts or permission errors still fail the affected market-data or historical-data stage.

## Safe Next Milestones

1. Review `signal-evaluate` reports after each new read-only historical snapshot refresh.
2. Keep analytical evaluator expansion broker-free and non-actionable until a future milestone explicitly changes the boundary.
3. Do not add buy/sell/hold outputs, order intents, order simulation, fills, portfolio accounting, P&L, broker routing, paper execution, or live trading in the next planning pass.
4. Write a paper-execution activation proposal before changing `PaperExecutor` to submit anything.

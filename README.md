# IBKR Quant System

Safety-first Python foundation for broker-free SPY research and staged Interactive Brokers paper-account validation through Trader Workstation or IB Gateway.

This project is infrastructure-first. It is not a profitability claim or a live trading bot. Paper order APIs remain confined to one explicit lifecycle-test module; autonomous paper execution is not implemented.

## What Is Implemented

- Strict config loading with fail-closed defaults.
- Serializable domain models for quotes, signals, trade plans, risk decisions, fills, positions, and accounts.
- Pure strategy layer that emits signals only.
- Portfolio construction that converts signals into trade plans.
- Risk layer that returns explicit approve/block decisions.
- Execution router that accepts only risk-approved plans.
- Deterministic simulator.
- Refusing paper executor stub.
- Shared broker-free SPY moving-average target-state policy used by research and shadow paths.
- Catalog-backed SPY research simulation with dual price views, limit-order modeling,
  explicit costs, capital events, portfolio accounting, and daily performance evidence.
- Preregistered chronological research experiments with append-only final-holdout access.
- Offline vendor-data bake-off, immutable catalog-v2 lineage, batch import, derived views,
  and checksum-valid catalog loading.
- Read-only IBKR TWS / IB Gateway broker probe with current-time diagnostics.
- Masked managed-account discovery when the broker API is reachable.
- Read-only IBKR market-data diagnostics for contract resolution, delayed quote capture,
  spread checks, quote freshness, and small historical-bar samples.
- Read-only historical snapshot ingestion and readiness reports for future simulation inputs.
- Broker-free offline historical snapshot indexing and loading for future simulation inputs.
- Broker-free backtest data feed scaffold for aligning offline historical datasets.
- Broker-free backtest engine skeleton for deterministic data-frame replay diagnostics.
- Broker-free strategy interface contract scaffold with no-op diagnostics only.
- Broker-free inert strategy runner scaffold that routes frames through no-op diagnostics only.
- Broker-free offline fixture stress tests for partial, gapped, duplicate, malformed, missing, and invalid historical datasets.
- Broker-free disabled signal contract scaffold with diagnostics only.
- Broker-free disabled signal diagnostic runner that records per-frame signal diagnostics only.
- Broker-free analytical signal evaluator that emits non-actionable condition observations only.
- Broker-free commodity research universe for commodity-linked security proxies only.
- Read-only paper readiness orchestration for the first broker-connected program run.
- Broker-free data-quality gate for local historical snapshots.
- Broker-free analytical evaluator comparison diagnostics for approved moving-average windows.
- GitHub Actions CI for tests, lint, typecheck, whitespace, and safety scans.
- Python 3.11 and 3.12 CI coverage plus global order-API and sensitive-artifact scans.
- Strict-live shadow warmup assembly and multi-session fingerprint/drift evidence.
- JSON and Markdown reports under `reports/`.
- Tests that require no TWS or IB Gateway.

## What Is Not Implemented

- Live trading.
- Live executor.
- General-purpose broker order submission.
- Autonomous paper-order daemon.
- Market orders.
- Profit optimization.
- A profitability-validated or production-certified strategy.
- Strategy-driven broker order submission.
- Research execution from ad hoc IBKR snapshot datasets; research commands require
  passing active catalog revisions.
- Real strategy evaluation, signal generation, order simulation, or P&L from strategy-contract checks.
- Real strategy evaluation, buy/sell/hold signal generation, order-intent generation, fill simulation, portfolio accounting, or P&L from strategy-runner checks.
- Real signal evaluation, buy/sell/hold outputs, order intents, order simulation, fill simulation, portfolio accounting, or P&L from signal-contract checks.
- Real signal evaluation, buy/sell/hold outputs, order intents, order simulation, fill simulation, portfolio accounting, or P&L from signal-runner checks.
- Trading instructions, order intents, execution, fill simulation, portfolio accounting, or P&L from analytical signal-evaluation checks.
- Trading instructions, order intents, execution, fill simulation, portfolio accounting, P&L, or broker contact from data-quality gates or evaluator comparisons.
- Direct futures contracts, futures roll modeling, futures margin modeling, or commodity futures execution.

## Safety Design

Normal strategy order-shaped objects must flow through:

```text
signal -> trade plan -> risk validation -> execution router -> simulator or paper executor -> journal
```

Strategy modules must never import broker or execution code.

The manually gated `paper-order-smoke` lifecycle test is an isolated exception
for SPY paper-only API validation. It cannot be called by a strategy and is the
only production module allowlisted for `placeOrder` or `cancelOrder`.

Default settings:

- `TRADING_MODE=paper`
- `ALLOW_PAPER_ORDERS=false`
- `ALLOW_LIVE_ORDERS=false`

The initial version rejects `TRADING_MODE=live`, rejects `ALLOW_LIVE_ORDERS=true`, and rejects live IBKR ports `7496` and `4001`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

The broker client is required only for real TWS / IB Gateway probes. Download
the current Stable or Latest TWS API from IBKR's official download page, install
its `source/pythonclient` directory into the active virtual environment, then run:

```bash
scripts/check-ibapi.sh
```

On Windows, use `scripts/check-ibapi.ps1`. The check is offline and requires
client protocol support at least `163`; it never connects to IBKR or invokes
order APIs. The repo intentionally does not install `ibapi` from PyPI because
IBKR does not host, endorse, or support that distribution channel.

Copy the example config only when you need local overrides:

```bash
cp .env.example .env
```

Do not commit `.env`.

## Validate

```bash
python -m pytest -p no:cacheprovider
python -m ruff check --no-cache src tests scripts
python -m mypy src
git diff --check
python scripts/check_order_api_allowlist.py
python scripts/check_no_sensitive_artifacts.py
```

## Dry-Run Commands

```bash
python -m trader.cli --help
python -m trader.cli status
python -m trader.cli preflight
python -m trader.cli preflight --connect
python -m trader.cli broker-probe
python -m trader.cli market-probe --symbols SPY,AAPL --data-type delayed
python -m trader.cli market-probe --symbols SPY,AAPL --data-type delayed --historical
python -m trader.cli history-snapshot --symbols SPY,AAPL --duration "1 D" --bar-size "5 mins" --what-to-show TRADES --use-rth 1
python -m trader.cli history-readiness --latest
python -m trader.cli ibkr-data-diagnostics --min-bars 50 --stale-after-minutes 15
python -m trader.cli history-index
python -m trader.cli history-load --symbols SPY,AAPL
python -m trader.cli data-quality-gate --symbols SPY,AAPL,GLD,USO,DBA --bar-size "5 mins" --what-to-show TRADES
python -m trader.cli history-inspect --symbol SPY
python -m trader.cli backtest-feed --symbols SPY,AAPL
python -m trader.cli backtest-feed --symbols SPY,AAPL --alignment intersection
python -m trader.cli backtest-run --symbols SPY,AAPL
python -m trader.cli backtest-run --symbols SPY,AAPL --alignment intersection
python -m trader.cli research-data-ingest --source-file <licensed-massive.csv.gz>
python -m trader.cli research-data-audit
python -m trader.cli research-data-bakeoff --manifest <local-manifest.json>
python -m trader.cli research-data-import-batch --source-dir <licensed-files> --vendor massive --kind minute_bars
python -m trader.cli research-data-derive
python -m trader.cli research-catalog-load --price-view split_adjusted_signal
python -m trader.cli research-backtest --symbol SPY --short-window 5 --long-window 20
python -m trader.cli research-walk-forward --symbol SPY --window-pairs 5:20,10:30,20:50
python -m trader.cli research-experiment-run --spec research/experiments/spy_sma_2016_2025_v1.json --phase development
python -m trader.cli strategy-contract --symbols SPY,AAPL
python -m trader.cli strategy-contract --symbols SPY,AAPL --alignment intersection
python -m trader.cli strategy-runner --symbols SPY,AAPL
python -m trader.cli strategy-runner --symbols SPY,AAPL --alignment intersection
python -m trader.cli signal-contract --symbols SPY,AAPL
python -m trader.cli signal-contract --symbols SPY,AAPL --alignment intersection
python -m trader.cli signal-runner --symbols SPY,AAPL
python -m trader.cli signal-runner --symbols SPY,AAPL --alignment intersection
python -m trader.cli signal-evaluate --symbols SPY,AAPL
python -m trader.cli signal-evaluate --symbols SPY,AAPL --short-window 5 --long-window 20
python -m trader.cli evaluator-compare --symbols SPY,AAPL,GLD,USO,DBA --window-pairs 5:20,10:30
python -m trader.cli commodity-universe
python -m trader.cli commodity-universe --symbols GLD,USO,DBA
python -m trader.cli paper-readiness-run
python -m trader.cli alpha-shadow-run
scripts/check-ibapi.sh
scripts/run-broker-preflight.sh
python -m trader.cli account --mock
python -m trader.cli positions --mock
python -m trader.cli probe --symbols SPY,QQQ,AAPL
python -m trader.cli plan --strategy momentum --dry-run
python -m trader.cli simulate --plan latest
```

Helper scripts:

```bash
scripts/run-tests.sh
scripts/run-lint.sh
scripts/run-preflight.sh
scripts/check-ibapi.sh
scripts/run-broker-preflight.sh
scripts/run-broker-probe.sh
scripts/run-dry-plan.sh
scripts/run-market-probe.sh
scripts/run-market-probe.sh --symbols SPY,AAPL,NVDA --data-type delayed --historical
scripts/run-history-snapshot.sh
scripts/run-history-load.sh
scripts/run-data-quality-gate.sh
scripts/run-backtest-feed.sh
scripts/run-backtest-run.sh
scripts/run-strategy-contract.sh
scripts/run-strategy-runner.sh
scripts/run-signal-contract.sh
scripts/run-signal-runner.sh
scripts/run-signal-evaluate.sh
scripts/run-evaluator-compare.sh
scripts/run-commodity-universe.sh
scripts/run-paper-readiness-run.sh
scripts/run-alpha-shadow-run.sh
```

## IBKR Paper Notes

Interactive Brokers TWS must be running before a future socket client can connect. TWS API access must be enabled in TWS API settings. The documented default TWS paper socket port is `7497`; the documented TWS live socket port is `7496` and is disabled by this repo.

IB Gateway paper on `4002` and TWS paper on `7497` are supported localhost endpoints. IB Gateway live `4001` and TWS live `7496` are rejected by this repo.

`broker-probe` opens a local read-only API socket only to request current server time and masked managed-account identifiers. It does not enable paper execution, does not route orders, and writes `reports/broker_probe_<timestamp>.json` plus `.md`.

Broker-probe reports include `connection_attempted`, `failure_stage`, `ibapi_available`, `ibapi_import_error`, `order_routing_enabled=false`, and `no_order_guarantee=true`.

Broker data requests treat IBKR farm-status callbacks as readiness diagnostics. Contract resolution waits for the security-definition farm OK callback before requesting contract details, so startup races fail with a clear readiness error instead of routing ahead while TWS is still initializing API services.

`market-probe` is also read-only. It may call IBKR contract, market-data, and
historical-data request APIs, then cleans up data requests with `cancelMktData`
and `cancelHistoricalData`. It does not submit, modify, or cancel orders.

`history-snapshot` is read-only data infrastructure. It requests bounded
historical bars, stores local JSONL snapshots under `data/historical/`, writes
matching manifests, and produces readiness reports for future backtesting and
simulation work. The snapshots are generated artifacts and are ignored by Git.

`history-index`, `history-load`, and `history-inspect` are offline-only. They
read local snapshot JSONL and manifest files, normalize bars into reusable
datasets, write loader reports, and do not contact IBKR or import broker clients.

`data-quality-gate` is offline-only. It reads local snapshot loader and
readiness diagnostics, applies explicit symbol gates for minimum bars,
zero-volume bars, duplicate timestamps, missing gaps, malformed records,
invalid OHLC, negative volume, and stale snapshots, then writes reports. It does
not contact IBKR, evaluate signals, generate order intents, model direct
futures, simulate fills, perform portfolio accounting, or compute P&L.
Zero-volume diagnostics include bounded sample timestamps so partial ETF data
warnings can be audited without opening raw snapshot JSONL files.
Optional average-volume and average-dollar-volume thresholds can be set for
broker-free liquidity screening before a symbol is promoted into later
research gates. These thresholds do not generate signals, orders, fills, or
P&L.

`backtest-feed` is also offline-only. It reads loaded local historical datasets,
normalizes them into aligned bar-feed frames, writes feed reports, and does not
contact IBKR, evaluate strategies, simulate orders, or compute P&L.

`backtest-run` is an offline engine skeleton. It replays `backtest-feed` frames
deterministically, records frame-level diagnostics, writes run reports, and does
not contact IBKR, evaluate strategies, simulate orders, calculate fills, or
compute P&L.

`research-backtest` is the catalog-only SPY research simulator. It loads
split-adjusted five-minute bars for the shared target-state policy, raw
five-minute bars for simulated execution, and a daily total-return benchmark.
Orders are deterministic price-protected `LMT DAY` simulations with tick
rounding, trade-through rules, configurable volume participation, partial fills,
cancellations, spread, slippage, commissions, splits, and cash dividends. It
supports fixed quantity for engineering tests and unlevered target allocation
for return research. Reports include daily returns, cost scenarios, portfolio
accounting, P&L, drawdown duration, turnover, exposure, and benchmark-relative
metrics. Annualized CAGR, volatility, Sharpe, Sortino, and Calmar remain
unavailable until at least 30 completed daily observations exist. Every report
keeps `promotion_eligible=false`.

The same completed-bar `SPYSmaPolicy` supplies research and shadow target state.
Research may enter or reduce a simulated long position from that state; the
read-only shadow path emits BUY only for an `ENTER_LONG` transition. A
`HOLD_LONG` observation remains HOLD and cannot create a repeated trade plan.

`research-walk-forward` remains a non-promoting exploratory chronological tool.
The authoritative final-holdout workflow is `research-experiment-run`, which
requires a committed preregistration, loads only 2016-2023 in development, and
records one append-only catalog access before loading the 2024-2025 holdout.
Final access requires the exact confirmation in the tracked specification; a
failed or interrupted access still consumes the experiment. Review readiness is
reported separately from execution promotion and never routes orders.

The research-data commands maintain an external, offline-only SPY store.
`research-data-bakeoff` validates manually supplied vendor samples and written
rights without downloading data or reading credentials. Import commands archive
licensed raw files immutably; catalog v2 records revisions, corporate actions,
derived lineage, and experiment access. `research-data-derive` creates raw
execution, split-adjusted signal, and total-return benchmark views, while
`research-catalog-load` accepts only active checksum-valid revisions with exact
XNYS session coverage. Install `.[research]` first and keep licensed data,
catalogs, and reports outside Git. See `docs/RESEARCH_DATA_SPEC.md`.

`strategy-contract` is an offline interface scaffold. It validates a no-op
strategy contract against local feed frames, writes contract reports, and does
not contact IBKR, perform real strategy evaluation, generate signals, simulate
orders, or compute P&L.

`strategy-runner` is an offline inert runner scaffold. It routes local feed
frames through the no-op strategy diagnostic contract, writes runner reports, and
does not contact IBKR, evaluate real strategies, generate buy/sell/hold signals,
create order intents, simulate orders or fills, perform portfolio accounting, or
compute P&L.

`signal-contract` is an offline disabled contract scaffold. It validates the
future signal-evaluation schema against local feed frames, writes contract
reports, and does not contact IBKR, generate trading signals, create order
intents, simulate orders or fills, perform portfolio accounting, or compute
P&L. Reports always state `signal_evaluation_enabled=false` and
`signal_count=0`.

`signal-runner` is an offline disabled diagnostic runner. It routes local feed
frames through the disabled signal contract, records one diagnostic per frame,
writes runner reports, and does not contact IBKR, generate trading signals,
create order intents, simulate orders or fills, perform portfolio accounting,
or compute P&L. Reports always state `disabled_signal_runner=true`,
`signal_evaluation_enabled=false`, and `signal_count=0`.

`signal-evaluate` is an offline analytical evaluator. It loads local historical
snapshots, builds broker-free feed frames, compares fast and slow close-price
averages at each frame timestamp, and writes non-actionable condition
observations. It does not contact IBKR, generate trading signals, create order
intents, simulate orders or fills, perform portfolio accounting, or compute
P&L. Reports state `signal_evaluation_enabled=true`,
`generated_signals=false`, and `signal_count=0`.

`evaluator-compare` is an offline analytical comparison diagnostic. It reruns
the approved moving-average relationship evaluator over configured short/long
window pairs and compares chronological train/test condition counts. It does
not rank a tradable strategy, optimize P&L, generate trading signals, create
order intents, simulate fills, perform portfolio accounting, contact IBKR, or
route orders.

`commodity-universe` is an offline commodity research helper. It lists
commodity-linked security proxies such as metals, energy, agriculture, and broad
basket exchange-traded products. It does not contact IBKR, enable direct futures
contracts, model futures roll or margin, run signal evaluation, create order
intents, simulate fills, perform portfolio accounting, or compute P&L.

`paper-readiness-run` is the first read-only paper-client orchestration command.
It runs broker probe, broker account summary, historical snapshot, offline load,
commodity proxy universe, and analytical signal evaluation sequentially for the
default universe `SPY,AAPL,GLD,USO,DBA`. It requires a real broker account
summary with masked account output and funding-style summary tags. Mock account
fallback is a failed readiness run. It writes
`reports/paper_readiness_run_<timestamp>.json` plus `.md`, keeps
`paper_orders_enabled=false`, reports `submitted_orders=false`, and keeps direct
futures out of scope.

`alpha-shadow-run` is the broker-connected, read-only SPY alpha test. Use paper
IB Gateway `127.0.0.1:4002` or paper TWS `127.0.0.1:7497` with Read-Only API
enabled and `ALLOW_PAPER_ORDERS=false`. It runs broker/account checks, captures
the current completed live-bar prefix, then assembles it with complete cached
XNYS sessions. The warmup stage fails closed on forming bars, gaps, conflicting
overlaps, missing prior-session evidence, or stale current data; the freshness
gate applies only to the newest current bar. Data quality, the shared SPY policy,
dry-run risk, and simulator routing use that assembled feed. Reports include
masked account evidence, source/data/strategy fingerprints, and
`submitted_orders=false`, `paper_orders_enabled=false`, and
`order_api_invoked=false`.

`paper-order-smoke` is the first gated paper-only order lifecycle command. Run it
only after a passing `alpha-shadow-run`, with paper Gateway on
`127.0.0.1:4002` or paper TWS on `127.0.0.1:7497` and Read-Only API disabled
only for the smoke window. It requires
`TRADING_MODE=paper`, `ALLOW_PAPER_ORDERS=true`, `ALLOW_LIVE_ORDERS=false`,
`IBKR_CLIENT_ID=21`, `MAX_TRADE_NOTIONAL=1000`, and
`--confirm PAPER_SMOKE_SPY_1`. It is SPY-only, quantity `1`, STK/SMART/USD,
`LMT`, `DAY`, BUY-only, and refuses live ports, live mode, market orders,
direct futures, options, algos, brackets, shorts, fractional/cash quantity stock
orders, and batches. The rehearsal form records an untransmitted order:

```bash
python -m trader.cli paper-order-smoke --symbol SPY --quantity 1 --transmit false --confirm PAPER_SMOKE_SPY_1
```

The transmitted smoke form sends one non-marketable paper limit order, then
cancels it if unfilled:

```bash
python -m trader.cli paper-order-smoke --symbol SPY --quantity 1 --transmit true --allow-fill false --cancel-after-seconds 30 --confirm PAPER_SMOKE_SPY_1
```

After the smoke run, set `ALLOW_PAPER_ORDERS=false` again and re-enable the
Gateway/TWS Read-Only API unless actively running the gated paper execution command.
Reports are written to `reports/paper_order_smoke_<timestamp>.json` plus `.md`
with masked account IDs, order/cancel callback evidence, and no secrets.

After any paper order smoke or alpha paper window, run the read-only
post-run checks before continuing development:

```bash
python -m trader.cli paper-reconcile --campaign-id campaign-YYYYMMDD-spy-001 --timeout 30
python -m trader.cli alpha-test-summary --campaign-id campaign-YYYYMMDD-spy-001
python -m trader.cli paper-ledger-update --campaign-id campaign-YYYYMMDD-spy-001
```

`paper-reconcile` expects Read-Only API to be re-enabled and
`ALLOW_PAPER_ORDERS=false`. It captures masked account evidence, broker
positions, broker open orders, current-day execution/commission evidence,
latest local order IDs/perm IDs, and a broker-state fingerprint without
placing, modifying, or canceling orders. It distinguishes a completed
zero-position response from unavailable positions. `alpha-test-summary` is offline-only
and aggregates the latest alpha shadow, paper smoke, alpha paper, and
reconciliation reports into a no-secret campaign summary. Use one no-secret
`campaign_id` across `alpha-shadow-run`, `paper-order-smoke`, `alpha-paper-run`,
`paper-reconcile`, and `alpha-test-summary`; summary and reconciliation fail
closed when loaded source reports carry different campaign IDs.
`paper-ledger-update` is offline-only and upserts one masked campaign row into
ignored local `state/paper_ledger.jsonl` after the summary is eligible. It fails
closed on mismatched campaign IDs, different commit SHAs, unverified account
summary, incomplete broker positions query, open broker orders, missing broker
state fingerprint, or missing order/perm IDs in broker-state evidence. It does
not contact IBKR, enable paper orders, or invoke order APIs.

`alpha-campaign-run` wraps the staged workflow without adding new order routes.
Shadow mode runs the read-only alpha shadow stage and writes a top-level
campaign report:

```bash
python -m trader.cli alpha-campaign-run --mode shadow --campaign-id campaign-YYYYMMDD-spy-001
```

Paper mode is a deliberate Read-Only-off window over the existing alpha paper
runner, then it switches its post-run config view back to
`ALLOW_PAPER_ORDERS=false`, runs `paper-reconcile`, and writes
`alpha-test-summary`:

```bash
python -m trader.cli alpha-campaign-run --mode paper --campaign-id campaign-YYYYMMDD-spy-001 --read-only-off-confirm READ_ONLY_OFF_FOR_ALPHA_PAPER
```

Paper mode still requires existing same-commit alpha shadow and transmitted
paper smoke reports, `TRADING_MODE=paper`, `ALLOW_PAPER_ORDERS=true`,
`ALLOW_LIVE_ORDERS=false`, localhost, paper port `7497` or `4002`, and
`IBKR_CLIENT_ID=21`.

`ibkr-data-diagnostics` is an offline strict SPY freshness gate for
market-hours shadow testing. Run it after a fresh `broker-probe` and
`history-snapshot --symbols SPY --duration "1 D" --bar-size "5 mins"
--what-to-show TRADES --use-rth 1`. It reads ignored local reports only,
requires same-commit broker/account evidence, confirms at least `50` SPY bars,
checks the latest 5-minute bar age against `15` minutes, surfaces live
market-data subscription errors from the latest `market-probe` report, and
writes JSON/Markdown diagnostics. It never contacts IBKR and reports
`submitted_orders=false`, `paper_orders_enabled=false`, and
`order_api_invoked=false`.

`ibkr-delayed-data-diagnostics` is the separate non-graduating lane for accounts
that do not yet have live SPY API market data. Run it only after a delayed
`market-probe --symbols SPY --data-type delayed --historical` and a fresh SPY
`history-snapshot`. It uses the same broker/account and bar-count evidence, but
defaults to a wider `30` minute freshness gate, reports
`delayed_shadow_precheck_passed`, keeps `strict_shadow_precheck_passed=false`,
and marks reports `graduation_eligible=false`.

`alpha-shadow-daemon` is the first controlled autonomous mode. It repeats the
existing read-only SPY shadow path for a bounded number of cycles, atomically
updates a latest heartbeat, writes a campaign-specific immutable heartbeat under
ignored local `state/`, and halts failed on stale source bars or safety
violations. Use a unique campaign ID from a clean committed worktree. Keep IBKR
Read-Only API enabled and `ALLOW_PAPER_ORDERS=false`; the daemon never invokes
broker order APIs:

```bash
python -m trader.cli alpha-shadow-daemon --campaign-id campaign-YYYYMMDD-spy-shadow-daemon-001 --max-cycles 5 --interval-seconds 300 --stale-after-minutes 15
```

Use `alpha-shadow-daemon-delayed` only for delayed-data engineering practice:

```bash
python -m trader.cli alpha-shadow-daemon-delayed --campaign-id campaign-YYYYMMDD-spy-shadow-delayed-001 --max-cycles 5 --interval-seconds 300 --stale-after-minutes 30
```

Delayed daemon reports are explicitly non-graduating and are rejected by the
normal daemon summary as paper-execution readiness evidence.

Create the configured kill-switch file, default
`state/alpha_shadow_daemon.kill`, to stop before the next cycle. The daemon
reports `submitted_orders=false`, `paper_orders_enabled=false`,
`order_routing_enabled=false`, `order_api_invoked=false`, stale-data status,
clean-cycle count, heartbeat path, trading date, coverage window, release/config/
strategy/data fingerprints, and per-session evidence status. A single daemon
report never grants graduation. Paper execution daemons remain out of scope
until the offline multi-session gate and ledger-backed broker truth are stable.

`alpha-shadow-daemon-summary` is the offline drift gate for those sessions. It
checks report age, same-commit evidence, heartbeat presence, strict-live policy,
broker/account counts, release/config/strategy fingerprints, unique data
fingerprints, a clean committed release, campaign/heartbeat identity, distinct
XNYS trading dates, coverage windows, and all order-safety flags. Five clean
strict-live sessions on five dates set
`graduation_ready=true`; ten clean sessions over at least five dates with
opening, midday, and closing coverage set `engineering_pilot_ready=true`.
Delayed sessions never count. The summary does not contact IBKR and keeps
`submitted_orders=false`:

```bash
python -m trader.cli alpha-shadow-daemon-summary --report-glob='reports/alpha_shadow_daemon_*.json' --min-clean-sessions 5 --max-report-age-hours 168 --require-same-commit true
```

The offline fixture stress suite uses temporary synthetic historical snapshots
to validate loader, feed, engine, strategy-contract, strategy-runner, and
signal-contract/signal-runner/signal-evaluate behavior against partial, gapped,
duplicate, malformed, missing, empty, and invalid data.
It does not read broker data, contact IBKR, evaluate real strategies, generate
signals, simulate orders or fills, perform portfolio accounting, or compute P&L.

## References

- IBKR TWS API supported download and installation guidance: https://www.interactivebrokers.com/campus/ibkr-api-page/twsapi-doc/
- IBKR TWS API setup and paper/live ports: https://www.interactivebrokers.com/campus/trading-lessons/installing-configuring-tws-for-the-api/
- IBKR historical data retrieval: https://www.interactivebrokers.com/campus/ibkr-quant-news/how-to-retrieve-equity-data-through-the-python-api/
- IBKR market-data type behavior: https://interactivebrokers.github.io/tws-api/market_data_type.html
- IBKR order submission and transmit behavior: https://interactivebrokers.github.io/tws-api/order_submission.html
- IBKR placing-order callbacks: https://www.interactivebrokers.com/campus/trading-lessons/python-placing-orders/
- IBKR order types and paper-trading notes: https://www.interactivebrokers.com/campus/ibkr-api-page/order-types/
- IBKR API market-data requirements: https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/
- IBKR paper-account simulation limitations: https://www.interactivebrokers.com/campus/glossary-terms/paper-trading-account/
- IBKR contracts API reference: https://www.interactivebrokers.com/campus/ibkr-api-page/contracts/
- Massive stock flat-file specification: https://massive.com/docs/flat-files/stocks/overview
- Norgate U.S. stock package history: https://norgatedata.com/stockmarketpackages.php
- Probability of Backtest Overfitting: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Deflated Sharpe Ratio: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- FINRA algorithmic testing guidance: https://www.finra.org/rules-guidance/notices/15-09
- SEC market-access risk-control FAQ: https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/divisionsmarketregfaq-0
- CFTC futures market basics: https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/FuturesMarketBasics/index.htm
- CFTC commodity ETP advisory: https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/CustomerAdvisory_CommodityETPs.htm
- GitHub status checks: https://docs.github.com/articles/about-status-checks
- GitHub protected branches: https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
- QuantConnect Algorithm Framework overview: https://www.quantconnect.com/docs/v1/algorithm-framework/overview
- OpenAI Codex `AGENTS.md` guidance: https://developers.openai.com/codex/guides/agents-md

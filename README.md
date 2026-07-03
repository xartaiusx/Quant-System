# IBKR Quant System

Safety-first Python foundation for a quantitative trading system designed to integrate with Interactive Brokers Trader Workstation or IB Gateway in later phases.

This project is infrastructure-first. It is not a profitability engine, not a live trading bot, and not an order-placement tool.

## What Is Implemented

- Strict config loading with fail-closed defaults.
- Serializable domain models for quotes, signals, trade plans, risk decisions, fills, positions, and accounts.
- Pure strategy layer that emits signals only.
- Portfolio construction that converts signals into trade plans.
- Risk layer that returns explicit approve/block decisions.
- Execution router that accepts only risk-approved plans.
- Deterministic simulator.
- Refusing paper executor stub.
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
- JSON and Markdown reports under `reports/`.
- Tests that require no TWS or IB Gateway.

## What Is Not Implemented

- Live trading.
- Live executor.
- Real broker order submission.
- Market orders.
- Profit optimization.
- Production-grade backtesting.
- Trading decisions from live broker market data.
- Strategy evaluation from broker historical snapshots.
- Backtest strategy evaluation from offline snapshot datasets.
- Order simulation or P&L from offline snapshot datasets.
- Fill simulation, portfolio accounting, or P&L from backtest runs.
- Real strategy evaluation, signal generation, order simulation, or P&L from strategy-contract checks.
- Real strategy evaluation, buy/sell/hold signal generation, order-intent generation, fill simulation, portfolio accounting, or P&L from strategy-runner checks.
- Real signal evaluation, buy/sell/hold outputs, order intents, order simulation, fill simulation, portfolio accounting, or P&L from signal-contract checks.
- Real signal evaluation, buy/sell/hold outputs, order intents, order simulation, fill simulation, portfolio accounting, or P&L from signal-runner checks.
- Trading instructions, order intents, execution, fill simulation, portfolio accounting, or P&L from analytical signal-evaluation checks.
- Trading instructions, order intents, execution, fill simulation, portfolio accounting, P&L, or broker contact from data-quality gates or evaluator comparisons.
- Direct futures contracts, futures roll modeling, futures margin modeling, or commodity futures execution.

## Safety Design

Every possible order-shaped object must flow through:

```text
signal -> trade plan -> risk validation -> execution router -> simulator or paper executor -> journal
```

Strategy modules must never import broker or execution code.

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

Optional future broker adapter dependency:
Required only for real TWS / IB Gateway read-only probes:

```bash
python -m pip install -e ".[dev,broker]"
scripts/check-ibapi.sh
```

The default dev install intentionally does not require `ibapi`. The broker extra uses the official `ibapi` Python package when it is available from your package index. If that package is unavailable in your environment, install the official IBKR TWS API Python client manually, then rerun `scripts/check-ibapi.sh`.

Copy the example config only when you need local overrides:

```bash
cp .env.example .env
```

Do not commit `.env`.

## Validate

```bash
pytest
ruff check --no-cache src tests
mypy src
git diff --check
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
python -m trader.cli history-index
python -m trader.cli history-load --symbols SPY,AAPL
python -m trader.cli data-quality-gate --symbols SPY,AAPL,GLD,USO,DBA --bar-size "5 mins" --what-to-show TRADES
python -m trader.cli history-inspect --symbol SPY
python -m trader.cli backtest-feed --symbols SPY,AAPL
python -m trader.cli backtest-feed --symbols SPY,AAPL --alignment intersection
python -m trader.cli backtest-run --symbols SPY,AAPL
python -m trader.cli backtest-run --symbols SPY,AAPL --alignment intersection
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
```

## TWS Paper Notes

Interactive Brokers TWS must be running before a future socket client can connect. TWS API access must be enabled in TWS API settings. The documented default TWS paper socket port is `7497`; the documented TWS live socket port is `7496` and is disabled by this repo.

IB Gateway paper is documented as `4002`; IB Gateway live is documented as `4001` and is disabled by this repo.

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

`backtest-feed` is also offline-only. It reads loaded local historical datasets,
normalizes them into aligned bar-feed frames, writes feed reports, and does not
contact IBKR, evaluate strategies, simulate orders, or compute P&L.

`backtest-run` is an offline engine skeleton. It replays `backtest-feed` frames
deterministically, records frame-level diagnostics, writes run reports, and does
not contact IBKR, evaluate strategies, simulate orders, calculate fills, or
compute P&L.

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

The offline fixture stress suite uses temporary synthetic historical snapshots
to validate loader, feed, engine, strategy-contract, strategy-runner, and
signal-contract/signal-runner/signal-evaluate behavior against partial, gapped,
duplicate, malformed, missing, empty, and invalid data.
It does not read broker data, contact IBKR, evaluate real strategies, generate
signals, simulate orders or fills, perform portfolio accounting, or compute P&L.

## References

- IBKR TWS API setup and paper/live ports: https://www.interactivebrokers.com/campus/trading-lessons/installing-configuring-tws-for-the-api/
- IBKR contracts API reference: https://www.interactivebrokers.com/campus/ibkr-api-page/contracts/
- CFTC futures market basics: https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/FuturesMarketBasics/index.htm
- CFTC commodity ETP advisory: https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/CustomerAdvisory_CommodityETPs.htm
- GitHub status checks: https://docs.github.com/articles/about-status-checks
- GitHub protected branches: https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
- QuantConnect Algorithm Framework overview: https://www.quantconnect.com/docs/v1/algorithm-framework/overview
- OpenAI Codex `AGENTS.md` guidance: https://developers.openai.com/codex/guides/agents-md

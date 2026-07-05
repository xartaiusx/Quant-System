# Safety

## Dry-Run First

The first version is designed to be useful without a broker connection. CLI commands use deterministic mock data unless a later phase deliberately adds broker-backed reads.

No command places orders.

Milestone 2 adds a broker socket probe, but it is read-only. It may request current server time, managed account identifiers, account summaries, or positions. It does not enable paper execution and does not send order submission, order modification, or order cancellation requests.

Milestone 3 adds setup checks and clearer readiness diagnostics for the official IBKR Python API dependency. It does not add execution capability. Broker-probe reports must continue to include `order_routing_enabled=false`, `no_order_guarantee=true`, and a clear failure stage when setup or connectivity is incomplete.

Milestone 5 adds read-only market-data diagnostics. `market-probe` may resolve
contracts, request market-data type, collect quote ticks, and request a small
historical-bar sample. It does not place, modify, or cancel orders. `cancelMktData`
and `cancelHistoricalData` are permitted only as data-request cleanup operations;
`cancelOrder` remains forbidden.

Milestone 6 adds read-only historical snapshot ingestion. `history-fetch`,
`history-readiness`, and `history-snapshot` may request, store, and validate
historical bar data. They do not place, modify, or cancel orders.
`cancelHistoricalData` is permitted only as historical-data request cleanup.

## Live Trading Disabled

Live trading is impossible in this version by design:

- `TRADING_MODE=live` is rejected.
- `ALLOW_LIVE_ORDERS=true` is rejected.
- TWS live port `7496` is rejected.
- IB Gateway live port `4001` is rejected.
- No live executor exists.
- Broker probe order routing is always reported as disabled.

## Execution Gates

The only valid lifecycle is:

```text
signal -> trade plan -> risk validation -> execution router -> simulator or paper executor -> journal
```

Strategies emit `Signal` objects only. The portfolio layer creates `TradePlan` objects. The risk layer returns explicit `RiskDecision` objects. The router refuses unapproved decisions.

## Risk Checks

The initial risk engine blocks:

- oversized trade notional
- too many open positions
- exceeded daily-loss threshold
- excessive position percent of equity
- stale quotes
- missing quotes
- missing bid/ask
- duplicate symbol/action plans in one cycle
- live-order configuration hazards
- broker execution while paper orders are disabled

## Paper Trading Limitations

`ALLOW_PAPER_ORDERS=false` by default. The normal paper executor remains a
refusing stub for strategy and router paths. Paper execution must be enabled
only through the explicit paper-order smoke command described below.

Read-Only API in TWS is still recommended as a belt-and-suspenders control because it prevents API orders at the TWS setting level.

The read-only broker probe does not change `ALLOW_PAPER_ORDERS`, does not submit to the paper executor, and does not make paper order activation possible.

The read-only market-data probe does not change `ALLOW_PAPER_ORDERS`, does not
submit to the paper executor, and does not feed strategy, portfolio, risk, or
execution automation.

The historical snapshot commands do not change `ALLOW_PAPER_ORDERS`, do not
submit to the paper executor, and do not feed automated strategy evaluation or
execution.

Milestone 7 adds offline historical snapshot indexing and loading. `history-index`,
`history-load`, and `history-inspect` read local files under `data/historical/`
only. They do not import broker clients, open sockets, request IBKR data, place
orders, or route execution.

Milestone 8 adds a broker-free backtest data adapter scaffold. `backtest-feed`
reads local loaded historical datasets only, aligns bars into feed frames, and
does not contact a broker. It does not evaluate strategies, simulate orders,
compute P&L, submit to the paper executor, or route execution.

Milestone 9 adds a broker-free backtest engine skeleton. `backtest-run` replays
offline feed frames only and writes diagnostics. It never contacts a broker,
invokes order APIs, evaluates strategies, simulates orders, calculates fills,
maintains portfolio accounting, computes P&L, submits to the paper executor, or
routes execution.

Milestone 10 adds a broker-free strategy interface contract scaffold.
`strategy-contract` validates no-op strategy metadata and frame contexts only.
It never contacts a broker, invokes order APIs, performs real signal generation,
simulates orders, calculates fills, maintains portfolio accounting, computes
P&L, submits to the paper executor, or routes execution.

Milestone 11 adds a broker-free inert strategy runner scaffold. `strategy-runner`
routes offline feed frames through the no-op strategy diagnostic contract only.
It never contacts a broker, invokes order APIs, performs real strategy
evaluation, generates buy/sell/hold signals, creates order intents, simulates
orders, simulates fills, maintains portfolio accounting, computes P&L, submits
to the paper executor, or routes execution.

Milestone 12 adds broker-free offline stress fixtures. These tests create only
temporary synthetic historical snapshot data to validate partial, gapped,
duplicate, malformed, missing, empty, and invalid data behavior across the
loader, feed adapter, backtest engine, strategy contract, and inert strategy
runner. They never contact a broker, invoke order APIs, perform real strategy
evaluation, generate signals, create order intents, simulate orders or fills,
maintain portfolio accounting, compute P&L, submit to the paper executor, or
route execution.

Milestone 13 adds a broker-free disabled signal contract scaffold.
`signal-contract` validates future signal-evaluation schema and diagnostics
only. It never contacts a broker, invokes order APIs, performs real signal
evaluation, generates buy/sell/hold outputs, creates order intents, simulates
orders, simulates fills, maintains portfolio accounting, computes P&L, submits
to the paper executor, or routes execution.

Milestone 14 adds a broker-free disabled signal diagnostic runner.
`signal-runner` routes offline feed frames through the disabled signal contract
only. It never contacts a broker, invokes order APIs, performs real signal
evaluation, generates buy/sell/hold outputs, creates order intents, simulates
orders, simulates fills, maintains portfolio accounting, computes P&L, submits
to the paper executor, or routes execution.

Milestone 15 adds a broker-free analytical signal evaluator.
`signal-evaluate` reads offline feed frames only and emits non-actionable
condition observations. It never contacts a broker, invokes order APIs, creates
order intents, simulates orders, simulates fills, maintains portfolio
accounting, computes P&L, submits to the paper executor, or routes execution.
It reports `generated_signals=false` and `signal_count=0`.

Milestone 16 adds a broker-free commodity research universe.
`commodity-universe` lists commodity-linked security proxies only. It never
contacts a broker, enables direct futures contracts, requests futures data,
models futures roll or margin, invokes order APIs, evaluates signals, creates
order intents, simulates fills, maintains portfolio accounting, computes P&L,
submits to the paper executor, or routes execution.

Milestone 17 adds read-only paper readiness orchestration.
`paper-readiness-run` contacts IBKR only for broker probe, broker account
summary, and bounded historical-data reads, then switches back to offline
loading, commodity-proxy inspection, and analytical signal evaluation. It runs
sequentially, requires a real broker account summary with masked account output,
rejects mock account fallback as readiness success, keeps
`ALLOW_PAPER_ORDERS=false`, reports `submitted_orders=false`, keeps
`paper_orders_enabled=false`, does not activate the paper executor, and keeps
direct futures contracts out of scope.

Milestone 18 adds a broker-free data-quality gate. `data-quality-gate` reads
local snapshot loader and readiness diagnostics only. It may fail or warn on
minimum bars, zero-volume bars, duplicate timestamps, missing gaps, malformed
records, invalid OHLC, negative volume, or stale snapshots. It never contacts a
broker, invokes order APIs, evaluates signals, creates order intents, simulates
fills, maintains portfolio accounting, computes P&L, submits to the paper
executor, routes execution, or enables direct futures contracts.

Milestone 19 adds a broker-free analytical evaluator comparison.
`evaluator-compare` reruns approved diagnostic condition evaluators over
explicit parameter candidates and reports train/test condition counts only. It
never contacts a broker, invokes order APIs, ranks trade recommendations,
optimizes P&L, generates trading signals, creates order intents, simulates
fills, maintains portfolio accounting, submits to the paper executor, routes
execution, or enables direct futures contracts.

Milestone 20 adds `alpha-shadow-run`, the first broker-connected read-only
alpha test. It requires paper TWS on `127.0.0.1:7497` or paper IB Gateway on
`127.0.0.1:4002`, expects IBKR Read-Only API to remain enabled, requires
`ALLOW_PAPER_ORDERS=false`, runs SPY-only broker/account/history reads plus
offline quality/evaluator/risk/simulator stages, and reports
`submitted_orders=false`.

Milestone 21 adds `paper-order-smoke`, the only production path allowed to call
IBKR paper order APIs. It requires a passing read-only alpha shadow run before
manual use, then requires `TRADING_MODE=paper`, `ALLOW_PAPER_ORDERS=true`,
`ALLOW_LIVE_ORDERS=false`, `IBKR_HOST=127.0.0.1`, `IBKR_PORT=7497` for TWS
paper or `IBKR_PORT=4002` for IB Gateway paper, `IBKR_CLIENT_ID=21`,
`MAX_TRADE_NOTIONAL=1000`, and explicit confirmation. It
is limited to one SPY BUY 1 STK/SMART/USD `LMT DAY` order. It refuses live
mode, live ports, market orders, futures, options, algos, brackets, shorts,
fractional or cash-quantity stock orders, duplicate open smoke orders, stale or
missing quotes, and multi-order batches. IBKR Read-Only API should be disabled
only during this smoke window and re-enabled immediately afterward.

Milestone 22 adds `alpha-paper-run`, the first strategy-gated paper alpha
execution command. It requires same-commit, fresh `alpha-shadow-run` and
transmitted `paper-order-smoke` reports, requires `TRADING_MODE=paper`,
`ALLOW_PAPER_ORDERS=true`, `ALLOW_LIVE_ORDERS=false`, localhost, paper port
`7497` or `4002`, `IBKR_CLIENT_ID=21`, and explicit confirmation
`ALPHA_PAPER_SPY_1`. It submits no order for HOLD/no-signal or failed risk
approval. When all gates pass, it may submit at most one SPY BUY 1
STK/SMART/USD `LMT DAY` paper order through the existing paper-smoke execution
boundary. Live trading, live ports, market orders, futures, options, algos,
brackets, shorts, fractional or cash-quantity stock orders, and batches remain
disabled.

Milestone 23 adds post-paper-run hardening. `paper-reconcile` requires
`TRADING_MODE=paper`, `ALLOW_PAPER_ORDERS=false`,
`ALLOW_LIVE_ORDERS=false`, localhost, and paper port `7497` or `4002`. It is
read-only: it may request account summary, positions, open orders, and
current-day executions, but it must not submit, modify, or cancel orders. It
distinguishes completed zero-position responses from unavailable position data,
records execution and commission evidence when available, and fails if filled
paper-order evidence lacks a matching broker execution row. It reports
`submitted_orders=false`, `paper_orders_enabled=false`,
`order_routing_enabled=false`, and `order_api_invoked=false`, and it fails if a
real broker account summary is unavailable. `alpha-test-summary` is offline
only: it reads ignored local reports, validates same-commit source evidence,
verifies the no-secret `campaign_id` across source reports, fails closed on
campaign mismatches, and never contacts IBKR or invokes order APIs.

Milestone 24 adds `alpha-campaign-run`, a sequential orchestrator over existing
SPY-only campaign stages. Shadow mode calls the read-only alpha shadow runner.
Paper mode requires the explicit `READ_ONLY_OFF_FOR_ALPHA_PAPER` confirmation,
then uses the existing `alpha-paper-run` boundary, switches its post-run config
view to `ALLOW_PAPER_ORDERS=false`, runs `paper-reconcile`, and writes
`alpha-test-summary`. It adds no new production order API calls and does not
enable live trading, live ports, market orders, direct futures, options, algos,
brackets, shorts, fractional or cash-quantity stock orders, or batches.

Milestone 25 adds `paper-ledger-update`, an offline ignored local ledger updater
for completed SPY paper campaigns. It reads `alpha-test-summary` and
`paper-reconcile` reports, requires current-commit same-campaign evidence,
verified account summary, completed broker positions query, zero open broker
orders, broker-state fingerprint, and order/perm ID coverage in broker-state
evidence, then upserts one masked JSONL row under ignored `state/`. It never
contacts IBKR, enables paper orders, invokes order APIs, routes execution,
calculates P&L, or expands commodity execution.

Commodity scope remains research-only after paper execution hardening. `GLD`
and `USO` can be research candidates, `DBA` stays excluded from execution until
liquidity gates pass, and direct futures remain out of scope until an explicit
contract descriptor, expiry/multiplier, rollover, margin, and risk-model
milestone is approved.

## Quantitative Research Gate

No current milestone supports profitability, performance, or tradability claims.
Before any future real signal evaluation, simulation, fills, portfolio
accounting, or P&L milestone is approved, the plan must explicitly address:

- look-ahead bias and point-in-time data availability;
- survivorship bias and static-universe limitations;
- data snooping, overfitting, multiple-testing inflation, and out-of-sample or
  walk-forward validation;
- transaction costs, slippage, latency, market-impact assumptions, and fill
  realism;
- unsupported claims based on placeholder strategies, synthetic fixtures, or
  local diagnostic reports.

## Sensitive Data

Never commit:

- `.env`
- account numbers
- API credentials
- tokens
- broker logs with sensitive values
- raw account reports

Reports use masked config/account output.

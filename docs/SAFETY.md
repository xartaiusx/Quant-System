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

`ALLOW_PAPER_ORDERS=false` by default. The paper executor exists only as a refusing stub. Future paper execution must be added deliberately with tests and docs.

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

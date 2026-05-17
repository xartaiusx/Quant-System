# Safety

## Dry-Run First

The first version is designed to be useful without a broker connection. CLI commands use deterministic mock data unless a later phase deliberately adds broker-backed reads.

No command places orders.

Milestone 2 adds a broker socket probe, but it is read-only. It may request current server time, managed account identifiers, account summaries, or positions. It does not enable paper execution and does not send order submission, order modification, or order cancellation requests.

Milestone 3 adds setup checks and clearer readiness diagnostics for the official IBKR Python API dependency. It does not add execution capability. Broker-probe reports must continue to include `order_routing_enabled=false`, `no_order_guarantee=true`, and a clear failure stage when setup or connectivity is incomplete.

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

## Sensitive Data

Never commit:

- `.env`
- account numbers
- API credentials
- tokens
- broker logs with sensitive values
- raw account reports

Reports use masked config/account output.

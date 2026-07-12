# SPY Research Backtest Specification

## Scope

`research-backtest` is a broker-free, SPY-only simulation command. It loads only
passing active catalog-v3 revisions and never imports broker/execution modules,
opens an IBKR socket, invokes an order API, or submits an order. It is an
accounting and hypothesis-testing tool, not proof of profitability.

## Shared Strategy Policy

Backtest and alpha shadow use the same versioned `SPYSmaPolicy`. The policy
reads completed split-adjusted bars and returns a target state:

- `LONG` when the fast simple moving average is above the slow average;
- `FLAT` otherwise.

The policy reports its strategy version and parameter fingerprint. It does not
emit broker orders. The simulator trades only when current simulated position
differs from the target, removing the former mismatch where research traded
crossings while shadow emitted BUY on every `fast > slow` observation.

## Data And Timing

Every run loads three independent catalog views for the same requested dates:

- split-adjusted five-minute bars for signals;
- raw five-minute bars for simulated execution;
- split-and-dividend-adjusted daily benchmark observations.

Signal and execution timestamps must align exactly. Policy decisions use a
completed bar close. A new order may be evaluated no earlier than the next raw
bar, and the final-bar signal cannot fill. Warmup observations may initialize
indicators but cannot create fills, positions, P&L, or equity records for an
evaluation segment.

## Limit-Order Model

The intended paper order is SPY `LMT DAY`, so the simulator does not assume an
unconditional market-like next-open fill. It constructs a synthetic quote from
the configured spread around the raw reference price, adds the configured limit
buffer, rounds to the one-cent tick, and fills only when the bar trades through
the limit. Available fill size is capped by configured bar-volume participation.

The model records:

- submitted, filled, partially filled, canceled, and DAY-expired order states;
- reference, limit, and fill prices;
- spread, slippage, tick-rounding, and commission costs;
- remaining quantity and cancellation reason;
- an end-of-test accounting liquidation labeled separately when enabled.

OHLCV bars cannot reconstruct quote sequence, queue position, hidden liquidity,
or the intrabar path. Fill results are deterministic assumptions and must be
stress-tested rather than treated as observed execution quality. Every run
includes base, 2x, 3x, and 5x crisis-cost diagnostics; none substitutes for
quote-calibrated spread, slippage, or decision-to-arrival evidence.

## Sizing And Accounting

Two sizing modes are supported:

- `fixed_quantity`: positive integer quantity, default `1`, for engineering
  tests and parity fixtures;
- `target_allocation`: an unlevered integer share target using at most 100% of
  available simulated equity.

The simulator is long-only and maintains cash, integer quantity, cost basis,
mark-to-market equity, and closed trades. Splits change quantity and per-share
cost basis without creating economic P&L. Cash dividends are credited explicitly
for positions held into the ex-date. Shorts, leverage, fractional shares,
multi-symbol portfolios, options, futures, and broker execution are out of scope.

## Cost Scenarios And Metrics

Each report includes base, 2x, and 3x spread/slippage/commission scenarios. The
default base assumptions remain reproducible inputs, not claims about an IBKR
pricing tier or future fills:

- full spread: 2 basis points;
- slippage: 1 basis point per side;
- commission: $0.005 per share with a $1.00 minimum;
- tick size: $0.01;
- maximum volume participation: 1%.

Reports include orders, fills, trades, capital events, daily returns, cash,
position, equity, net/gross P&L, CAGR when supported, annualized volatility,
Sharpe, Sortino, Calmar, maximum drawdown and duration, turnover, exposure,
win rate, trial count, and benchmark-relative results. Unsupported statistics
remain unavailable rather than being manufactured from short samples. CAGR,
annualized volatility, Sharpe, Sortino, and Calmar require at least 30 completed
daily observations.

## Promotion Boundary

Every report preserves:

```text
promotion_eligible=false
broker_contacted=false
order_routing_enabled=false
submitted_orders=false
order_api_invoked=false
```

A standalone result cannot select or promote parameters. The authoritative
chronological and final-holdout controls are in
`docs/RESEARCH_VALIDATION_SPEC.md`. Strategy-driven paper alpha remains blocked
until both `research_review_ready=true` and the independent strict-live
operational gate are satisfied.

## References

- Probability of Backtest Overfitting: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Deflated Sharpe Ratio: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- FINRA testing and validation practices: https://www.finra.org/rules-guidance/notices/15-09
- IBKR paper-account limitations: https://www.interactivebrokers.com/campus/glossary-terms/paper-trading-account/

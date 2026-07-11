# SPY Research Backtest Specification

## Scope

`research-backtest` is a broker-free SPY-only research simulator. It reads
ignored local historical snapshots and never imports broker or execution
modules, opens an IBKR socket, invokes order APIs, or submits an order.

This milestone is an accounting and simulation foundation, not evidence that a
strategy is profitable. `research-walk-forward` supplies the next validation
layer, but neither command promotes a strategy automatically.

## Signal And Timing

- Strategy: long-only fast/slow simple moving-average crossover.
- Entry signal: fast average crosses from at or below the slow average to above it.
- Exit signal: fast average crosses from at or above the slow average to below it.
- Signals use completed bar closes only.
- A strategy signal can fill no earlier than the next bar open.
- The final bar cannot fill a new signal because no next bar exists.
- Optional end-of-test liquidation is labeled separately and uses the final close.
- Shorts, leverage, pyramiding, fractional quantity, and multi-symbol portfolios
  are out of scope.

## Fill And Cost Model

The input is OHLCV bar data, not a quote or order-book feed. The spread is
therefore an explicit model assumption rather than observed bid/ask evidence.

- Buy fill: next open plus half the configured spread plus configured slippage.
- Sell fill: next open minus half the configured spread and configured slippage.
- Commission: maximum of per-share commission and minimum commission per fill.
- Quantity: fixed positive integer, default `1`.
- Default full spread: `2` basis points.
- Default slippage: `1` basis point per side.
- Default commission: `$0.005` per share with a conservative `$1.00` minimum.

These defaults are reproducible research assumptions, not a claim about the
operator's actual IBKR pricing tier or future execution quality.

## Accounting

The simulator records:

- every signal and next-bar fill;
- cash and integer SPY position after each fill;
- mark-to-market equity after each bar;
- closed-trade gross and net P&L;
- commissions, modeled spread cost, and modeled slippage cost;
- total return, SPY buy-and-hold benchmark return, maximum drawdown, turnover,
  win rate, and market exposure;
- full JSON and Markdown evidence under ignored `reports/` paths.

Short samples are not annualized and do not receive Sharpe-ratio claims. A
single in-sample result must not be used to select or promote parameters.

## Promotion Boundary

Core reports must contain:

```text
promotion_eligible=false
evaluation_scope=in_sample_core
non_promotion_reason=walk_forward_and_sealed_oos_not_completed
broker_contacted=false
order_routing_enabled=false
submitted_orders=false
order_api_invoked=false
```

Chronological selection and final-holdout rules are specified in
`docs/RESEARCH_VALIDATION_SPEC.md`. Paper-daemon design remains blocked by
independent research review and the separate strict-live shadow-session gate.

## References

- Backtest-overfitting framework: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- FINRA algorithmic testing and validation guidance: https://www.finra.org/rules-guidance/notices/15-09
- SEC automated pre-trade risk-control principles: https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/divisionsmarketregfaq-0
- IBKR historical-data API guidance: https://www.interactivebrokers.com/campus/ibkr-quant-news/how-to-retrieve-equity-data-through-the-python-api/

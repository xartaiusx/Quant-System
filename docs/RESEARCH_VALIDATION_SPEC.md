# SPY Research Validation Specification

## Purpose

`research-walk-forward` tests a predeclared SPY moving-average candidate grid
without contacting IBKR. It is intended to reduce obvious temporal leakage and
single-split selection bias. It does not establish profitability and cannot
promote a strategy or unlock paper execution.

## Chronological Partitions

The final `holdout_bars` are removed before any model selection. The remaining
development bars are divided into anchored folds:

1. The first training segment contains every development bar before fold 1.
2. Every later training segment expands by one prior validation segment.
3. Validation segments are equal-sized, chronological, and non-overlapping.
4. Each fold evaluates every predeclared candidate on training data.
5. The deterministic training winner alone is evaluated on the immediately
   following validation segment.
6. Every candidate is evaluated once on all development bars. That development
   winner alone is evaluated on the final holdout.

Indicator warmup uses bars immediately before a validation or holdout boundary.
Warmup bars can update moving averages but cannot generate signals, fills,
positions, P&L, or equity observations. This avoids discarding the beginning of
each evaluation segment without allowing pre-segment simulated trades.

## Candidate Selection

The candidate grid is declared before the run. Duplicate pairs and pairs where
`short_window >= long_window` are rejected. A trial must complete and meet the
configured minimum closed-trade count.

The deterministic score is:

```text
total_return_pct - drawdown_penalty * max_drawdown_pct
```

The default drawdown penalty is `1`. Ties preserve the predeclared candidate
order. The score is transparent and deliberately simple; it is not a claim that
this objective is economically optimal.

## Holdout Controls

The report records SHA-256 fingerprints for the complete dataset, development
partition, final holdout, and serialized research specification. The holdout is
not passed to fold selection or full-development candidate selection. It is
evaluated at most once while building one report.

This is logical isolation, not tamper-proof experiment governance. The program
cannot prevent an operator from deleting reports, changing the candidate grid,
or rerunning after seeing holdout results. Every report therefore records
`operator_rerun_prevention_enforced=false` and remains
`promotion_eligible=false`. Treat a holdout as consumed after first access.

## Interpretation Limits

- Costs are explicit assumptions, not observed bid/ask or queue-position data.
- Five-minute bar simulation cannot reconstruct intrabar paths or limit-order
  fill probability.
- A small number of folds or trades has weak statistical power.
- Repeated experiments, candidate expansion, and informal tuning increase
  backtest-overfitting risk.
- Short samples are not annualized and receive no Sharpe-ratio claim.
- Historical SPY results do not prove future profitability.

Independent research review should assess data provenance, corporate-action
treatment, sample length, regime coverage, parameter stability, economic
rationale, transaction-cost sensitivity, and any consumed holdouts before a
signal is considered for strict-live shadow testing.

## Safety Invariants

```text
broker_contacted=false
order_routing_enabled=false
submitted_orders=false
order_api_invoked=false
holdout_used_for_selection=false
holdout_evaluation_count<=1
promotion_eligible=false
```

The module must not import broker or execution code and must not contain order
API calls. Commodity proxies and direct futures are outside this SPY-only
research command.

## Primary References

- Bailey et al., *The Probability of Backtest Overfitting*:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- FINRA Notice 15-09, algorithmic strategy testing and supervision:
  https://www.finra.org/rules-guidance/notices/15-09
- SEC market-access risk-control FAQ:
  https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/divisionsmarketregfaq-0

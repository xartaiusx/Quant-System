# SPY Research Validation Specification

## Purpose

The authoritative research gate is a preregistered, catalog-backed experiment,
not repeated inspection of a single backtest. It reduces avoidable lookahead,
selection, and holdout-reuse errors but does not establish future profitability
or automatically authorize paper execution.

`research-walk-forward` remains available for non-promoting exploratory
diagnostics. `research-experiment-run` is the only command that can report
`research_review_ready=true`.

## Preregistration

The active specification is committed at
`research/experiments/spy_sma_2016_2025_v2.json`. It supersedes only the
unconsumed v1 experiment and is registered before importing the sealed period.
It declares:

- strategy `spy_sma_target_state` version `1.0.0`;
- candidates `5:20`, `10:30`, and `20:50`;
- initial training period 2016-2018;
- anchored annual validation folds 2019-2023;
- untouched final holdout 2024-2025;
- unlevered target-allocation sizing and explicit cost assumptions;
- deterministic selection and review thresholds;
- at least 100 development trades, 12 trades in each validation year, and 30
  final-holdout trades;
- exact one-time final-holdout confirmation text.

`research-experiment-register` requires a clean worktree and records commit,
hash-locked dependency, pyproject, Python, official IBKR API, strategy,
configuration, and environment fingerprints. It permanently seals 2024-2025.
Generic catalog, backtest, and walk-forward loads reject any overlap with a
sealed period. The command fails before catalog data access when the spec is not
Git-tracked, changes after registration, supersedes a consumed experiment, uses
an invalid candidate grid, or violates period ordering.

## Development Phase

Development loads only catalog dates from 2016 through 2023. For each validation
year:

1. Training begins in 2016 and ends immediately before that validation year.
2. Every preregistered candidate is evaluated on training data.
3. Selection uses only the declared return-minus-drawdown rule.
4. The deterministic winner alone is evaluated on the untouched next calendar
   year.
5. All trials, fingerprints, costs, errors, and selected parameters are retained.

After annual folds, all candidates are evaluated on the full 2016-2023
development partition to select the one candidate eligible for final evaluation.
Development cannot load 2024-2025, create a holdout access row, or become
research-review ready.

## Final-Holdout Phase

The final phase reruns and verifies development from the same immutable spec and
catalog lineage. It then requires the exact confirmation string. Before loading
2024-2025, it appends a `holdout_access` row to catalog v3. Only then can the
capability-scoped final-holdout loader read the exact registered seal. That
record is the point of consumption: a missing dataset, failed simulation, interruption, or
unsatisfactory result still consumes the experiment. A second final access for
the same experiment ID is rejected.

A failed holdout cannot be tuned and rerun. Subsequent work requires a new
hypothesis/version and future forward evidence, not a relabeled reuse of the same
2024-2025 observations.

## Review Gates

`research_review_ready=true` requires every lineage and fold gate plus all of:

- at least four of five validation years positive after base costs;
- aggregate validation return nonnegative under 2x costs;
- explicit base, 2x, 3x, and 5x crisis-cost diagnostics;
- final-holdout return positive after base costs;
- Deflated Sharpe probability at least 0.95 when statistically supported;
- final-holdout maximum drawdown no worse than the total-return benchmark;
- eligible simulations, complete catalog fingerprints, and no errors.

The Deflated Sharpe Ratio is reported only when its observation and trial-count
requirements are supported. Probability of Backtest Overfitting is reported only
when a valid CSCV trial matrix exists; it is otherwise explicitly unavailable.
Neither statistic substitutes for untouched out-of-sample evidence.

Even a passing report keeps `promotion_eligible=false`. Review readiness is one
independent prerequisite for strategy-driven paper alpha, not an automatic
deployment decision.

Quote-calibrated spread/slippage and decision-to-arrival evidence remain a
required operator review item before consuming the holdout. The program does
not invent such evidence when licensed quote samples are unavailable.

## Interpretation Limits

- Five-minute OHLCV cannot reconstruct limit-order queue position or intrabar
  event order.
- Data licenses and corporate-action lineage must remain valid and auditable.
- Candidate expansion, repeated hypotheses, and informal tuning increase
  backtest-overfitting risk and must be counted as trials.
- Historical SPY results do not prove future returns.
- Delayed or strict-live shadow evidence cannot repair weak research evidence;
  operational and research gates are independent.

## Safety Invariants

```text
broker_contacted=false
credentials_read=false
network_accessed=false
order_routing_enabled=false
submitted_orders=false
order_api_invoked=false
promotion_eligible=false
```

The experiment module must remain SPY-only and broker/execution/order-API free.
Commodity proxies and direct futures remain outside this command.

## Primary References

- Bailey et al., Probability of Backtest Overfitting: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Bailey and Lopez de Prado, Deflated Sharpe Ratio: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- FINRA algorithmic testing guidance: https://www.finra.org/rules-guidance/notices/15-09

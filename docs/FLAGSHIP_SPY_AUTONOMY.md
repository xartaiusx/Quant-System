# Flagship SPY Paper-Autonomy Gates

## Objective

The near-term target is autonomous SPY paper trading, not live trading. Research
truth, current broker data, and execution evidence remain separate systems with
independent fail-closed gates. Passing one gate cannot substitute for another.

The autonomous paper daemon is intentionally not implemented in the current
milestone.

## Gate 1: Licensed Research Data

Required evidence:

- passing offline vendor bake-off and written usage/retention rights;
- complete immutable SPY minute data for calendar years 2016-2025;
- approved daily and corporate-action coverage from SPY inception through 2025;
- active checksum-valid catalog-v4 revisions and an immutable SPY identity;
- exact XNYS normal-session and early-close coverage;
- raw execution, split-adjusted signal, and total-return benchmark views;
- no stale parents, missing actions, or checksum drift.

Massive is the intraday candidate because its stock flat files provide SIP
minute aggregates, but those files are explicitly unadjusted. Norgate remains a
daily/action candidate only after its trial export and license pass the bake-off.
The 1993-2003 gap stays blocked if that evidence is unavailable.

## Gate 2: Research Review

The tracked v2 experiment uses 2016-2018 training, annual 2019-2023 validation, and
one untouched 2024-2025 final holdout. Development must complete before the
one-time holdout confirmation is used. The holdout access record is append-only
and any access consumes the experiment.

Strategy-driven paper alpha requires `research_review_ready=true`, including the
validation-year, 2x-cost, positive-holdout, Deflated Sharpe, drawdown, lineage,
simulation, and trade-count gates. Strategy-driven paper commands also require
the same-commit ten-session strict summary with lifecycle-pilot eligibility.
This flag never routes an order and never means the
strategy is profitable or approved for live trading.

## Gate 3: Strict-Live Operations

Delayed IBKR sessions are engineering evidence only and never graduate. Strict
sessions require funded/subscribed live SPY API data, paper Gateway `4002` or
paper TWS `7497`, Read-Only API enabled, `ALLOW_PAPER_ORDERS=false`, a real
masked account summary, and no order APIs.

Warmup combines complete cached XNYS sessions with the current completed
strict-live prefix. It must prove exact timestamp coverage and matching overlap
or structural session-boundary agreement. The 15-minute freshness check applies
only to the newest current bar, not to prior complete sessions.

The offline daemon summary requires stable release, configuration, strategy, and
data fingerprints, a clean committed worktree, and a matching campaign-specific
heartbeat. A campaign ID and its immutable heartbeat cannot be reused:

- five clean strict-live sessions on five distinct XNYS dates unlock paper-daemon
  implementation work;
- ten clean sessions across at least five dates and opening, midday, and closing
  coverage unlock a first lifecycle engineering pilot;
- any stale data, broker/account gap, heartbeat failure, duplicate data
  fingerprint, drift, delayed mode, or order-safety flag fails closed.

## Gate 4: Deferred Paper Daemon

Only after Gate 3 permits implementation may a separate reviewed milestone add a
disabled-by-default `alpha-paper-daemon --mode lifecycle|alpha`. It must retain:

- paper mode, localhost paper ports, a dedicated client ID, explicit confirmation,
  and Read-Only-off operator attestation;
- `ALLOW_PAPER_ORDERS=true`, `ALLOW_LIVE_ORDERS=false`, SPY only, quantity `1`,
  at most $1,000 notional, one order per trading date, and no shorts;
- fresh bid and ask no older than five seconds and spread no wider than five bps;
- SPY `LMT DAY` only, with no market, option, future, algo, bracket, fractional,
  cash-quantity, or batch order;
- durable ignored SQLite state, intent-before-submit persistence, idempotency,
  restart reconciliation, heartbeat, and kill switch;
- cancellation of only its known order, partial-fill reconciliation, and a halt
  on unknown broker state;
- no `reqGlobalCancel` and no live executor.

Lifecycle mode may proceed only after the ten-session operational gate. It sends
one deliberately non-marketable paper limit and cancels after 30 seconds; any
fill is a failed engineering pilot. Alpha mode additionally requires Gate 2 and
uses the shared target-state policy. BUY is allowed only from verified flat
state; SELL is allowed only to reduce a verified long SPY paper position.

IBKR states that paper fills are simulated from top-of-book data without deep
book access. Paper outcomes therefore validate software lifecycle and controls,
not production execution quality.

The existing manual `alpha-paper-run` and `alpha-campaign-run --mode paper`
now fail closed unless Gate 2 and the ten-session Gate 3 evidence are supplied.
The lifecycle-only `paper-order-smoke` remains exempt so connectivity can be
tested without claiming strategy readiness.

## Operating Targets

Every paper window must end with Read-Only restored, paper orders disabled,
broker reconciliation, ledger update, campaign summary, zero unmatched
executions, and zero residual open orders.

Targets before expanding behavior:

- 30 clean SPY paper sessions before strategy expansion;
- 60 clean SPY paper sessions before any separate live-candidate discussion;
- zero duplicate orders, unmatched executions, residual orders, or safety
  violations;
- 100% post-run reconciliation.

Live execution remains unimplemented.

## Commodity Boundary

GLD and USO remain research-only candidates. DBA remains excluded from execution
until liquidity gates pass. Direct futures require a separate program for
contract descriptors, expiry, rollover, multiplier, tick value, margin,
permissions, liquidity, and delivery risk. Commodity ETPs can also diverge from
their underlying exposure because futures expire and rolling contracts can add
material drag.

## Primary Sources

- Massive unadjusted stock flat files: https://massive.com/docs/flat-files/stocks/overview
- Norgate U.S. stock history packages: https://norgatedata.com/stockmarketpackages.php
- IBKR API market-data requirements: https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/
- IBKR paper-account limitations: https://www.interactivebrokers.com/campus/glossary-terms/paper-trading-account/
- FINRA algorithmic testing and monitoring: https://www.finra.org/rules-guidance/notices/15-09
- SEC market-access risk-control FAQ: https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/divisionsmarketregfaq-0
- CFTC commodity ETP advisory: https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/CustomerAdvisory_CommodityETPs.htm

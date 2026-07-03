# Signal Evaluation Spec

Status: implemented for `v0.13` as a broker-free analytical diagnostics
scaffold. The implementation adds `signal-evaluate`, report models, Markdown
reports, and tests while preserving all no-execution safety boundaries.

## Purpose

`v0.13` introduces the first broker-free analytical signal evaluator
scaffold. The evaluator may produce non-actionable diagnostic observations from
offline historical feed frames. It must not produce trading instructions, order
intents, fills, P&L, portfolio accounting, or broker contact.

## Safety Boundary

The evaluator path must remain offline and broker-free:

- no `trader.broker` imports;
- no `ibapi` imports;
- no socket connection attempts;
- no order APIs;
- no paper execution activation;
- no live trading;
- no order intents;
- no order simulation;
- no fill simulation;
- no P&L calculation;
- no portfolio accounting.

Output states are deliberately not trading actions. They describe whether an
analytical condition is true, false, unready, or invalid.

## Analytical Observation Model

Implemented model: `AnalyticalSignalObservation`.

Fields:

- `evaluator_name`: stable evaluator identifier.
- `evaluator_version`: semantic evaluator version.
- `symbol`: normalized symbol.
- `timestamp`: current feed-frame timestamp.
- `frame_index`: deterministic frame index.
- `condition_name`: stable diagnostic condition identifier.
- `condition_state`: one of the approved condition states.
- `numeric_value`: calculated diagnostic value, such as moving-average
  difference.
- `threshold_or_reference_value`: comparison reference, such as the long moving
  average.
- `required_lookback_bars`: minimum valid bars needed for the evaluator.
- `warmup_complete`: whether the lookback requirement is satisfied.
- `data_valid`: whether required bar data is present and internally valid.
- `explanation`: concise diagnostic explanation without action vocabulary.
- `generated_signals=false`.
- `signal_count=0`.
- `order_intents_generated=false`.
- `broker_contacted=false`.
- `pnl_calculated=false`.
- `portfolio_accounting=false`.

Approved `condition_state` values:

- `condition_met`
- `condition_not_met`
- `insufficient_data`
- `invalid_data`

Forbidden output vocabulary:

- `buy`
- `sell`
- `hold`
- `long`
- `short`
- `enter`
- `exit`
- `order`
- `position`
- `allocation`
- `rebalance`

The forbidden vocabulary may appear in documentation only when naming safety
boundaries, not as evaluator output.

## Evaluator Metadata

Implemented model: `AnalyticalSignalEvaluatorMetadata`.

Fields:

- `name`
- `version`
- `description`
- `required_fields`
- `required_lookback_bars`
- `supported_bar_sizes`
- `broker_required=false`
- `emits_trading_actions=false`
- `emits_order_intents=false`

Metadata validation should fail closed if an evaluator claims broker access,
trading-action output, or order-intent output.

## No-Lookahead Rule

At frame timestamp `T`, an evaluator may only use bars with
`bar.timestamp <= T`.

No future bars may be read from the feed, cached in the current context, used for
warm-up, or used for numeric calculations. Tests must include a future-bar
sentinel whose value would flip the observation if lookahead were present.

## Warm-Up Rule

If fewer than `required_lookback_bars` valid bars are available for the symbol at
frame timestamp `T`, the evaluator must return:

- `condition_state=insufficient_data`
- `warmup_complete=false`
- `generated_signals=false`
- `signal_count=0`

Warm-up output remains a diagnostic observation, not a trade decision.

## Invalid-Data Rule

If OHLCV fields are missing, non-numeric, non-finite, or internally invalid, the
evaluator must return:

- `condition_state=invalid_data`
- `data_valid=false`
- `generated_signals=false`
- `signal_count=0`

Invalid bars must not be silently repaired or converted into actionable output.

## First Evaluator

Implemented evaluator name: `moving_average_relationship_diagnostic`.

Purpose:

- Compare a short moving average with a long moving average using close prices
  available at the current frame timestamp.
- Return only an approved condition state.

Config:

- `short_window`: default `5`.
- `long_window`: default `20`.
- `required_lookback_bars`: `max(short_window, long_window)`.

Allowed calculations:

- short moving average;
- long moving average;
- difference between short and long averages;
- ratio when the long average is safely non-zero.

Allowed outputs:

- `condition_met`
- `condition_not_met`
- `insufficient_data`
- `invalid_data`

Forbidden outputs:

- `buy`
- `sell`
- `hold`
- `long`
- `short`
- `enter`
- `exit`

## CLI

Implemented commands:

```bash
python -m trader.cli signal-evaluate --symbols SPY,AAPL
python -m trader.cli signal-evaluate --symbols SPY,AAPL --short-window 5 --long-window 20
scripts/run-signal-evaluate.sh
```

The command must remain offline only. It should read local snapshots through the
historical loader, build a broker-free feed, evaluate observations, and print
that outputs are diagnostic-only and non-actionable.

## Reports

Implemented report files:

- `reports/signal_evaluation_<timestamp>.json`
- `reports/signal_evaluation_<timestamp>.md`
- `reports/latest_signal_evaluation.json`
- `reports/latest_signal_evaluation.md`

Reports must include:

- evaluator metadata;
- symbols requested;
- snapshot selection criteria;
- feed summary;
- observation counts by state;
- first and last evaluated timestamps;
- warm-up counts;
- invalid-data counts;
- warnings and errors;
- `generated_signals=false`;
- `signal_count=0`;
- `order_intents_generated=false`;
- `broker_contacted=false`;
- `orders_simulated=false`;
- `fills_simulated=false`;
- `pnl_calculated=false`;
- `portfolio_accounting=false`;
- `order_routing_enabled=false`;
- `no_order_guarantee=true`.

`signal_evaluation_enabled=true` is used for this approved analytical
diagnostic execution path. `generated_signals=false` and `signal_count=0`
remain required for this scaffold.

Reports must state that observations are non-actionable diagnostics and must not
make profitability, tradability, or performance claims.

## Test Plan

Implementation tests cover:

- model serialization;
- metadata validation;
- approved condition-state validation;
- forbidden output vocabulary rejection;
- warm-up handling;
- invalid-data handling;
- no-lookahead with a future-bar sentinel;
- deterministic frame and symbol ordering;
- partial feed missing-symbol handling;
- empty and failed feed failure modes;
- CLI fixture runs using temporary local snapshots;
- static scans for broker, `ibapi`, execution, portfolio, risk, and order API
  dependencies;
- paper executor refusal;
- live port rejection.

## Stress-Test Plan

Use synthetic fixtures only. Cover:

- clean data;
- partial overlap;
- gapped data;
- duplicate timestamps;
- malformed records;
- invalid OHLCV;
- missing symbols;
- empty datasets;
- no-lookahead future sentinel.

Every stress path must keep:

- `generated_signals=false`;
- `signal_count=0`;
- `order_intents_generated=false`;
- `orders_simulated=false`;
- `fills_simulated=false`;
- `pnl_calculated=false`;
- `portfolio_accounting=false`;
- `broker_contacted=false`.

## Acceptance Criteria

The implementation milestone is accepted only if:

- unit tests pass without IB Gateway;
- the evaluator path is broker-free;
- observations use only approved condition states;
- no-lookahead is proven by tests;
- warm-up and invalid-data states are explicit;
- no order APIs are added;
- no order intents are added;
- no fills, P&L, portfolio accounting, paper execution, or live trading are
  added;
- generated reports remain ignored.

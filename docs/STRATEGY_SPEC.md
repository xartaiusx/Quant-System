# Strategy Spec

## Current Strategies

### Momentum

`MomentumStrategy` uses deterministic two-point history in the initial version. It ranks positive returns and emits buy `Signal` objects for the strongest symbols.

This is a placeholder for infrastructure validation, not a profitable trading claim.

### Mean Reversion

`MeanReversionStrategy` is a minimal placeholder. It emits small buy signals after deterministic dips and includes TODOs for researched indicators.

## Signal Format

Signals include:

- id
- symbol
- direction
- strength
- confidence
- strategy name
- reason
- generated timestamp
- horizon

Signals are not orders.

## Trade Plan Lifecycle

```text
Signal
  -> TradePlan
  -> RiskDecision
  -> ExecutionRouter
  -> ExecutionResult
  -> Journal
```

The strategy layer must never import broker or execution modules.

## Future Research Ideas

- event-driven universe selection
- robust historical data validation
- factor research notebooks
- walk-forward validation
- transaction cost assumptions
- benchmark-relative reporting
- slippage model calibration
- regime detection

All future research must preserve the execution boundary.

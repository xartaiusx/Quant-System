#!/usr/bin/env bash
set -euo pipefail

python -m trader.cli alpha-shadow-run \
  --symbols "SPY" \
  --duration "1 D" \
  --bar-size "5 mins" \
  --what-to-show "TRADES" \
  --use-rth 1 \
  --broker-timeout 15 \
  --history-timeout 30 \
  --short-window 5 \
  --long-window 20 \
  --min-bars 50 \
  --max-zero-volume-bars 0 \
  --min-average-volume 100 \
  --min-average-dollar-volume 5000 \
  --max-trade-notional 1000 \
  --max-open-positions 1

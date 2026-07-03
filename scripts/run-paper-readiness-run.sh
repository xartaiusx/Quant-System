#!/usr/bin/env bash
set -euo pipefail

python -m trader.cli paper-readiness-run \
  --symbols "SPY,AAPL,GLD,USO,DBA" \
  --commodity-symbols "GLD,USO,DBA" \
  --duration "1 D" \
  --bar-size "5 mins" \
  --what-to-show "TRADES" \
  --use-rth 1 \
  --broker-timeout 15 \
  --history-timeout 30 \
  --short-window 5 \
  --long-window 20

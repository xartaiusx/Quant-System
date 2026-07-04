#!/usr/bin/env bash
set -euo pipefail

export TRADING_MODE=paper
export ALLOW_LIVE_ORDERS=false
export IBKR_HOST=127.0.0.1
export IBKR_PORT=7497
export IBKR_CLIENT_ID=21
export MAX_TRADE_NOTIONAL=1000

export ALLOW_PAPER_ORDERS="${ALLOW_PAPER_ORDERS:-false}"
: "${PAPER_ORDER_SMOKE_TRANSMIT:=false}"
: "${PAPER_ORDER_SMOKE_ALLOW_FILL:=false}"
: "${PAPER_ORDER_SMOKE_CANCEL_AFTER_SECONDS:=30}"

python -m trader.cli paper-order-smoke \
  --symbol SPY \
  --quantity 1 \
  --transmit "${PAPER_ORDER_SMOKE_TRANSMIT}" \
  --allow-fill "${PAPER_ORDER_SMOKE_ALLOW_FILL}" \
  --cancel-after-seconds "${PAPER_ORDER_SMOKE_CANCEL_AFTER_SECONDS}" \
  --confirm PAPER_SMOKE_SPY_1

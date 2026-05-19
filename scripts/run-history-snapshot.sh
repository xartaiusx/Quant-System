#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python}"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

if [[ "$#" -eq 0 ]]; then
  set -- \
    --symbols SPY,AAPL \
    --duration "1 D" \
    --bar-size "5 mins" \
    --what-to-show TRADES \
    --use-rth 1
fi

"${PYTHON_BIN}" -m trader.cli history-snapshot "$@"

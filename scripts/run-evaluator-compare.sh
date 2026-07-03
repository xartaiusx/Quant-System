#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python}"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

if [[ "$#" -eq 0 ]]; then
  set -- \
    --symbols SPY,AAPL,GLD,USO,DBA \
    --window-pairs 5:20,10:30 \
    --bar-size "5 mins" \
    --what-to-show TRADES
fi

"${PYTHON_BIN}" -m trader.cli evaluator-compare "$@"

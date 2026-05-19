#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python}"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

if [[ "$#" -eq 0 ]]; then
  set -- --symbols SPY,AAPL --alignment union
fi

"${PYTHON_BIN}" -m trader.cli strategy-contract "$@"

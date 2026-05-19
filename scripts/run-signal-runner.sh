#!/usr/bin/env bash
set -euo pipefail

if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="python"
fi

if [[ "$#" -eq 0 ]]; then
  set -- --symbols SPY,AAPL --alignment union
fi

"${PYTHON_BIN}" -m trader.cli signal-runner "$@"

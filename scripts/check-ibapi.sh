#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python}"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

echo "Python: ${PYTHON_BIN}"
"${PYTHON_BIN}" -m trader.broker.ibapi_compatibility

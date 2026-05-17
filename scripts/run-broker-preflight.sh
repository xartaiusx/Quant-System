#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python}"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

status=0

if ! "${PYTHON_BIN}" -m trader.cli preflight --connect "$@"; then
  status=1
fi

if ! "${PYTHON_BIN}" -m trader.cli broker-probe "$@"; then
  status=1
fi

exit "${status}"

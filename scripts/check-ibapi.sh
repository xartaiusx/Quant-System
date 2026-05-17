#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python}"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

echo "Python: ${PYTHON_BIN}"

if ! "${PYTHON_BIN}" -m pip show ibapi; then
  echo "ibapi package: missing"
  echo "Next step: activate the repo venv and install the optional broker extra:"
  echo '  python -m pip install -e ".[dev,broker]"'
  echo "No packages were installed by this script."
  exit 1
fi

if ! "${PYTHON_BIN}" -c "import ibapi; print('ibapi import: ok')"; then
  echo "ibapi import: failed"
  echo "Next step: repair or reinstall the optional broker dependency."
  echo "No packages were installed by this script."
  exit 1
fi

echo "ibapi readiness: ok"

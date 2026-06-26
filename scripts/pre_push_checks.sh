#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

EXPECTED_PYTHON_VERSION=""
if [[ -f "$ROOT_DIR/.python-version" ]]; then
  EXPECTED_PYTHON_VERSION="$(tr -d '[:space:]' < "$ROOT_DIR/.python-version")"
fi

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

echo "Running pre-push checks from: $ROOT_DIR"
echo "Using Python: $PYTHON_BIN"

if [[ -n "$EXPECTED_PYTHON_VERSION" ]]; then
  ACTUAL_PYTHON_VERSION="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ "$ACTUAL_PYTHON_VERSION" != "$EXPECTED_PYTHON_VERSION" ]]; then
    echo "ERROR: Expected Python $EXPECTED_PYTHON_VERSION, but got $ACTUAL_PYTHON_VERSION" >&2
    echo "Create/update .venv with Python $EXPECTED_PYTHON_VERSION to match CI." >&2
    exit 1
  fi
fi

"$PYTHON_BIN" -m ruff check .
"$PYTHON_BIN" -m ruff format --check .
"$PYTHON_BIN" -m pytest -q

echo "Pre-push checks passed."
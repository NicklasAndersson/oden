#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

echo "Running pre-push checks from: $ROOT_DIR"
echo "Using Python: $PYTHON_BIN"

"$PYTHON_BIN" -m ruff check .
"$PYTHON_BIN" -m ruff format --check .
"$PYTHON_BIN" -m pytest -q

echo "Pre-push checks passed."
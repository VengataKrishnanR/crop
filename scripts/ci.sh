#!/usr/bin/env bash
# CI entrypoint — runs the test suite offline (stub LLM, no network).
#   bash scripts/ci.sh            # SQLite suite
#   CI_PG=1 bash scripts/ci.sh    # also the full suite on PostgreSQL (Testcontainers, needs Docker)
set -euo pipefail

cd "$(dirname "$0")/.."

# Prefer the project venv's interpreter; fall back to python3.
if [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

echo "Using interpreter: $PY"
CCRE_LLM_MODE=stub "$PY" -m pytest tests -q
if [ "${CI_PG:-0}" = "1" ]; then
  echo "Full suite on PostgreSQL"
  CCRE_LLM_MODE=stub CCRE_TEST_PG=1 "$PY" -m pytest tests -q
fi

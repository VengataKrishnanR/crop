#!/usr/bin/env bash
# CI entrypoint — runs the full test suite offline (stub LLM, no network).
# Usage: bash scripts/ci.sh
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

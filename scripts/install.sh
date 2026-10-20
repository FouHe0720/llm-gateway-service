#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if command -v uv >/dev/null 2>&1; then
  UV_PYTHON_DOWNLOADS=never uv sync --frozen --extra dev --python python3
else
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements-dev.lock
  .venv/bin/python -m pip install --no-deps -e .
fi

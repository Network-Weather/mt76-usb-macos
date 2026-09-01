#!/usr/bin/env bash
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
# Run the publication checks that do not require firmware or attached hardware.
set -eu

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

PROJECT_PYTHON=${PROJECT_PYTHON:-.venv/bin/python}
if [ ! -x "$PROJECT_PYTHON" ]; then
  echo "missing $PROJECT_PYTHON; run bash setup.sh, then install .[dev]" >&2
  exit 1
fi

"$PROJECT_PYTHON" -m ruff format --check .
"$PROJECT_PYTHON" -m ruff check .
"$PROJECT_PYTHON" scripts/check_docs.py
bash -n setup.sh
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck setup.sh scripts/check.sh
else
  echo "shellcheck not installed; skipping semantic shell lint" >&2
fi
"$PROJECT_PYTHON" -m pytest -q
"$PROJECT_PYTHON" -m build --no-isolation
"$PROJECT_PYTHON" -m pip check

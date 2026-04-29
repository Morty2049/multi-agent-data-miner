#!/usr/bin/env bash
# Tally API server launcher.
#
# Why this script exists, and not just "uvicorn ..." in the README:
# Python normally writes .pyc files to chrome_plugin/__pycache__/. Chrome
# refuses to load extensions whose root directory contains files/dirs
# starting with "_" — see chrome://extensions error: "Cannot load
# extension with file or directory name __pycache__".
#
# Tests already set sys.dont_write_bytecode (conftest.py); but uvicorn
# imports api_server outside of pytest and would re-create __pycache__
# on every reload. Setting PYTHONDONTWRITEBYTECODE before python starts
# is the only reliable way to prevent it.
#
# Test that locks this in: tests/test_extension_layout.py.
set -euo pipefail

cd "$(dirname "$0")/.."

# Belt: env stops Python from writing bytecode anywhere in this process.
export PYTHONDONTWRITEBYTECODE=1

# Suspenders: if a stale __pycache__ snuck in (e.g. from a manual
# `python -c "import chrome_plugin.api_server"`), purge it before serve.
find chrome_plugin -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

# venv is the canonical Python — uvicorn lives there.
exec venv/bin/uvicorn chrome_plugin.api_server:app --reload --port 8000 "$@"

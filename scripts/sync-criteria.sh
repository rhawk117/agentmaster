#!/usr/bin/env sh
# Compatibility wrapper - criteria sync lives in install.py: `sync` regenerates,
# `validate` checks, and the old --check flag maps to validate.
cd "$(dirname "$0")/.." || exit 1
PY="$(command -v python3.14 || command -v python3 || command -v python)"
if [ "${1:-}" = "--check" ]; then
    exec "$PY" install.py validate --target all
fi
exec "$PY" install.py sync

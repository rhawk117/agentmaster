#!/usr/bin/env sh
# Compatibility wrapper - all installation logic lives in install.py
cd "$(dirname "$0")" || exit 1
exec "$(command -v python3.14 || command -v python3 || command -v python)" install.py install --target copilot "$@"

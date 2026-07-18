#!/usr/bin/env sh
# Compatibility wrapper - the report lives in scripts/telemetry_report.py
exec "$(command -v python3.14 || command -v python3 || command -v python)" \
    "$(dirname "$0")/telemetry_report.py" "$@"

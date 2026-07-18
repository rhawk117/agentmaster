#!/usr/bin/env bash
# Copilot sessionStart -> surface the agentmaster artifact pointer when present
set -u
IN=$(cat)
PY=$(command -v python3 || command -v python || true); [ -z "$PY" ] && exit 0
export AGENTMASTER_HOOK_INPUT="$IN"
"$PY" - <<'PYEOF'
import json, os, pathlib
d = json.loads(os.environ.get("AGENTMASTER_HOOK_INPUT") or "{}")
am = pathlib.Path(d.get("cwd") or os.getcwd()) / ".agentmaster"
if am.is_dir():
    files = sorted(p.name for p in am.iterdir() if p.is_file())
    if files:
        print("agentmaster artifacts present in .agentmaster/ ({}). Ledger of record: "
              "ledger.md (review-ledger.md for reviews) - re-hydrate from files, not "
              "compacted memory.".format(", ".join(files[:8])))
PYEOF
exit 0

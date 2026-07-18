#!/usr/bin/env bash
# SessionStart -> inject a re-hydration pointer when agentmaster artifacts exist
set -u
IN=$(cat)
export AGENTMASTER_HOOK_INPUT="$IN"
python3 - <<'PY'
import json, sys, os, pathlib
d = json.loads(os.environ.get("AGENTMASTER_HOOK_INPUT") or "{}")
am = pathlib.Path(d.get("cwd") or os.getcwd()) / ".agentmaster"
if am.is_dir():
    files = sorted(p.name for p in am.iterdir() if p.is_file())
    if files:
        print("agentmaster artifacts present in .agentmaster/ ({}). "
              "The ledger of record is ledger.md (review-ledger.md for reviews); "
              "re-hydrate evidence from these files rather than trusting compacted "
              "memory of them.".format(", ".join(files[:8])))
PY
exit 0

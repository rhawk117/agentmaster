#!/usr/bin/env bash
# SubagentStart -> record start timestamp keyed by agent_id for duration math
set -u
IN=$(cat)
export AGENTMASTER_HOOK_INPUT="$IN"
python3 - <<'PY'
import json, sys, os, time, pathlib
d = json.loads(os.environ.get("AGENTMASTER_HOOK_INPUT") or "{}")
cwd = d.get("cwd") or os.getcwd()
aid = d.get("agent_id") or ""
if os.environ.get("AGENTMASTER_HOOK_DEBUG"):
    am = pathlib.Path(cwd) / ".agentmaster"; am.mkdir(exist_ok=True)
    (am / "hook-debug.jsonl").open("a").write(json.dumps(d) + "\n")
if aid:
    p = pathlib.Path(cwd) / ".agentmaster" / ".starts"
    p.mkdir(parents=True, exist_ok=True)
    (p / aid).write_text(str(time.time()))
PY
exit 0

#!/usr/bin/env bash
# Copilot preToolUse -> queue a start timestamp when the agent tool dispatches a worker
set -u
IN=$(cat)
PY=$(command -v python3 || command -v python || true); [ -z "$PY" ] && exit 0
export AGENTMASTER_HOOK_INPUT="$IN"
"$PY" - <<'PYEOF'
import json, os, time, pathlib, re
d = json.loads(os.environ.get("AGENTMASTER_HOOK_INPUT") or "{}")
if str(d.get("toolName", d.get("tool_name", ""))).lower() != "agent":
    raise SystemExit(0)
cwd = pathlib.Path(d.get("cwd") or os.getcwd())
am = cwd / ".agentmaster"; am.mkdir(exist_ok=True)
if os.environ.get("AGENTMASTER_HOOK_DEBUG"):
    (am / "hook-debug.jsonl").open("a").write(json.dumps(d) + "\n")
args = d.get("toolArgs") or d.get("tool_args") or d.get("toolInput") or {}
agent = ""
if isinstance(args, dict):
    agent = args.get("agent") or args.get("name") or args.get("agent_name") or args.get("subagent_type") or ""
if not agent:
    m = re.search(r'"(?:agent|name|agent_name|subagent_type)"\s*:\s*"([^"]+)"', json.dumps(args))
    agent = m.group(1) if m else "agent"
q = am / ".starts"; q.mkdir(exist_ok=True)
with (q / "copilot-queue").open("a") as f:
    f.write(f"{time.time()} {agent}\n")
PYEOF
exit 0

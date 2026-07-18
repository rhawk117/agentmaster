#!/usr/bin/env bash
# Copilot postToolUse -> pop the start timestamp and append a telemetry line
set -u
IN=$(cat)
PY=$(command -v python3 || command -v python || true); [ -z "$PY" ] && exit 0
export AGENTMASTER_HOOK_INPUT="$IN"
"$PY" - <<'PYEOF'
import json, os, time, pathlib
d = json.loads(os.environ.get("AGENTMASTER_HOOK_INPUT") or "{}")
if str(d.get("toolName", d.get("tool_name", ""))).lower() != "agent":
    raise SystemExit(0)
cwd = pathlib.Path(d.get("cwd") or os.getcwd())
am = cwd / ".agentmaster"; am.mkdir(exist_ok=True)
qf = am / ".starts" / "copilot-queue"
agent, dur = "agent", ""
try:
    lines = qf.read_text().splitlines()
    if lines:
        ts, agent = lines[0].split(" ", 1)
        dur = str(int((time.time() - float(ts)) * 1000))
        qf.write_text("\n".join(lines[1:]) + ("\n" if lines[1:] else ""))
except Exception:
    pass
with (am / "telemetry.md").open("a") as f:
    f.write(f"hook,{agent},,,{dur}\n")
PYEOF
exit 0

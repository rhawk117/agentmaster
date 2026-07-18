#!/usr/bin/env bash
# SubagentStop -> append "hook,<agent>,,<tokens>,<duration_ms>" to .agentmaster/telemetry.md
set -u
IN=$(cat)
export AGENTMASTER_HOOK_INPUT="$IN"
python3 - <<'PY'
import json, sys, os, time, pathlib
d = json.loads(os.environ.get("AGENTMASTER_HOOK_INPUT") or "{}")
cwd = d.get("cwd") or os.getcwd()
am = pathlib.Path(cwd) / ".agentmaster"
am.mkdir(exist_ok=True)
if os.environ.get("AGENTMASTER_HOOK_DEBUG"):
    (am / "hook-debug.jsonl").open("a").write(json.dumps(d) + "\n")
agent = d.get("agent_type") or d.get("agent_name") or "unknown"
aid = d.get("agent_id") or ""
tokens = d.get("total_tokens") or (d.get("usage") or {}).get("total_tokens") or ""
if tokens == "":
    tp = d.get("transcript_path") or ""
    cands = []
    if aid and tp:
        base = pathlib.Path(tp).parent
        cands = [base / "subagents" / f"agent-{aid}.jsonl", base / f"agent-{aid}.jsonl"]
    for c in cands:
        try:
            tot = 0
            for line in c.read_text().splitlines():
                try:
                    u = json.loads(line).get("message", {}).get("usage", {})
                    tot += int(u.get("input_tokens", 0)) + int(u.get("output_tokens", 0))
                except Exception:
                    pass
            if tot:
                tokens = tot
                break
        except Exception:
            pass
dur = ""
if aid:
    st = am / ".starts" / aid
    try:
        dur = str(int((time.time() - float(st.read_text())) * 1000))
        st.unlink()
    except Exception:
        pass
with (am / "telemetry.md").open("a") as f:
    f.write(f"hook,{agent},,{tokens},{dur}\n")
PY
exit 0

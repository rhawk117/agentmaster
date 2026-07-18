#!/usr/bin/env bash
# Copilot preToolUse -> operator owns git: deny write git subcommands (AGENTMASTER_GIT_GUARD=off to disable)
set -u
[ "${AGENTMASTER_GIT_GUARD:-on}" = "off" ] && { cat > /dev/null; exit 0; }
IN=$(cat)
PY=$(command -v python3 || command -v python || true); [ -z "$PY" ] && exit 0
export AGENTMASTER_HOOK_INPUT="$IN"
"$PY" - <<'PYEOF'
import json, os, re, sys
d = json.loads(os.environ.get("AGENTMASTER_HOOK_INPUT") or "{}")
tool = str(d.get("toolName", d.get("tool_name", ""))).lower()
if tool not in ("execute", "bash", "shell", "run_in_terminal"):
    raise SystemExit(0)
args = d.get("toolArgs") or d.get("tool_args") or d.get("toolInput") or {}
cmd = args.get("command") if isinstance(args, dict) else str(args)
cmd = cmd or ""
SAFE = {"status", "diff", "log", "show", "blame", "rev-parse", "ls-files", "grep", "describe", "shortlog"}
for m in re.finditer(r"\bgit\s+(?:-[^\s]+\s+)*([a-z-]+)", cmd):
    if m.group(1) not in SAFE:
        reason = (f"agentmaster git-guard: 'git {m.group(1)}' is blocked - the operator owns git. "
                  "Report changes; do not commit, push, stage, or rewrite history.")
        print(json.dumps({"decision": "deny", "permissionDecision": "deny", "reason": reason}))
        sys.stderr.write(reason + "\n")
        sys.exit(2)
PYEOF
exit $?

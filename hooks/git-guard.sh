#!/usr/bin/env bash
# implementer PreToolUse (Bash) -> operator owns git: default-deny with a read-only allowlist
set -u
IN=$(cat)
export AGENTMASTER_HOOK_INPUT="$IN"
python3 - <<'PY'
import json, sys, re, os
d = json.loads(os.environ.get("AGENTMASTER_HOOK_INPUT") or "{}")
cmd = (d.get("tool_input") or {}).get("command") or ""
SAFE = {"status", "diff", "log", "show", "blame", "rev-parse", "ls-files", "grep", "describe", "shortlog"}
for m in re.finditer(r"\bgit\s+(?:-[^\s]+\s+)*([a-z-]+)", cmd):
    if m.group(1) not in SAFE:
        sys.stderr.write(
            f"agentmaster git-guard: 'git {m.group(1)}' is blocked for implementers - "
            "the operator owns git. Report your changes; do not commit, push, stage, "
            "or rewrite history.\n")
        sys.exit(2)
sys.exit(0)
PY

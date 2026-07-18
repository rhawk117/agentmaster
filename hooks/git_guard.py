"""PreToolUse (Bash/execute) -> operator owns git: default-deny writes."""

import json
import os
import sys

import hooklib

_GIT_TOOLS = frozenset({'bash', 'execute', 'shell', 'run_in_terminal'})


def main() -> int:
    payload = hooklib.read_payload()
    if os.environ.get('AGENTMASTER_GIT_GUARD') == 'off':
        return 0
    name = hooklib.tool_name(payload)
    if name and name not in _GIT_TOOLS:
        return 0
    args = hooklib.tool_args(payload)
    command = args.get('command') if isinstance(args, dict) else str(args)
    command = command or ''
    blocked = hooklib.first_blocked_git_subcommand(command)
    if blocked is None:
        return 0
    reason = (
        f"agentmaster git-guard: 'git {blocked}' is blocked - the operator owns git. "
        'Report changes; do not commit, push, stage, or rewrite history.'
    )
    if 'toolName' in payload:
        deny = {'decision': 'deny', 'permissionDecision': 'deny', 'reason': reason}
        print(json.dumps(deny))
    sys.stderr.write(reason + '\n')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())

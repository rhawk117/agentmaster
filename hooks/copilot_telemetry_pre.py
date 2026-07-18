"""Copilot preToolUse -> queue a start timestamp when the agent tool dispatches."""

import json
import re
import time

import hooklib

_AGENT_RE = re.compile(r'"(?:agent|name|agent_name|subagent_type)"\s*:\s*"([^"]+)"')


def main() -> int:
    payload = hooklib.read_payload()
    if hooklib.tool_name(payload) != 'agent':
        return 0
    am = hooklib.agentmaster_dir(payload)
    hooklib.debug_dump(payload)
    args = hooklib.tool_args(payload)
    agent = ''
    if isinstance(args, dict):
        agent = (
            args.get('agent')
            or args.get('name')
            or args.get('agent_name')
            or args.get('subagent_type')
            or ''
        )
    if not agent:
        m = _AGENT_RE.search(json.dumps(args))
        agent = m.group(1) if m else 'agent'
    queue = am / '.starts'
    queue.mkdir(exist_ok=True)
    with (queue / 'copilot-queue').open('a') as f:
        f.write(f'{time.time()} {agent}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

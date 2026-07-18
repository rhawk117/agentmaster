"""SubagentStart -> record a start timestamp keyed by agent_id for duration math."""

import time

import hooklib


def main() -> int:
    payload = hooklib.read_payload()
    hooklib.debug_dump(payload)
    aid = payload.get('agent_id') or ''
    if aid:
        starts = hooklib.agentmaster_dir(payload) / '.starts'
        starts.mkdir(parents=True, exist_ok=True)
        (starts / aid).write_text(str(time.time()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

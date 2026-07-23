import contextlib
import time

import hooklib


def _to_int(value: str | int) -> int | None:
    try:
        parsed = int(value)
    except TypeError, ValueError:
        return None
    return parsed if parsed >= 0 else None


def main() -> int:
    payload = hooklib.read_payload()
    if hooklib.tool_name(payload) != 'agent':
        return 0
    am = hooklib.agentmaster_dir(payload)
    qf = am / '.starts' / 'copilot-queue'
    agent, duration = 'agent', ''
    with contextlib.suppress(Exception):
        lines = qf.read_text().splitlines()
        if lines:
            ts, agent = lines[0].split(' ', 1)
            duration = str(int((time.time() - float(ts)) * 1000))
            rest = lines[1:]
            qf.write_text('\n'.join(rest) + ('\n' if rest else ''))
    hooklib.append_telemetry(payload, agent, '', duration)
    hooklib.spool_event(
        payload,
        {
            'kind': 'agent_session',
            'cwd': str(hooklib.workspace(payload)),
            'agent_id': '',
            'role': agent,
            'model': '',
            'total_tokens': None,
            'duration_ms': _to_int(duration),
        },
    )
    hooklib.auto_drain(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

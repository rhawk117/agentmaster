"""SubagentStop -> append a telemetry row for the finished subagent."""

import contextlib
import json
import time
from pathlib import Path

import hooklib


def _transcript_stats(transcript_path: str, aid: str) -> tuple[str | int, str]:
    """Sum input/output tokens and find the model from the subagent transcript."""
    if not (aid and transcript_path):
        return '', ''
    base = Path(transcript_path)
    cands = [
        base.with_suffix('') / 'subagents' / f'agent-{aid}.jsonl',
        base.parent / 'subagents' / f'agent-{aid}.jsonl',
        base.parent / f'agent-{aid}.jsonl',
    ]
    for c in cands:
        with contextlib.suppress(Exception):
            tot = 0
            model = ''
            for line in c.read_text().splitlines():
                with contextlib.suppress(Exception):
                    message = json.loads(line).get('message', {})
                    usage = message.get('usage', {})
                    tot += int(usage.get('input_tokens', 0)) + int(
                        usage.get('output_tokens', 0)
                    )
                    model = model or str(message.get('model') or '')
            if tot or model:
                return tot or '', model
    return '', ''


def _consume_start(sdir: Path, legacy_dir: Path, aid: str) -> str:
    """Return the elapsed duration in ms and delete the recorded start.

    Checks the session-scoped .starts/ first, falling back to the legacy
    root .agentmaster/.starts/ for timestamps recorded before session
    scoping.
    """
    for base in (sdir, legacy_dir):
        st = base / '.starts' / aid
        try:
            duration = str(int((time.time() - float(st.read_text())) * 1000))
        except OSError, ValueError:
            continue
        with contextlib.suppress(Exception):
            st.unlink()
        return duration
    return ''


def _to_int(value: str | int) -> int | None:
    """Return `value` as a non-negative int, or `None` when absent/unparseable.

    Never fabricates a token/duration value (SPEC.md §16.3): an empty
    string or a value that isn't a real non-negative integer becomes NULL
    rather than 0 or a guess.
    """
    try:
        parsed = int(value)
    except TypeError, ValueError:
        return None
    return parsed if parsed >= 0 else None


def main() -> int:
    payload = hooklib.read_payload()
    sdir = hooklib.session_dir(payload)
    hooklib.debug_dump(payload)
    agent = payload.get('agent_type') or payload.get('agent_name') or 'unknown'
    aid = payload.get('agent_id') or ''
    tokens = (
        payload.get('total_tokens')
        or (payload.get('usage') or {}).get('total_tokens')
        or ''
    )
    model = str(payload.get('model') or payload.get('agent_model') or '')
    if tokens == '' or not model:
        t_tokens, t_model = _transcript_stats(payload.get('transcript_path') or '', aid)
        if tokens == '':
            tokens = t_tokens
        model = model or t_model
    duration_ms = (
        _consume_start(sdir, hooklib.agentmaster_dir(payload), aid) if aid else ''
    )
    hooklib.append_telemetry(payload, agent, tokens, duration_ms, model)
    hooklib.spool_event(
        payload,
        {
            'kind': 'agent_session',
            'cwd': str(hooklib.workspace(payload)),
            'agent_id': aid,
            'role': agent,
            'model': model,
            'total_tokens': _to_int(tokens),
            'duration_ms': _to_int(duration_ms),
        },
    )
    hooklib.auto_drain(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

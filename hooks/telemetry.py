"""SubagentStop -> append a telemetry row for the finished subagent."""

import contextlib
import json
import time
from pathlib import Path

import hooklib


def _tokens_from_transcript(transcript_path: str, aid: str) -> str | int:
    """Sum input/output tokens from the subagent transcript as a fallback."""
    if not (aid and transcript_path):
        return ''
    base = Path(transcript_path).parent
    cands = [base / 'subagents' / f'agent-{aid}.jsonl', base / f'agent-{aid}.jsonl']
    for c in cands:
        with contextlib.suppress(Exception):
            tot = 0
            for line in c.read_text().splitlines():
                with contextlib.suppress(Exception):
                    usage = json.loads(line).get('message', {}).get('usage', {})
                    tot += int(usage.get('input_tokens', 0)) + int(
                        usage.get('output_tokens', 0)
                    )
            if tot:
                return tot
    return ''


def _consume_start(am: Path, aid: str) -> str:
    """Return the elapsed duration in ms and delete the recorded start."""
    st = am / '.starts' / aid
    try:
        duration = str(int((time.time() - float(st.read_text())) * 1000))
    except Exception:
        return ''
    with contextlib.suppress(Exception):
        st.unlink()
    return duration


def main() -> int:
    payload = hooklib.read_payload()
    am = hooklib.agentmaster_dir(payload)
    hooklib.debug_dump(payload)
    agent = payload.get('agent_type') or payload.get('agent_name') or 'unknown'
    aid = payload.get('agent_id') or ''
    tokens = (
        payload.get('total_tokens')
        or (payload.get('usage') or {}).get('total_tokens')
        or ''
    )
    if tokens == '':
        tokens = _tokens_from_transcript(payload.get('transcript_path') or '', aid)
    duration_ms = _consume_start(am, aid) if aid else ''
    hooklib.append_telemetry(payload, agent, tokens, duration_ms)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

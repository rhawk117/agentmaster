import contextlib
import json
import sqlite3
import sys
from typing import TYPE_CHECKING

import hooklib

if TYPE_CHECKING:
    from pathlib import Path

BLOCKING_STATES = frozenset({
    'ReviewRequired',
    'Reviewing',
    'FixesRequired',
    'MergePending',
    'RetrospectivePending',
})
MAX_STOP_RETRIES = 3


def _ledger_path() -> Path | None:
    with contextlib.suppress(Exception):
        descriptor = hooklib.load_runtime_descriptor()
        if descriptor is None or not descriptor.ledger_enabled:
            return None
        return descriptor.ledger_path
    return None


def _run_id(payload: dict) -> str | None:
    marker = hooklib.session_dir(payload) / '.run_id'
    try:
        text = marker.read_text(encoding='utf-8').strip()
    except OSError:
        return None
    return text or None


def _run_state(ledger_path: Path, run_id: str) -> str | None:
    try:
        uri = f'file:{ledger_path.as_posix()}?mode=ro'
        connection = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        row = connection.execute(
            'SELECT state FROM RUN WHERE id = ?', (run_id,)
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return row[0] if row else None


def _retry_marker(payload: dict) -> Path:
    return hooklib.session_dir(payload) / '.stop_hook_retries'


def _retry_count(payload: dict) -> int:
    with contextlib.suppress(Exception):
        return int(_retry_marker(payload).read_text(encoding='utf-8').strip() or '0')
    return 0


def _record_retries_exhausted(payload: dict, *, run_id: str, state: str) -> None:
    with contextlib.suppress(Exception):
        am = hooklib.agentmaster_dir(payload)
        with (am / 'hook-debug.jsonl').open('a') as f:
            f.write(
                json.dumps({
                    'stop_hook_retries_exhausted': True,
                    'run_id': run_id,
                    'state': state,
                    'max_retries': MAX_STOP_RETRIES,
                })
                + '\n'
            )


def main() -> int:
    payload = hooklib.read_payload()
    ledger_path = _ledger_path()
    if ledger_path is None or not ledger_path.is_file():
        return 0
    run_id = _run_id(payload)
    if run_id is None:
        return 0
    state = _run_state(ledger_path, run_id)
    if state is None or state not in BLOCKING_STATES:
        _retry_marker(payload).unlink(missing_ok=True)
        return 0

    retries = _retry_count(payload) + 1
    if retries > MAX_STOP_RETRIES:
        _record_retries_exhausted(payload, run_id=run_id, state=state)
        sys.stderr.write(
            f'agentmaster execute stop hook: run {run_id} is still {state} after '
            f'{MAX_STOP_RETRIES} retries; not blocking again. The review/merge gate '
            'remains incomplete -- surface this to the user.\n'
        )
        return 0
    _retry_marker(payload).write_text(str(retries), encoding='utf-8')
    sys.stderr.write(
        f'agentmaster execute stop hook: run {run_id} is {state}, not complete. '
        'execute must not end while the review/merge gate is pending -- resume the '
        'delivery pipeline until it reaches Merged/RetrospectivePending/Complete.\n'
    )
    return 2


if __name__ == '__main__':
    raise SystemExit(main())

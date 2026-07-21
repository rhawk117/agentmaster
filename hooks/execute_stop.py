"""Stop -> block execute from ending while the review/merge gate is incomplete.

SPEC.md §20.3: "A stop hook blocks successful execution termination while the
state is REVIEW_REQUIRED, REVIEWING, FIXES_REQUIRED, MERGE_PENDING, or
RETROSPECTIVE_PENDING for the selected delivery mode... [and] must not
recursively relaunch after a configured retry ceiling." Hook processes run
standalone, copied without the `ledger` package (see hooks/hooklib.py's
`spool_event`), so this reads the ledger sqlite file directly with the
stdlib `sqlite3`/`tomllib` modules rather than importing `ledger.*`; on any
missing marker, missing ledger, or read error it fails open (exits 0) rather
than ever blocking a stop it cannot actually verify.

`BLOCKING_STATES` duplicates `ledger.orchestrator_state.
BLOCKING_COMPLETION_STATES` (the source of truth) for the same reason.
"""

import contextlib
import sqlite3
import sys
import tomllib
from pathlib import Path

import hooklib

BLOCKING_STATES = frozenset({
    'ReviewRequired',
    'Reviewing',
    'FixesRequired',
    'MergePending',
    'RetrospectivePending',
})
MAX_STOP_RETRIES = 3


def _ledger_path(payload: dict) -> Path | None:
    config_path = hooklib.workspace(payload) / '.agentmaster' / 'config.toml'
    # Broad by design (hooklib.py's own read_payload/spool_event convention):
    # any parse failure means "can't verify", which fails open, not closed.
    with contextlib.suppress(Exception):
        document = tomllib.loads(config_path.read_text(encoding='utf-8'))
        return Path(document['paths']['ledger'])
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


def main() -> int:
    payload = hooklib.read_payload()
    ledger_path = _ledger_path(payload)
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
        # Idempotent, non-recursive: stop retrying after the ceiling and let
        # the session end, surfacing the gate as still open rather than
        # relaunching indefinitely.
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

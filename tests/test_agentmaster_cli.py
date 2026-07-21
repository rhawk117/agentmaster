"""Tests for the unified `agentmaster` CLI's ledger/memory wiring (SPEC.md §19)."""

import json

import pytest

from agentmaster.cli import main
from ledger.connection import connect

_CREATED_AT = '2026-07-20T00:00:00Z'


def _seed_run_and_task(ledger_path):
    connection = connect(ledger_path)
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        "VALUES ('project-1', '/repo', 'fp-1', ?, ?)",
        (_CREATED_AT, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        "VALUES ('user-session-1', 'harness-1', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO RUN '
        '(id, project_id, user_session_id, delivery_mode, state, started_at) '
        "VALUES ('run-1', 'project-1', 'user-session-1', 'local', 'Planned', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO TASK (id, run_id, title, state, sequence_no) '
        "VALUES ('task-1', 'run-1', 'retry backoff', 'ready', 1)"
    )
    connection.commit()
    connection.close()


@pytest.fixture
def ledger_path(tmp_path):
    path = tmp_path / 'ledger.sqlite3'
    assert main(['ledger', 'init', '--path', str(path)]) == 0
    return path


@pytest.mark.sqlite
def test_ledger_record_feedback_then_query_round_trip(capsys, ledger_path):
    _seed_run_and_task(ledger_path)

    exit_code = main([
        'ledger',
        'record-feedback',
        '--path',
        str(ledger_path),
        '--user-session-id',
        'user-session-1',
        '--run-id',
        'run-1',
        '--rating',
        '1',
    ])

    assert exit_code == 0
    feedback_id = capsys.readouterr().out.strip()
    connection = connect(ledger_path)
    row = connection.execute(
        'SELECT rating FROM FEEDBACK WHERE id = ?', (feedback_id,)
    ).fetchone()
    connection.close()
    assert row == (1,)


@pytest.mark.sqlite
def test_ledger_record_feedback_rejects_an_unknown_run(capsys, ledger_path):
    exit_code = main([
        'ledger',
        'record-feedback',
        '--path',
        str(ledger_path),
        '--user-session-id',
        'user-session-1',
        '--run-id',
        'no-such-run',
        '--rating',
        '0',
    ])

    assert exit_code == 1
    assert 'does not exist' in capsys.readouterr().err


@pytest.mark.sqlite
def test_ledger_query_entrypoints_on_a_fresh_ledger_reports_empty(capsys, ledger_path):
    exit_code = main([
        'ledger',
        'query',
        'entrypoints',
        '--path',
        str(ledger_path),
        '--json',
    ])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


@pytest.mark.sqlite
def test_memory_lifecycle_via_cli(capsys, ledger_path):
    connection = connect(ledger_path)
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        "VALUES ('project-1', '/repo', 'fp-1', ?, ?)",
        (_CREATED_AT, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, created_at, '
        'updated_at) '
        "VALUES ('memory-1', 'project-1', 'Candidate', 'lesson', 'title', 'content', "
        '?, ?)',
        (_CREATED_AT, _CREATED_AT),
    )
    connection.commit()
    connection.close()

    exit_code = main([
        'memory',
        'reject',
        '--path',
        str(ledger_path),
        '--memory-id',
        'memory-1',
    ])
    assert exit_code == 0

    exit_code = main([
        'memory',
        'show',
        '--path',
        str(ledger_path),
        '--memory-id',
        'memory-1',
        '--json',
    ])
    assert exit_code == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail['state'] == 'Rejected'


@pytest.mark.sqlite
def test_memory_show_on_an_unknown_id_fails(capsys, ledger_path):
    exit_code = main([
        'memory',
        'show',
        '--path',
        str(ledger_path),
        '--memory-id',
        'no-such-memory',
    ])

    assert exit_code == 1
    assert 'not found' in capsys.readouterr().err

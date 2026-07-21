"""Tests for the PROCEDURE/PROCEDURE_VERSION/PROCEDURE_USE schema (SPEC.md §17.2, §20.4).

`_seed_project`/`_seed_procedure` mirror tests/test_retrospective_ledger.py.
"""

import sqlite3

import pytest

from ledger.connection import connect
from ledger.migrations import migrate

_CREATED_AT = '2026-07-20T00:00:00Z'


def _seed_project(
    connection: sqlite3.Connection, *, project_id: str = 'project-1'
) -> None:
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        'VALUES (?, ?, ?, ?, ?)',
        (project_id, '/repo', f'fp-{project_id}', _CREATED_AT, _CREATED_AT),
    )
    connection.commit()


def _seed_procedure(
    connection: sqlite3.Connection, *, procedure_id: str = 'procedure-1'
) -> None:
    if (
        connection.execute("SELECT 1 FROM PROJECT WHERE id = 'project-1'").fetchone()
        is None
    ):
        _seed_project(connection)
    connection.execute(
        'INSERT INTO PROCEDURE (id, project_id, name, scope, state, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (procedure_id, 'project-1', 'name', 'skill', 'active', _CREATED_AT),
    )
    connection.commit()


def _seed_procedure_version(
    connection: sqlite3.Connection,
    *,
    version_id: str = 'pv-1',
    procedure_id: str = 'procedure-1',
    version_no: int = 1,
    status: str = 'inactive',
) -> None:
    if (
        connection.execute(
            'SELECT 1 FROM PROCEDURE WHERE id = ?', (procedure_id,)
        ).fetchone()
        is None
    ):
        _seed_procedure(connection, procedure_id=procedure_id)
    connection.execute(
        'INSERT INTO PROCEDURE_VERSION '
        '(id, procedure_id, version_no, content_hash, status, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (version_id, procedure_id, version_no, f'hash-{version_no}', status, _CREATED_AT),
    )
    connection.commit()


def _seed_run_task_and_agent_session(connection: sqlite3.Connection) -> None:
    if (
        connection.execute("SELECT 1 FROM PROJECT WHERE id = 'project-1'").fetchone()
        is None
    ):
        _seed_project(connection)
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        'VALUES (?, ?, ?)',
        ('user-session-1', 'harness-1', _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO RUN '
        '(id, project_id, user_session_id, delivery_mode, state, started_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        ('run-1', 'project-1', 'user-session-1', 'local', 'Planned', _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO TASK (id, run_id, title, state, sequence_no) VALUES (?, ?, ?, ?, ?)',
        ('task-1', 'run-1', 'do the thing', 'ready', 1),
    )
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, task_id, role, provider, model, state, started_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (
            'agent-session-1',
            'run-1',
            'task-1',
            'implementer',
            'claude',
            'sonnet',
            'running',
            _CREATED_AT,
        ),
    )
    connection.commit()


@pytest.mark.sqlite
def test_procedure_version_accepts_both_closed_set_statuses(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_procedure(connection)

    _seed_procedure_version(
        connection, version_id='pv-1', version_no=1, status='inactive'
    )
    _seed_procedure_version(connection, version_id='pv-2', version_no=2, status='active')

    rows = connection.execute(
        'SELECT status FROM PROCEDURE_VERSION ORDER BY version_no'
    ).fetchall()
    assert rows == [('inactive',), ('active',)]
    connection.close()


@pytest.mark.sqlite
def test_procedure_version_number_must_be_at_least_one(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_procedure(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO PROCEDURE_VERSION '
            '(id, procedure_id, version_no, content_hash, status, created_at) '
            "VALUES ('pv-1', 'procedure-1', 0, 'hash-0', 'inactive', ?)",
            (_CREATED_AT,),
        )
    connection.close()


@pytest.mark.sqlite
def test_different_procedures_may_each_start_at_version_one(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_procedure(connection, procedure_id='procedure-1')
    _seed_procedure(connection, procedure_id='procedure-2')

    _seed_procedure_version(
        connection, version_id='pv-1', procedure_id='procedure-1', version_no=1
    )
    _seed_procedure_version(
        connection, version_id='pv-2', procedure_id='procedure-2', version_no=1
    )

    rows = connection.execute('SELECT COUNT(*) FROM PROCEDURE_VERSION').fetchone()
    assert rows == (2,)
    connection.close()


@pytest.mark.sqlite
def test_procedure_use_records_the_task_and_agent_session_that_applied_a_version(
    tmp_path,
):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_procedure_version(connection)
    _seed_run_task_and_agent_session(connection)

    connection.execute(
        'INSERT INTO PROCEDURE_USE '
        '(id, procedure_version_id, task_id, agent_session_id, outcome, created_at) '
        "VALUES ('use-1', 'pv-1', 'task-1', 'agent-session-1', 'success', ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    row = connection.execute(
        'SELECT procedure_version_id, task_id, agent_session_id, outcome '
        "FROM PROCEDURE_USE WHERE id = 'use-1'"
    ).fetchone()
    assert row == ('pv-1', 'task-1', 'agent-session-1', 'success')
    connection.close()


@pytest.mark.sqlite
def test_procedure_use_rejects_a_nonexistent_procedure_version(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO PROCEDURE_USE (id, procedure_version_id, created_at) '
            "VALUES ('use-1', 'no-such-version', ?)",
            (_CREATED_AT,),
        )
    connection.close()

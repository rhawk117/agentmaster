"""Tests for memory lifecycle/scope/link constraints and FEEDBACK (SPEC.md §17.3, §17.4).

FEEDBACK.user_session_id, per the amended §17, is a FK to USER_SESSION and must
not accept an AGENT_SESSION id even though both are Agentmaster-generated text
identifiers.
"""

import sqlite3

import pytest

from ledger.connection import connect
from ledger.migrations import MIGRATIONS, SUPPORTED_SCHEMA_VERSION, migrate

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


def _seed_memory(
    connection: sqlite3.Connection,
    *,
    memory_id: str = 'memory-1',
    state: str = 'Candidate',
) -> None:
    if (
        connection.execute("SELECT 1 FROM PROJECT WHERE id = 'project-1'").fetchone()
        is None
    ):
        _seed_project(connection)
    connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, '
        'created_at, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (
            memory_id,
            'project-1',
            state,
            'lesson',
            'title',
            'content',
            _CREATED_AT,
            _CREATED_AT,
        ),
    )
    connection.commit()


def _seed_feedback_targets(connection: sqlite3.Connection) -> None:
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
    connection.commit()


@pytest.mark.sqlite
def test_memory_state_check_rejects_an_unrecognized_state(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_project(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO MEMORY '
            '(id, origin_project_id, state, memory_kind, title, content, '
            'created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                'memory-1',
                'project-1',
                'Bogus',
                'lesson',
                'title',
                'content',
                _CREATED_AT,
                _CREATED_AT,
            ),
        )
    connection.close()


@pytest.mark.sqlite
def test_memory_state_check_accepts_every_lifecycle_state(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_project(connection)
    states = ('Candidate', 'Validated', 'Active', 'Superseded', 'Archived', 'Rejected')

    for index, state in enumerate(states):
        _seed_memory(connection, memory_id=f'memory-{index}', state=state)

    rows = connection.execute('SELECT COUNT(*) FROM MEMORY').fetchone()
    assert rows == (len(states),)
    connection.close()


@pytest.mark.sqlite
def test_memory_scope_rejects_a_global_row_that_names_a_project(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_memory(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO MEMORY_SCOPE (memory_id, scope_kind, project_id, created_at) '
            'VALUES (?, ?, ?, ?)',
            ('memory-1', 'global', 'project-1', _CREATED_AT),
        )
    connection.close()


@pytest.mark.sqlite
def test_memory_scope_rejects_a_project_scoped_row_without_a_project(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_memory(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO MEMORY_SCOPE (memory_id, scope_kind, project_id, created_at) '
            'VALUES (?, ?, ?, ?)',
            ('memory-1', 'project', None, _CREATED_AT),
        )
    connection.close()


@pytest.mark.sqlite
def test_memory_link_rejects_an_unrecognized_link_kind(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_memory(connection, memory_id='memory-1')
    _seed_memory(connection, memory_id='memory-2')

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO MEMORY_LINK '
            '(source_memory_id, target_memory_id, link_kind, created_at) '
            'VALUES (?, ?, ?, ?)',
            ('memory-1', 'memory-2', 'bogus', _CREATED_AT),
        )
    connection.close()


@pytest.mark.sqlite
def test_feedback_rating_check_rejects_a_value_above_the_tri_state_range(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_feedback_targets(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO FEEDBACK (id, user_session_id, run_id, rating, created_at) '
            'VALUES (?, ?, ?, ?, ?)',
            ('feedback-1', 'user-session-1', 'run-1', 2, _CREATED_AT),
        )
    connection.close()


@pytest.mark.sqlite
def test_feedback_rating_check_rejects_a_value_below_the_tri_state_range(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_feedback_targets(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO FEEDBACK (id, user_session_id, run_id, rating, created_at) '
            'VALUES (?, ?, ?, ?, ?)',
            ('feedback-1', 'user-session-1', 'run-1', -2, _CREATED_AT),
        )
    connection.close()


@pytest.mark.sqlite
def test_feedback_user_session_id_rejects_an_agent_session_id(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_feedback_targets(connection)
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (
            'agent-session-1',
            'run-1',
            'implementer',
            'claude',
            'sonnet',
            'running',
            _CREATED_AT,
        ),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO FEEDBACK (id, user_session_id, run_id, rating, created_at) '
            'VALUES (?, ?, ?, ?, ?)',
            ('feedback-1', 'agent-session-1', 'run-1', 1, _CREATED_AT),
        )
    connection.close()


@pytest.mark.sqlite
def test_migrate_from_schema_version_3_backs_up_before_reaching_the_current_version(
    tmp_path, monkeypatch
):
    ledger_path = tmp_path / 'ledger.sqlite3'
    pre_memory = tuple(migration for migration in MIGRATIONS if migration.to_version <= 3)
    monkeypatch.setattr('ledger.migrations.MIGRATIONS', pre_memory)
    monkeypatch.setattr('ledger.migrations.SUPPORTED_SCHEMA_VERSION', 3)
    seed_connection = connect(ledger_path)
    migrate(seed_connection)
    seed_connection.close()
    monkeypatch.undo()

    backup_path = tmp_path / 'backups' / 'pre-memory.sqlite3'
    connection = connect(ledger_path)
    final_version = migrate(connection, backup_path=backup_path)

    assert final_version == SUPPORTED_SCHEMA_VERSION
    assert backup_path.exists()
    connection.close()

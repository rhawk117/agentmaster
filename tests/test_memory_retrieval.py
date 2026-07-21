"""Tests for the FTS5 memory index and access logging (SPEC.md §23 MT14 c2, §17.5)."""

import pytest

from ledger.connection import connect
from ledger.migrations import SUPPORTED_SCHEMA_VERSION, migrate

_CREATED_AT = '2026-07-20T00:00:00Z'


def _seed_project(connection, *, project_id='project-1'):
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        'VALUES (?, ?, ?, ?, ?)',
        (project_id, '/repo', f'fp-{project_id}', _CREATED_AT, _CREATED_AT),
    )
    connection.commit()


def _insert_memory(connection, memory_id, *, state, title='title', content='content'):
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
            title,
            content,
            _CREATED_AT,
            _CREATED_AT,
        ),
    )
    connection.commit()


def _seed_run_and_task(connection):
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
def test_fresh_init_reaches_the_memory_retrieval_schema_version(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')

    final_version = migrate(connection)

    assert final_version == SUPPORTED_SCHEMA_VERSION == 6
    connection.close()


@pytest.mark.sqlite
def test_an_active_memory_matches_in_the_fts_index(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _insert_memory(
        connection,
        'memory-1',
        state='Active',
        title='Retry backoff',
        content='Use jittered backoff for BUSY retries',
    )

    rows = connection.execute(
        "SELECT rowid FROM memory_fts WHERE memory_fts MATCH 'backoff'"
    ).fetchall()

    assert len(rows) == 1
    connection.close()


@pytest.mark.sqlite
def test_a_candidate_memory_does_not_match_in_the_fts_index(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _insert_memory(
        connection,
        'memory-1',
        state='Candidate',
        title='Retry backoff',
        content='Use jittered backoff for BUSY retries',
    )

    rows = connection.execute(
        "SELECT rowid FROM memory_fts WHERE memory_fts MATCH 'backoff'"
    ).fetchall()

    assert rows == []
    connection.close()


@pytest.mark.sqlite
def test_updating_memory_content_resyncs_the_fts_index(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _insert_memory(connection, 'memory-1', state='Active', content='alpha content')

    connection.execute("UPDATE MEMORY SET content = 'beta content' WHERE id = 'memory-1'")
    connection.commit()

    alpha_rows = connection.execute(
        "SELECT rowid FROM memory_fts WHERE memory_fts MATCH 'alpha'"
    ).fetchall()
    beta_rows = connection.execute(
        "SELECT rowid FROM memory_fts WHERE memory_fts MATCH 'beta'"
    ).fetchall()
    assert alpha_rows == []
    assert len(beta_rows) == 1
    connection.close()


@pytest.mark.sqlite
def test_activating_a_candidate_memory_adds_it_to_the_fts_index(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _insert_memory(connection, 'memory-1', state='Candidate', content='alpha content')

    connection.execute("UPDATE MEMORY SET state = 'Active' WHERE id = 'memory-1'")
    connection.commit()

    rows = connection.execute(
        "SELECT rowid FROM memory_fts WHERE memory_fts MATCH 'alpha'"
    ).fetchall()
    assert len(rows) == 1
    connection.close()


@pytest.mark.sqlite
def test_archiving_an_active_memory_removes_it_from_the_fts_index(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _insert_memory(connection, 'memory-1', state='Active', content='alpha content')

    connection.execute("UPDATE MEMORY SET state = 'Archived' WHERE id = 'memory-1'")
    connection.commit()

    rows = connection.execute(
        "SELECT rowid FROM memory_fts WHERE memory_fts MATCH 'alpha'"
    ).fetchall()
    assert rows == []
    connection.close()


@pytest.mark.sqlite
def test_deleting_a_memory_removes_it_from_the_fts_index(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _insert_memory(connection, 'memory-1', state='Active', content='alpha content')

    connection.execute("DELETE FROM MEMORY WHERE id = 'memory-1'")
    connection.commit()

    rows = connection.execute(
        "SELECT rowid FROM memory_fts WHERE memory_fts MATCH 'alpha'"
    ).fetchall()
    assert rows == []
    connection.close()


@pytest.mark.sqlite
def test_memory_access_logs_rank_score_and_outcome_columns(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run_and_task(connection)
    _insert_memory(connection, 'memory-1', state='Active')

    connection.execute(
        'INSERT INTO memory_access '
        '(id, run_id, task_id, agent_session_id, memory_id, query_digest, rank, '
        'score, selected, estimated_tokens, used, helpful, harmful, '
        'retrieval_algorithm_version, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            'access-1',
            'run-1',
            'task-1',
            'agent-session-1',
            'memory-1',
            'digest-1',
            0,
            0.87,
            1,
            120,
            1,
            1,
            0,
            'v1',
            _CREATED_AT,
        ),
    )
    connection.commit()

    row = connection.execute(
        'SELECT rank, score, selected, estimated_tokens, used, helpful, harmful, '
        'retrieval_algorithm_version FROM memory_access WHERE id = ?',
        ('access-1',),
    ).fetchone()

    assert row == (0, 0.87, 1, 120, 1, 1, 0, 'v1')
    connection.close()

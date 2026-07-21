"""Tests for the execution/token-accounting schema (SPEC.md §23 Microtask 12, §17.1)."""

import sqlite3

import pytest

from ledger.connection import connect
from ledger.migrations import migrate
from ledger.schema import MIGRATIONS, SUPPORTED_SCHEMA_VERSION

_EXECUTION_TABLES = (
    'USER_SESSION',
    'ENTRYPOINT',
    'PROJECT',
    'RUN',
    'TASK',
    'TASK_DEPENDENCY',
    'AGENT_SESSION',
    'MODEL_CALL',
    'TOOL_CALL',
    'COMPACTION_EVENT',
)

_EXECUTION_INDEXES = (
    'idx_user_session_harness_session_id',
    'idx_entrypoint_kind_active',
    'idx_run_project_id',
    'idx_run_user_session_id',
    'idx_run_parent_run_id',
    'idx_run_state',
    'idx_run_started_at',
    'idx_task_run_id',
    'idx_task_parent_task_id',
    'idx_task_state',
    'idx_task_started_at',
    'idx_task_dependency_task_id',
    'idx_task_dependency_depends_on_task_id',
    'idx_agent_session_run_id',
    'idx_agent_session_task_id',
    'idx_agent_session_parent_session_id',
    'idx_agent_session_entrypoint_id',
    'idx_model_call_agent_session_id',
    'idx_tool_call_agent_session_id',
    'idx_tool_call_task_id',
    'idx_tool_call_entrypoint_id',
    'idx_compaction_event_agent_session_id',
    'idx_compaction_event_snapshot_artifact_id',
)


@pytest.mark.sqlite
def test_fresh_init_reaches_the_execution_schema_version(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')

    final_version = migrate(connection)

    assert final_version == SUPPORTED_SCHEMA_VERSION == 2
    connection.close()


@pytest.mark.sqlite
def test_fresh_init_creates_every_execution_table(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    table_names = {row[0] for row in rows}

    for table in _EXECUTION_TABLES:
        assert table in table_names
    connection.close()


@pytest.mark.sqlite
def test_fresh_init_creates_every_execution_index(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    ).fetchall()
    index_names = {row[0] for row in rows}

    for index in _EXECUTION_INDEXES:
        assert index in index_names
    connection.close()


@pytest.mark.sqlite
def test_agent_session_insert_fails_for_a_nonexistent_run(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO AGENT_SESSION '
            '(id, run_id, role, provider, model, state, started_at) '
            "VALUES ('session-1', 'no-such-run', 'implementer', 'claude', "
            "'sonnet', 'running', '2026-07-20T00:00:00Z')"
        )
    connection.close()


@pytest.mark.sqlite
def test_run_insert_fails_for_an_unknown_state(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_project_and_session(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO RUN '
            '(id, project_id, user_session_id, delivery_mode, state, started_at) '
            "VALUES ('run-1', 'project-1', 'user-session-1', 'local', "
            "'not-a-real-state', '2026-07-20T00:00:00Z')"
        )
    connection.close()


@pytest.mark.sqlite
def test_a_v1_database_migrates_forward_with_a_pre_migration_backup(
    tmp_path, monkeypatch
):
    ledger_path = tmp_path / 'ledger.sqlite3'
    backup_path = tmp_path / 'backup.sqlite3'
    v1_only = tuple(migration for migration in MIGRATIONS if migration.to_version == 1)
    monkeypatch.setattr('ledger.migrations.MIGRATIONS', v1_only)
    monkeypatch.setattr('ledger.migrations.SUPPORTED_SCHEMA_VERSION', 1)
    seed_connection = connect(ledger_path)
    migrate(seed_connection)
    assert not backup_path.exists()
    seed_connection.close()
    monkeypatch.undo()

    connection = connect(ledger_path)
    final_version = migrate(connection, backup_path=backup_path)

    assert final_version == SUPPORTED_SCHEMA_VERSION == 2
    assert backup_path.exists()
    backup_connection = sqlite3.connect(backup_path)
    try:
        backup_version = backup_connection.execute('PRAGMA user_version').fetchone()[0]
    finally:
        backup_connection.close()
    assert backup_version == 1
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    for table in _EXECUTION_TABLES:
        assert table in tables
    connection.close()


def _seed_project_and_session(connection: sqlite3.Connection) -> None:
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        "VALUES ('project-1', '/repo', 'fp-1', "
        "'2026-07-20T00:00:00Z', '2026-07-20T00:00:00Z')"
    )
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        "VALUES ('user-session-1', 'harness-1', '2026-07-20T00:00:00Z')"
    )
    connection.commit()

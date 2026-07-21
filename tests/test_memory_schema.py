"""Tests for the memory/feedback schema (SPEC.md §23 Microtask 14 commit 1, §17.2)."""

import pytest

from ledger.connection import connect
from ledger.migrations import SUPPORTED_SCHEMA_VERSION, migrate

_MEMORY_TABLES = (
    'MEMORY',
    'MEMORY_SCOPE',
    'MEMORY_TARGET',
    'MEMORY_LINK',
    'MEMORY_EVIDENCE',
    'FEEDBACK',
)
_MEMORY_INDEXES = (
    'idx_memory_origin_project_id',
    'idx_memory_supersedes_memory_id',
    'idx_memory_scope_memory_id',
    'idx_memory_scope_project_id',
    'idx_memory_target_memory_id',
    'idx_memory_link_source_memory_id',
    'idx_memory_link_target_memory_id',
    'idx_memory_evidence_memory_id',
    'idx_memory_evidence_evidence_id',
    'idx_memory_evidence_observation_id',
    'idx_feedback_user_session_id',
    'idx_feedback_run_id',
    'idx_feedback_task_id',
    'idx_feedback_memory_id',
)


@pytest.mark.sqlite
def test_fresh_init_reaches_the_memory_schema_version(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')

    final_version = migrate(connection)

    assert final_version == SUPPORTED_SCHEMA_VERSION == 6
    connection.close()


@pytest.mark.sqlite
def test_fresh_init_creates_every_memory_table(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    for table in _MEMORY_TABLES:
        assert table in tables
    connection.close()


@pytest.mark.sqlite
def test_fresh_init_creates_every_memory_index(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }

    for index in _MEMORY_INDEXES:
        assert index in indexes
    connection.close()

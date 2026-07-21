"""Tests for `ledger.queries.query_entrypoints` (SPEC.md §17.1, §19, §23 Microtask 16)."""

import pytest

from ledger.connection import connect
from ledger.migrations import migrate
from ledger.queries import query_entrypoints

_CREATED_AT = '2026-07-20T00:00:00Z'


@pytest.mark.sqlite
def test_query_entrypoints_on_a_fresh_ledger_is_empty(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    assert query_entrypoints(connection) == []
    connection.close()


@pytest.mark.sqlite
def test_query_entrypoints_lists_rows_ordered_by_kind_then_name(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    connection.execute(
        'INSERT INTO ENTRYPOINT (id, kind, name, source_path, active, created_at) '
        "VALUES ('ep-1', 'skill', 'writing-skills', 'skills/writing-skills', 1, ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO ENTRYPOINT (id, kind, name, source_path, active, created_at) '
        "VALUES ('ep-2', 'command', 'ledger-doctor', NULL, 0, ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    rows = query_entrypoints(connection)

    assert [(row.kind, row.name) for row in rows] == [
        ('command', 'ledger-doctor'),
        ('skill', 'writing-skills'),
    ]
    assert rows[0].active is False
    assert rows[0].source_path is None
    assert rows[1].active is True
    connection.close()

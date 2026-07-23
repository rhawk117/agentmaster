import pytest
from conftest import seed_project_run_task

from ledger.connection import connect
from ledger.migrations import migrate
from ledger.queries import query_entrypoints, query_runs, query_tokens

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


@pytest.mark.sqlite
def test_query_runs_on_a_fresh_ledger_is_empty(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    assert query_runs(connection) == []
    connection.close()


@pytest.mark.sqlite
def test_query_runs_lists_task_counts(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    seed_project_run_task(connection)

    rows = query_runs(connection)

    assert len(rows) == 1
    assert rows[0].run_id == 'run-1'
    assert rows[0].task_count == 1
    assert rows[0].completed_task_count == 0
    connection.close()


@pytest.mark.sqlite
def test_query_tokens_filters_by_run_id(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    seed = seed_project_run_task(connection)
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES ('agent-session-1', ?, 'implementer', 'claude', 'sonnet', 'running', ?)",
        (seed.run_id, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO MODEL_CALL (id, agent_session_id, model, input_tokens, '
        'output_tokens, created_at) '
        "VALUES ('call-1', 'agent-session-1', 'sonnet', 10, 20, ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    rows = query_tokens(connection, run_id=seed.run_id)

    assert len(rows) == 1
    assert rows[0].model == 'sonnet'
    assert rows[0].input_tokens == 10
    assert rows[0].output_tokens == 20

    assert query_tokens(connection, run_id='no-such-run') == []
    connection.close()

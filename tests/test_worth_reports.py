import sqlite3

import pytest

from ledger.connection import connect, connect_read_only
from ledger.migrations import migrate
from ledger.worth import (
    EvaluationInput,
    MetricInput,
    compute_memory_worth,
    compute_procedure_worth,
    compute_run_worth,
    record_evaluation,
)

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


def _seed_memory(connection: sqlite3.Connection, *, memory_id: str = 'memory-1') -> None:
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
            'Candidate',
            'lesson',
            'title',
            'content',
            _CREATED_AT,
            _CREATED_AT,
        ),
    )
    connection.commit()


def _seed_evaluation(
    connection: sqlite3.Connection, *, evaluation_id: str = 'eval-1'
) -> None:
    _seed_memory(connection)
    connection.execute(
        'INSERT INTO EVALUATION '
        '(id, memory_id, project_id, evaluation_kind, decision, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (evaluation_id, 'memory-1', 'project-1', 'worth', 'promote', _CREATED_AT),
    )
    connection.commit()


@pytest.mark.sqlite
def test_evaluation_metric_records_a_named_measure_with_a_method(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_evaluation(connection)

    connection.execute(
        'INSERT INTO EVALUATION_METRIC '
        '(evaluation_id, metric_name, value_microunits, unit, method) '
        "VALUES ('eval-1', 'reuse_count', 3000000, 'count', 'descriptive-cohort-a')"
    )
    connection.commit()

    row = connection.execute(
        'SELECT metric_name, value_microunits, unit, method FROM EVALUATION_METRIC '
        "WHERE evaluation_id = 'eval-1'"
    ).fetchone()
    assert row == ('reuse_count', 3000000, 'count', 'descriptive-cohort-a')
    connection.close()


@pytest.mark.sqlite
def test_evaluation_metric_requires_a_method(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_evaluation(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO EVALUATION_METRIC '
            '(evaluation_id, metric_name, value_microunits, unit, method) '
            "VALUES ('eval-1', 'reuse_count', 3000000, 'count', NULL)"
        )
    connection.close()


@pytest.mark.sqlite
def test_evaluation_metric_rejects_an_unknown_evaluation(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO EVALUATION_METRIC '
            '(evaluation_id, metric_name, value_microunits, unit, method) '
            "VALUES ('no-such-eval', 'reuse_count', 3000000, 'count', 'descriptive')"
        )
    connection.close()


@pytest.mark.sqlite
def test_a_single_evaluation_can_carry_multiple_named_metrics(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_evaluation(connection)

    connection.execute(
        'INSERT INTO EVALUATION_METRIC '
        '(evaluation_id, metric_name, value_microunits, unit, method) '
        "VALUES ('eval-1', 'reuse_count', 3000000, 'count', 'descriptive')"
    )
    connection.execute(
        'INSERT INTO EVALUATION_METRIC '
        '(evaluation_id, metric_name, value_microunits, unit, method) '
        "VALUES ('eval-1', 'harmful_count', 0, 'count', 'descriptive')"
    )
    connection.commit()

    rows = connection.execute(
        "SELECT metric_name FROM EVALUATION_METRIC WHERE evaluation_id = 'eval-1' "
        'ORDER BY metric_name'
    ).fetchall()
    assert rows == [('harmful_count',), ('reuse_count',)]
    connection.close()


@pytest.mark.sqlite
def test_evaluation_rejects_an_evaluator_session_id_from_a_user_session(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_memory(connection)
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        'VALUES (?, ?, ?)',
        ('user-session-1', 'harness-1', _CREATED_AT),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO EVALUATION '
            '(id, memory_id, project_id, evaluator_session_id, evaluation_kind, '
            'decision, created_at) '
            "VALUES ('eval-1', 'memory-1', 'project-1', 'user-session-1', 'worth', "
            "'promote', ?)",
            (_CREATED_AT,),
        )
    connection.close()


def _seed_run_with_tasks(
    connection: sqlite3.Connection, *, run_id: str = 'run-1'
) -> None:
    _seed_project(connection)
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        'VALUES (?, ?, ?)',
        ('user-session-1', 'harness-1', _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO RUN '
        '(id, project_id, user_session_id, delivery_mode, state, started_at) '
        "VALUES (?, 'project-1', 'user-session-1', 'local', 'Complete', ?)",
        (run_id, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO TASK (id, run_id, title, state, sequence_no) '
        "VALUES ('task-1', ?, 'title', 'complete', 1)",
        (run_id,),
    )
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES ('agent-session-1', ?, 'implementer', 'anthropic', "
        "'claude-sonnet', 'complete', ?)",
        (run_id, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO MODEL_CALL '
        '(id, agent_session_id, model, input_tokens, output_tokens, '
        'cost_micro_usd, created_at) '
        "VALUES ('call-1', 'agent-session-1', 'claude-sonnet', 100, 50, 1000, ?)",
        (_CREATED_AT,),
    )
    connection.commit()


@pytest.mark.sqlite
def test_compute_run_worth_returns_none_for_an_unknown_run(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    connection.close()
    read_connection = connect_read_only(tmp_path / 'ledger.sqlite3')

    report = compute_run_worth(read_connection, 'no-such-run')

    assert report is None
    read_connection.close()


@pytest.mark.sqlite
def test_compute_run_worth_reports_task_and_token_totals(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run_with_tasks(connection)
    connection.close()
    read_connection = connect_read_only(tmp_path / 'ledger.sqlite3')

    report = compute_run_worth(read_connection, 'run-1')

    assert report is not None
    assert report.task_count == 1
    assert report.completed_task_count == 1
    assert report.total_input_tokens == 100
    assert report.total_output_tokens == 50
    assert report.total_cost_micro_usd == 1000
    assert report.unresolved_finding_count == 0
    assert report.cohort
    assert report.method
    read_connection.close()


@pytest.mark.sqlite
def test_compute_memory_worth_reports_retrieval_helpful_harmful_counts(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run_with_tasks(connection)
    _seed_memory(connection)
    connection.execute(
        'INSERT INTO memory_access '
        '(id, run_id, memory_id, query_digest, rank, score, selected, used, '
        'helpful, harmful, retrieval_algorithm_version, created_at) '
        "VALUES ('access-1', 'run-1', 'memory-1', 'digest', 0, 1.0, 1, 1, 1, 0, "
        "'v1', ?)",
        (_CREATED_AT,),
    )
    connection.commit()
    connection.close()
    read_connection = connect_read_only(tmp_path / 'ledger.sqlite3')

    report = compute_memory_worth(read_connection, 'memory-1')

    assert report.retrieval_count == 1
    assert report.helpful_count == 1
    assert report.harmful_count == 0
    read_connection.close()


@pytest.mark.sqlite
def test_compute_procedure_worth_reports_use_count_by_outcome(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_procedure(connection)
    connection.execute(
        'INSERT INTO PROCEDURE_VERSION '
        '(id, procedure_id, version_no, content_hash, status, created_at) '
        "VALUES ('pv-1', 'procedure-1', 1, 'hash-1', 'active', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO PROCEDURE_USE (id, procedure_version_id, outcome, created_at) '
        "VALUES ('use-1', 'pv-1', 'success', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO PROCEDURE_USE (id, procedure_version_id, outcome, created_at) '
        "VALUES ('use-2', 'pv-1', 'success', ?)",
        (_CREATED_AT,),
    )
    connection.commit()
    connection.close()
    read_connection = connect_read_only(tmp_path / 'ledger.sqlite3')

    report = compute_procedure_worth(read_connection, 'procedure-1')

    assert report.use_count == 2
    assert report.outcome_counts == {'success': 2}
    read_connection.close()


@pytest.mark.sqlite
def test_record_evaluation_writes_a_worth_evaluation_with_metrics(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_procedure(connection)
    connection.execute(
        'INSERT INTO PROCEDURE_VERSION '
        '(id, procedure_id, version_no, content_hash, status, created_at) '
        "VALUES ('pv-1', 'procedure-1', 1, 'hash-1', 'active', ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    evaluation_id = record_evaluation(
        connection,
        EvaluationInput(
            id='eval-1',
            project_id='project-1',
            decision='keep',
            created_at=_CREATED_AT,
            procedure_version_id='pv-1',
        ),
        [
            MetricInput(
                metric_name='use_count', value=3, unit='count', method='descriptive'
            )
        ],
    )

    decision = connection.execute(
        'SELECT decision FROM EVALUATION WHERE id = ?', (evaluation_id,)
    ).fetchone()[0]
    assert decision == 'keep'
    value = connection.execute(
        'SELECT value_microunits FROM EVALUATION_METRIC WHERE evaluation_id = ?',
        (evaluation_id,),
    ).fetchone()[0]
    assert value == 3_000_000
    connection.close()

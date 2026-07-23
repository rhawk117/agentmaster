import sqlite3

import pytest

from ledger.connection import connect
from ledger.migrations import migrate

_ALL_VIEWS = (
    'v_run_summary',
    'v_task_acceptance_evidence',
    'v_token_usage_by_role',
    'v_token_usage_by_model',
    'v_delivery_current_head',
    'v_memory_retrieval_outcomes',
    'v_procedure_effectiveness',
    'v_project_active_memories',
    'v_unresolved_review_findings',
    'v_retention_candidates',
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


def _seed_run(connection: sqlite3.Connection, *, run_id: str = 'run-1') -> None:
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
        (run_id, 'project-1', 'user-session-1', 'local', 'Planned', _CREATED_AT),
    )
    connection.commit()


def _seed_memory(
    connection: sqlite3.Connection, *, memory_id: str = 'memory-1', state: str = 'Active'
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


@pytest.mark.sqlite
def test_every_stable_view_is_created(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    views = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view'"
        ).fetchall()
    }

    for view in _ALL_VIEWS:
        assert view in views
    connection.close()


@pytest.mark.sqlite
@pytest.mark.parametrize('view', _ALL_VIEWS)
def test_a_view_rejects_a_direct_insert(tmp_path, view):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    with pytest.raises(sqlite3.OperationalError):
        connection.execute(f'INSERT INTO {view} DEFAULT VALUES')
    connection.close()


_BASE_SHA = 'a' * 40
_HEAD_SHA = 'b' * 40


@pytest.mark.sqlite
def test_v_delivery_current_head_reflects_a_delivery_attempt_ci_check_and_review(
    tmp_path,
):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run(connection)
    connection.execute(
        'INSERT INTO DELIVERY_ATTEMPT '
        '(id, run_id, attempt_no, branch, base_sha, head_sha, pr_number, state, '
        'created_at) '
        "VALUES ('delivery-1', 'run-1', 1, 'feat/x', ?, ?, 7, 'open', ?)",
        (_BASE_SHA, _HEAD_SHA, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO CI_CHECK '
        '(id, delivery_attempt_id, name, head_sha, status, conclusion, observed_at) '
        "VALUES ('check-1', 'delivery-1', 'ci', ?, 'completed', 'success', ?)",
        (_HEAD_SHA, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES ('reviewer-1', 'run-1', 'reviewer', 'claude', 'opus', 'active', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO REVIEW '
        '(id, delivery_attempt_id, reviewer_session_id, reviewed_sha, verdict, '
        'created_at) '
        "VALUES ('review-1', 'delivery-1', 'reviewer-1', ?, 'GOOD', ?)",
        (_HEAD_SHA, _CREATED_AT),
    )
    connection.commit()

    row = connection.execute(
        'SELECT delivery_attempt_id, pr_number, ci_status, ci_conclusion, '
        'reviewed_sha, review_verdict FROM v_delivery_current_head '
        "WHERE delivery_attempt_id = 'delivery-1'"
    ).fetchone()

    assert row == ('delivery-1', 7, 'completed', 'success', _HEAD_SHA, 'GOOD')
    connection.close()


@pytest.mark.sqlite
def test_v_unresolved_review_findings_excludes_a_resolved_finding(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run(connection)
    connection.execute(
        'INSERT INTO DELIVERY_ATTEMPT '
        '(id, run_id, attempt_no, branch, base_sha, head_sha, state, created_at) '
        "VALUES ('delivery-1', 'run-1', 1, 'feat/x', ?, ?, 'open', ?)",
        (_BASE_SHA, _HEAD_SHA, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES ('reviewer-1', 'run-1', 'reviewer', 'claude', 'opus', 'active', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO REVIEW '
        '(id, delivery_attempt_id, reviewer_session_id, reviewed_sha, verdict, '
        'created_at) '
        "VALUES ('review-1', 'delivery-1', 'reviewer-1', ?, 'NEEDS_FIXES', ?)",
        (_HEAD_SHA, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO REVIEW_FINDING (id, review_id, severity, state, summary) '
        "VALUES ('finding-open', 'review-1', 'blocker', 'open', 'fix me')"
    )
    connection.execute(
        'INSERT INTO REVIEW_FINDING (id, review_id, severity, state, summary) '
        "VALUES ('finding-resolved', 'review-1', 'minor', 'resolved', 'already fixed')"
    )
    connection.commit()

    rows = connection.execute(
        'SELECT review_finding_id, reviewed_sha FROM v_unresolved_review_findings'
    ).fetchall()

    assert rows == [('finding-open', _HEAD_SHA)]
    connection.close()


@pytest.mark.sqlite
def test_v_run_summary_reflects_a_newly_added_run(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run(connection)

    row = connection.execute(
        "SELECT run_id, task_count FROM v_run_summary WHERE run_id = 'run-1'"
    ).fetchone()

    assert row == ('run-1', 0)
    connection.close()


@pytest.mark.sqlite
def test_v_run_summary_reflects_a_task_added_after_the_run(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run(connection)

    connection.execute(
        'INSERT INTO TASK (id, run_id, title, state, sequence_no) VALUES (?, ?, ?, ?, ?)',
        ('task-1', 'run-1', 'do the thing', 'ready', 1),
    )
    connection.commit()

    row = connection.execute(
        "SELECT task_count FROM v_run_summary WHERE run_id = 'run-1'"
    ).fetchone()

    assert row == (1,)
    connection.close()


@pytest.mark.sqlite
def test_v_project_active_memories_excludes_a_candidate_memory(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_memory(connection, memory_id='memory-1', state='Candidate')
    connection.execute(
        'INSERT INTO MEMORY_SCOPE (memory_id, scope_kind, project_id, created_at) '
        "VALUES ('memory-1', 'project', 'project-1', ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    rows = connection.execute(
        'SELECT memory_id FROM v_project_active_memories'
    ).fetchall()

    assert rows == []
    connection.close()


@pytest.mark.sqlite
def test_v_project_active_memories_reflects_an_activated_memory(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_memory(connection, memory_id='memory-1', state='Candidate')
    connection.execute(
        'INSERT INTO MEMORY_SCOPE (memory_id, scope_kind, project_id, created_at) '
        "VALUES ('memory-1', 'project', 'project-1', ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    connection.execute("UPDATE MEMORY SET state = 'Active' WHERE id = 'memory-1'")
    connection.commit()

    rows = connection.execute(
        'SELECT memory_id FROM v_project_active_memories'
    ).fetchall()

    assert rows == [('memory-1',)]
    connection.close()

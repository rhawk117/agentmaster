"""Tests for FEEDBACK recording (SPEC.md §17.2, §19, §23 Microtask 16)."""

import pytest
from conftest import seed_project_run_task

from ledger.feedback import FeedbackInput, UnknownReferenceError, record_feedback

_CREATED_AT = '2026-07-20T00:00:00Z'


@pytest.fixture
def connection(ledger_connection):
    seed_project_run_task(ledger_connection)
    return ledger_connection


@pytest.mark.sqlite
def test_record_feedback_inserts_a_row(connection):
    feedback = FeedbackInput(
        id='feedback-1',
        user_session_id='user-session-1',
        run_id='run-1',
        rating=1,
        created_at=_CREATED_AT,
        task_id='task-1',
        comment='helpful',
    )

    record_feedback(connection, feedback)

    row = connection.execute(
        'SELECT user_session_id, run_id, task_id, memory_id, rating, comment '
        "FROM FEEDBACK WHERE id = 'feedback-1'"
    ).fetchone()
    assert row == ('user-session-1', 'run-1', 'task-1', None, 1, 'helpful')


@pytest.mark.sqlite
@pytest.mark.parametrize('rating', [-2, 2, 5])
def test_record_feedback_rejects_an_out_of_range_rating(connection, rating):
    feedback = FeedbackInput(
        id='feedback-1',
        user_session_id='user-session-1',
        run_id='run-1',
        rating=rating,
        created_at=_CREATED_AT,
    )

    with pytest.raises(ValueError, match='rating must be one of'):
        record_feedback(connection, feedback)


@pytest.mark.sqlite
def test_record_feedback_rejects_an_unknown_run_id(connection):
    feedback = FeedbackInput(
        id='feedback-1',
        user_session_id='user-session-1',
        run_id='no-such-run',
        rating=0,
        created_at=_CREATED_AT,
    )

    with pytest.raises(UnknownReferenceError, match='RUN'):
        record_feedback(connection, feedback)


@pytest.mark.sqlite
def test_record_feedback_rejects_an_unknown_memory_id(connection):
    feedback = FeedbackInput(
        id='feedback-1',
        user_session_id='user-session-1',
        run_id='run-1',
        rating=0,
        created_at=_CREATED_AT,
        memory_id='no-such-memory',
    )

    with pytest.raises(UnknownReferenceError, match='MEMORY'):
        record_feedback(connection, feedback)


def _seed_memory(connection, *, memory_id: str = 'memory-1') -> None:
    connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, created_at, '
        'updated_at) '
        "VALUES (?, 'project-1', 'Active', 'lesson', 'title', 'content', ?, ?)",
        (memory_id, _CREATED_AT, _CREATED_AT),
    )
    connection.commit()


def _seed_memory_access(
    connection,
    *,
    access_id: str = 'access-1',
    run_id: str = 'run-1',
    memory_id: str = 'memory-1',
) -> None:
    connection.execute(
        'INSERT INTO memory_access '
        '(id, run_id, memory_id, query_digest, rank, score, '
        'retrieval_algorithm_version, created_at) '
        "VALUES (?, ?, ?, 'digest', 0, 1.0, 'v1', ?)",
        (access_id, run_id, memory_id, _CREATED_AT),
    )
    connection.commit()


@pytest.mark.sqlite
def test_record_feedback_marks_a_used_memory_helpful_and_bumps_usefulness_count(
    connection,
):
    _seed_memory(connection)
    _seed_memory_access(connection)
    feedback = FeedbackInput(
        id='feedback-1',
        user_session_id='user-session-1',
        run_id='run-1',
        rating=1,
        created_at=_CREATED_AT,
        memory_id='memory-1',
    )

    record_feedback(connection, feedback)

    helpful, harmful = connection.execute(
        "SELECT helpful, harmful FROM memory_access WHERE id = 'access-1'"
    ).fetchone()
    assert (helpful, harmful) == (1, 0)
    usefulness_count, harmful_count = connection.execute(
        "SELECT usefulness_count, harmful_count FROM MEMORY WHERE id = 'memory-1'"
    ).fetchone()
    assert (usefulness_count, harmful_count) == (1, 0)


@pytest.mark.sqlite
def test_record_feedback_marks_a_used_memory_harmful_and_bumps_harmful_count(connection):
    _seed_memory(connection)
    _seed_memory_access(connection)
    feedback = FeedbackInput(
        id='feedback-1',
        user_session_id='user-session-1',
        run_id='run-1',
        rating=-1,
        created_at=_CREATED_AT,
        memory_id='memory-1',
    )

    record_feedback(connection, feedback)

    helpful, harmful = connection.execute(
        "SELECT helpful, harmful FROM memory_access WHERE id = 'access-1'"
    ).fetchone()
    assert (helpful, harmful) == (0, 1)
    usefulness_count, harmful_count = connection.execute(
        "SELECT usefulness_count, harmful_count FROM MEMORY WHERE id = 'memory-1'"
    ).fetchone()
    assert (usefulness_count, harmful_count) == (0, 1)


@pytest.mark.sqlite
def test_record_feedback_leaves_counts_untouched_for_a_memory_never_used_in_the_run(
    connection,
):
    _seed_memory(connection)
    feedback = FeedbackInput(
        id='feedback-1',
        user_session_id='user-session-1',
        run_id='run-1',
        rating=1,
        created_at=_CREATED_AT,
        memory_id='memory-1',
    )

    record_feedback(connection, feedback)

    usefulness_count, harmful_count = connection.execute(
        "SELECT usefulness_count, harmful_count FROM MEMORY WHERE id = 'memory-1'"
    ).fetchone()
    assert (usefulness_count, harmful_count) == (0, 0)

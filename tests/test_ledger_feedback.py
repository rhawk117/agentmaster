"""Tests for FEEDBACK recording (SPEC.md §17.2, §19, §23 Microtask 16)."""

import pytest

from ledger.connection import connect
from ledger.feedback import FeedbackInput, UnknownReferenceError, record_feedback
from ledger.migrations import migrate

_CREATED_AT = '2026-07-20T00:00:00Z'


def _seed_run_and_task(connection):
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        "VALUES ('project-1', '/repo', 'fp-1', ?, ?)",
        (_CREATED_AT, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        "VALUES ('user-session-1', 'harness-1', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO RUN '
        '(id, project_id, user_session_id, delivery_mode, state, started_at) '
        "VALUES ('run-1', 'project-1', 'user-session-1', 'local', 'Planned', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO TASK (id, run_id, title, state, sequence_no) '
        "VALUES ('task-1', 'run-1', 'do the thing', 'ready', 1)"
    )
    connection.commit()


@pytest.fixture
def connection(tmp_path):
    conn = connect(tmp_path / 'ledger.sqlite3')
    migrate(conn)
    _seed_run_and_task(conn)
    yield conn
    conn.close()


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

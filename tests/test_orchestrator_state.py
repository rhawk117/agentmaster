"""Tests for the durable RUN/TASK execution state machine (SPEC.md §9.1, §23 M19)."""

import uuid

import pytest

from ledger.orchestrator_state import (
    RUN_COMPLETION_HOOKS,
    IllegalTransitionError,
    RunNotFoundError,
    RunTransitionInput,
    TaskNotFoundError,
    TaskTransitionInput,
    transition_run,
    transition_task,
)
from tests.conftest import seed_project_run_task


def _now() -> str:
    return '2026-07-21T00:00:00Z'


def _id() -> str:
    return str(uuid.uuid4())


def _run_input(*, reason: str | None = None) -> RunTransitionInput:
    return RunTransitionInput(now=_now(), id_factory=_id, reason=reason)


def _task_input(
    *, reason: str | None = None, lease_agent_session_id: str | None = None
) -> TaskTransitionInput:
    return TaskTransitionInput(
        now=_now(),
        id_factory=_id,
        reason=reason,
        lease_agent_session_id=lease_agent_session_id,
    )


def _seed_agent_session(connection, run_id: str, agent_session_id: str) -> None:
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES (?, ?, 'implementer', 'claude', 'sonnet', 'active', ?)",
        (agent_session_id, run_id, _now()),
    )
    connection.commit()


# --- RUN transitions ---------------------------------------------------------


@pytest.mark.sqlite
def test_transition_run_moves_through_the_full_legal_tail(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    for to_state in (
        'Preflight',
        'Executing',
        'Verifying',
        'DeliveryPending',
        'CIPending',
        'ReviewRequired',
        'Reviewing',
        'MergePending',
        'Merged',
        'RetrospectivePending',
        'Complete',
    ):
        transition_run(ledger_connection, seed.run_id, to_state, _run_input())

    state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert state == 'Complete'
    transitions = ledger_connection.execute(
        'SELECT COUNT(*) FROM RUN_TRANSITION WHERE run_id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert transitions == 11


@pytest.mark.sqlite
def test_transition_run_rejects_an_illegal_transition(ledger_connection):
    seed = seed_project_run_task(ledger_connection)

    with pytest.raises(IllegalTransitionError, match='Planned -> Executing'):
        transition_run(ledger_connection, seed.run_id, 'Executing', _run_input())

    state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert state == 'Planned'
    transitions = ledger_connection.execute(
        'SELECT COUNT(*) FROM RUN_TRANSITION WHERE run_id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert transitions == 0


@pytest.mark.sqlite
def test_transition_run_rejects_leaving_a_terminal_state(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    transition_run(ledger_connection, seed.run_id, 'Preflight', _run_input())
    transition_run(
        ledger_connection, seed.run_id, 'Blocked', _run_input(reason='missing tool')
    )

    with pytest.raises(IllegalTransitionError, match='Blocked -> Executing'):
        transition_run(ledger_connection, seed.run_id, 'Executing', _run_input())


@pytest.mark.sqlite
def test_transition_run_same_state_is_an_idempotent_no_op(ledger_connection):
    seed = seed_project_run_task(ledger_connection)

    transition_run(ledger_connection, seed.run_id, 'Planned', _run_input())

    transitions = ledger_connection.execute(
        'SELECT COUNT(*) FROM RUN_TRANSITION WHERE run_id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert transitions == 0


@pytest.mark.sqlite
def test_transition_run_unknown_run_raises_run_not_found(ledger_connection):
    with pytest.raises(RunNotFoundError):
        transition_run(ledger_connection, 'no-such-run', 'Preflight', _run_input())


@pytest.mark.sqlite
def test_transition_run_to_blocked_records_reason(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    transition_run(ledger_connection, seed.run_id, 'Preflight', _run_input())

    transition_run(
        ledger_connection,
        seed.run_id,
        'Blocked',
        _run_input(reason='missing GitHub authority'),
    )

    row = ledger_connection.execute(
        'SELECT blocked_reason, ended_at FROM RUN WHERE id = ?', (seed.run_id,)
    ).fetchone()
    assert row[0] == 'missing GitHub authority'
    assert row[1] == _now()
    reason = ledger_connection.execute(
        "SELECT reason FROM RUN_TRANSITION WHERE run_id = ? AND to_state = 'Blocked'",
        (seed.run_id,),
    ).fetchone()[0]
    assert reason == 'missing GitHub authority'


@pytest.mark.sqlite
def test_run_completion_hooks_fire_when_a_run_reaches_complete(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    fired: list[str] = []
    RUN_COMPLETION_HOOKS.append(lambda _connection, run_id: fired.append(run_id))
    try:
        for to_state in (
            'Preflight',
            'Executing',
            'Verifying',
            'DeliveryPending',
            'CIPending',
            'ReviewRequired',
            'Reviewing',
            'MergePending',
            'Merged',
            'RetrospectivePending',
        ):
            transition_run(ledger_connection, seed.run_id, to_state, _run_input())
        assert fired == []
        transition_run(ledger_connection, seed.run_id, 'Complete', _run_input())
    finally:
        RUN_COMPLETION_HOOKS.clear()

    assert fired == [seed.run_id]


# --- TASK transitions ---------------------------------------------------------


@pytest.mark.sqlite
def test_transition_task_moves_through_a_legal_path(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _seed_agent_session(ledger_connection, seed.run_id, 'agent-session-1')

    transition_task(
        ledger_connection,
        'task-1',
        'running',
        _task_input(lease_agent_session_id='agent-session-1'),
    )
    transition_task(ledger_connection, 'task-1', 'review-required', _task_input())
    transition_task(ledger_connection, 'task-1', 'complete', _task_input())

    row = ledger_connection.execute(
        'SELECT state, lease_agent_session_id, started_at, ended_at FROM TASK '
        'WHERE id = ?',
        ('task-1',),
    ).fetchone()
    assert row[0] == 'complete'
    assert row[1] is None  # lease released once the task left 'running'
    assert row[2] == _now()
    assert row[3] == _now()
    transitions = ledger_connection.execute(
        'SELECT COUNT(*) FROM TASK_TRANSITION WHERE task_id = ?', ('task-1',)
    ).fetchone()[0]
    assert transitions == 3


@pytest.mark.sqlite
def test_transition_task_rejects_an_illegal_transition(ledger_connection):
    seed_project_run_task(ledger_connection)

    with pytest.raises(IllegalTransitionError, match='ready -> complete'):
        transition_task(ledger_connection, 'task-1', 'complete', _task_input())


@pytest.mark.sqlite
def test_transition_task_same_state_is_an_idempotent_no_op(ledger_connection):
    seed_project_run_task(ledger_connection)

    transition_task(ledger_connection, 'task-1', 'ready', _task_input())

    transitions = ledger_connection.execute(
        'SELECT COUNT(*) FROM TASK_TRANSITION WHERE task_id = ?', ('task-1',)
    ).fetchone()[0]
    assert transitions == 0


@pytest.mark.sqlite
def test_transition_task_unknown_task_raises_task_not_found(ledger_connection):
    with pytest.raises(TaskNotFoundError):
        transition_task(ledger_connection, 'no-such-task', 'running', _task_input())


@pytest.mark.sqlite
def test_transition_task_to_blocked_records_reason(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _seed_agent_session(ledger_connection, seed.run_id, 'agent-session-1')
    transition_task(
        ledger_connection,
        'task-1',
        'running',
        _task_input(lease_agent_session_id='agent-session-1'),
    )

    transition_task(
        ledger_connection,
        'task-1',
        'blocked',
        _task_input(reason='waiting on dependency'),
    )

    row = ledger_connection.execute(
        'SELECT blocked_reason, lease_agent_session_id FROM TASK WHERE id = ?',
        ('task-1',),
    ).fetchone()
    assert row[0] == 'waiting on dependency'
    assert row[1] is None

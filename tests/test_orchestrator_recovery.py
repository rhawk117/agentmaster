"""Tests for interruption recovery (SPEC.md §9, §23 M19)."""

import uuid

import pytest

from ledger.orchestrator_recovery import recover_run
from ledger.orchestrator_state import (
    RunNotFoundError,
    RunTransitionInput,
    TaskTransitionInput,
    transition_run,
    transition_task,
)
from tests.conftest import seed_project_run_task


def _now() -> str:
    return '2026-07-21T00:00:00Z'


def _id() -> str:
    return str(uuid.uuid4())


def _seed_agent_session(connection, run_id: str, agent_session_id: str) -> None:
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES (?, ?, 'implementer', 'claude', 'sonnet', 'active', ?)",
        (agent_session_id, run_id, _now()),
    )
    connection.commit()


def _advance_run(connection, run_id: str, *states: str) -> None:
    for state in states:
        transition_run(
            connection, run_id, state, RunTransitionInput(now=_now(), id_factory=_id)
        )


@pytest.mark.sqlite
def test_recover_run_releases_a_stale_running_lease(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _seed_agent_session(ledger_connection, seed.run_id, 'agent-session-1')
    _advance_run(ledger_connection, seed.run_id, 'Preflight', 'Executing')
    transition_task(
        ledger_connection,
        'task-1',
        'running',
        TaskTransitionInput(
            now=_now(), id_factory=_id, lease_agent_session_id='agent-session-1'
        ),
    )

    report = recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    assert report.requires_user_direction is False
    assert report.released_task_ids == ('task-1',)
    row = ledger_connection.execute(
        'SELECT state, lease_agent_session_id FROM TASK WHERE id = ?', ('task-1',)
    ).fetchone()
    assert row == ('blocked', None)
    events = ledger_connection.execute(
        "SELECT COUNT(*) FROM RECOVERY_EVENT WHERE run_id = ? AND task_id = 'task-1'",
        (seed.run_id,),
    ).fetchone()[0]
    assert events == 1


@pytest.mark.sqlite
def test_recover_run_is_idempotent_on_a_consistent_database(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _seed_agent_session(ledger_connection, seed.run_id, 'agent-session-1')
    _advance_run(ledger_connection, seed.run_id, 'Preflight', 'Executing')
    transition_task(
        ledger_connection,
        'task-1',
        'running',
        TaskTransitionInput(
            now=_now(), id_factory=_id, lease_agent_session_id='agent-session-1'
        ),
    )
    recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    second = recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    assert second.released_task_ids == ()
    events = ledger_connection.execute(
        'SELECT COUNT(*) FROM RECOVERY_EVENT WHERE run_id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert events == 1


@pytest.mark.sqlite
def test_recover_run_requires_user_direction_for_external_reconciliation(
    ledger_connection,
):
    seed = seed_project_run_task(ledger_connection)
    _advance_run(
        ledger_connection,
        seed.run_id,
        'Preflight',
        'Executing',
        'Verifying',
        'DeliveryPending',
        'CIPending',
        'ReviewRequired',
    )

    report = recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    assert report.requires_user_direction is True
    assert report.reason is not None
    assert 'ReviewRequired' in report.reason
    state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert state == 'ReviewRequired'
    events = ledger_connection.execute(
        'SELECT COUNT(*) FROM RECOVERY_EVENT WHERE run_id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert events == 1


@pytest.mark.sqlite
def test_recover_run_requires_user_direction_is_idempotent(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _advance_run(
        ledger_connection,
        seed.run_id,
        'Preflight',
        'Executing',
        'Verifying',
        'DeliveryPending',
        'CIPending',
        'ReviewRequired',
    )
    recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    second = recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    assert second.requires_user_direction is True
    events = ledger_connection.execute(
        'SELECT COUNT(*) FROM RECOVERY_EVENT WHERE run_id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert events == 1


@pytest.mark.sqlite
def test_recover_run_releases_a_stale_lease_from_fixes_required(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _seed_agent_session(ledger_connection, seed.run_id, 'agent-session-1')
    _advance_run(ledger_connection, seed.run_id, 'Preflight', 'Executing', 'Verifying')
    transition_task(
        ledger_connection,
        'task-1',
        'running',
        TaskTransitionInput(
            now=_now(), id_factory=_id, lease_agent_session_id='agent-session-1'
        ),
    )
    _advance_run(ledger_connection, seed.run_id, 'FixesRequired')

    report = recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    assert report.requires_user_direction is False
    assert report.released_task_ids == ('task-1',)
    row = ledger_connection.execute(
        'SELECT state, lease_agent_session_id FROM TASK WHERE id = ?', ('task-1',)
    ).fetchone()
    assert row == ('blocked', None)


@pytest.mark.sqlite
def test_recover_run_advances_merged_to_retrospective_pending(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _advance_run(
        ledger_connection,
        seed.run_id,
        'Preflight',
        'Executing',
        'Verifying',
        'DeliveryPending',
        'CIPending',
        'ReviewRequired',
        'Reviewing',
        'MergePending',
        'Merged',
    )

    report = recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    assert report.requires_user_direction is False
    assert report.released_task_ids == ()
    state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert state == 'RetrospectivePending'
    events = ledger_connection.execute(
        'SELECT COUNT(*) FROM RECOVERY_EVENT WHERE run_id = ? '
        "AND decision = 'advanced-to-retrospective-pending'",
        (seed.run_id,),
    ).fetchone()[0]
    assert events == 1


@pytest.mark.sqlite
def test_recover_run_flags_retrospective_pending_as_resumable(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _advance_run(
        ledger_connection,
        seed.run_id,
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
    )

    report = recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)
    second = recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    assert report.requires_user_direction is False
    assert second.requires_user_direction is False
    state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert state == 'RetrospectivePending'
    events = ledger_connection.execute(
        'SELECT COUNT(*) FROM RECOVERY_EVENT WHERE run_id = ? '
        "AND decision = 'retrospective-resumable'",
        (seed.run_id,),
    ).fetchone()[0]
    assert events == 1


@pytest.mark.sqlite
def test_recover_run_releases_a_stale_lease_between_dispatch_and_verification(
    ledger_connection,
):
    """A coordinator killed after acquiring a task lease but before the RUN
    reaches 'Verifying' leaves that task 'running' with a lease; recovery
    must release it so a fresh dispatch can pick the task back up, never
    re-dispatching it while the stale lease is still held.
    """
    seed = seed_project_run_task(ledger_connection)
    _seed_agent_session(ledger_connection, seed.run_id, 'agent-session-1')
    _advance_run(ledger_connection, seed.run_id, 'Preflight', 'Executing')
    transition_task(
        ledger_connection,
        'task-1',
        'running',
        TaskTransitionInput(
            now=_now(), id_factory=_id, lease_agent_session_id='agent-session-1'
        ),
    )
    _advance_run(ledger_connection, seed.run_id, 'Verifying')

    report = recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    assert report.requires_user_direction is False
    assert report.released_task_ids == ('task-1',)
    row = ledger_connection.execute(
        'SELECT state, lease_agent_session_id FROM TASK WHERE id = ?', ('task-1',)
    ).fetchone()
    assert row == ('blocked', None)


@pytest.mark.sqlite
def test_resume_after_recovery_dispatches_the_released_task_exactly_once(
    ledger_connection,
):
    """After recovery releases a stale lease, resuming dispatch (blocked ->
    ready -> running with a new lease) must not create a second TASK row or
    a duplicate 'running' lease -- exactly one task, one live lease.
    """
    seed = seed_project_run_task(ledger_connection)
    _seed_agent_session(ledger_connection, seed.run_id, 'agent-session-1')
    _seed_agent_session(ledger_connection, seed.run_id, 'agent-session-2')
    _advance_run(ledger_connection, seed.run_id, 'Preflight', 'Executing')
    transition_task(
        ledger_connection,
        'task-1',
        'running',
        TaskTransitionInput(
            now=_now(), id_factory=_id, lease_agent_session_id='agent-session-1'
        ),
    )

    recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    transition_task(
        ledger_connection,
        'task-1',
        'ready',
        TaskTransitionInput(now=_now(), id_factory=_id),
    )
    transition_task(
        ledger_connection,
        'task-1',
        'running',
        TaskTransitionInput(
            now=_now(), id_factory=_id, lease_agent_session_id='agent-session-2'
        ),
    )

    task_count = ledger_connection.execute(
        'SELECT COUNT(*) FROM TASK WHERE run_id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert task_count == 1
    row = ledger_connection.execute(
        'SELECT state, lease_agent_session_id FROM TASK WHERE id = ?', ('task-1',)
    ).fetchone()
    assert row == ('running', 'agent-session-2')


@pytest.mark.sqlite
def test_recover_run_is_a_no_op_when_nothing_needs_reconciling(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _advance_run(ledger_connection, seed.run_id, 'Preflight', 'Executing')

    report = recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    assert report.requires_user_direction is False
    assert report.released_task_ids == ()
    events = ledger_connection.execute(
        'SELECT COUNT(*) FROM RECOVERY_EVENT WHERE run_id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert events == 0


@pytest.mark.sqlite
def test_recover_run_is_a_no_op_for_a_terminal_run(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _advance_run(ledger_connection, seed.run_id, 'Preflight', 'Executing', 'Verifying')
    transition_run(
        ledger_connection,
        seed.run_id,
        'FixesRequired',
        RunTransitionInput(now=_now(), id_factory=_id),
    )
    transition_run(
        ledger_connection,
        seed.run_id,
        'Executing',
        RunTransitionInput(now=_now(), id_factory=_id),
    )
    transition_run(
        ledger_connection,
        seed.run_id,
        'Cancelled',
        RunTransitionInput(now=_now(), id_factory=_id),
    )

    report = recover_run(ledger_connection, seed.run_id, now=_now(), id_factory=_id)

    assert report.requires_user_direction is False
    assert report.released_task_ids == ()


@pytest.mark.sqlite
def test_recover_run_unknown_run_raises_run_not_found(ledger_connection):
    with pytest.raises(RunNotFoundError):
        recover_run(ledger_connection, 'no-such-run', now=_now(), id_factory=_id)

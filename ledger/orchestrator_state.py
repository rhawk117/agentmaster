from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

RUN_TERMINAL_STATES: frozenset[str] = frozenset({
    'Complete',
    'Blocked',
    'Failed',
    'Cancelled',
})

RUN_TRANSITIONS: dict[str, tuple[str, ...]] = {
    'Planned': ('Preflight', 'Failed', 'Cancelled'),
    'Preflight': ('Executing', 'Blocked', 'Failed', 'Cancelled'),
    'Executing': ('Verifying', 'Failed', 'Cancelled'),
    'Verifying': ('FixesRequired', 'DeliveryPending', 'Failed', 'Cancelled'),
    'FixesRequired': ('Executing', 'Failed', 'Cancelled'),
    'DeliveryPending': ('CIPending', 'Failed', 'Cancelled'),
    'CIPending': ('FixesRequired', 'ReviewRequired', 'Failed', 'Cancelled'),
    'ReviewRequired': ('Reviewing', 'Failed', 'Cancelled'),
    'Reviewing': ('FixesRequired', 'MergePending', 'Failed', 'Cancelled'),
    'MergePending': ('Merged', 'Failed', 'Cancelled'),
    'Merged': ('RetrospectivePending',),
    'RetrospectivePending': ('Complete',),
    'Complete': (),
    'Blocked': (),
    'Failed': (),
    'Cancelled': (),
}

BLOCKING_COMPLETION_STATES: frozenset[str] = frozenset({
    'ReviewRequired',
    'Reviewing',
    'FixesRequired',
    'MergePending',
    'RetrospectivePending',
})

TASK_TERMINAL_STATES: frozenset[str] = frozenset({'complete'})

TASK_TRANSITIONS: dict[str, tuple[str, ...]] = {
    'ready': ('running', 'blocked'),
    'running': ('blocked', 'failed', 'review-required', 'complete'),
    'blocked': ('ready', 'failed'),
    'review-required': ('running', 'complete', 'failed'),
    'failed': ('ready',),
    'complete': (),
}

RUN_COMPLETION_HOOKS: list[Callable[[sqlite3.Connection, str], None]] = []


class RunNotFoundError(ValueError): ...


class TaskNotFoundError(ValueError): ...


class IllegalTransitionError(ValueError): ...


@dataclass(frozen=True, slots=True)
class RunTransitionInput:
    now: str
    id_factory: Callable[[], str]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class TaskTransitionInput:
    now: str
    id_factory: Callable[[], str]
    reason: str | None = None
    lease_agent_session_id: str | None = None


def _current_run_state(connection: sqlite3.Connection, run_id: str) -> str:
    row = connection.execute('SELECT state FROM RUN WHERE id = ?', (run_id,)).fetchone()
    if row is None:
        raise RunNotFoundError(run_id)
    return row[0]


def _current_task_state(connection: sqlite3.Connection, task_id: str) -> str:
    row = connection.execute('SELECT state FROM TASK WHERE id = ?', (task_id,)).fetchone()
    if row is None:
        raise TaskNotFoundError(task_id)
    return row[0]


def transition_run(
    connection: sqlite3.Connection,
    run_id: str,
    to_state: str,
    transition: RunTransitionInput,
) -> None:
    current = _current_run_state(connection, run_id)
    if current == to_state:
        return
    if to_state not in RUN_TRANSITIONS.get(current, ()):
        raise IllegalTransitionError(
            f'RUN {run_id}: {current} -> {to_state} is not permitted'
        )
    ends_run = to_state in RUN_TERMINAL_STATES
    transition_id = transition.id_factory()
    now, reason = transition.now, transition.reason

    def _op(conn: sqlite3.Connection) -> None:
        conn.execute(
            'UPDATE RUN SET state = ?, blocked_reason = ?, '
            'ended_at = CASE WHEN ? THEN ? ELSE ended_at END WHERE id = ?',
            (to_state, reason, ends_run, now if ends_run else None, run_id),
        )
        conn.execute(
            'INSERT INTO RUN_TRANSITION '
            '(id, run_id, from_state, to_state, reason, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (transition_id, run_id, current, to_state, reason, now),
        )

    run_write_transaction(connection, _op)
    if to_state == 'Complete':
        for hook in RUN_COMPLETION_HOOKS:
            hook(connection, run_id)


def transition_task(
    connection: sqlite3.Connection,
    task_id: str,
    to_state: str,
    transition: TaskTransitionInput,
) -> None:
    current = _current_task_state(connection, task_id)
    if current == to_state:
        return
    if to_state not in TASK_TRANSITIONS.get(current, ()):
        raise IllegalTransitionError(
            f'TASK {task_id}: {current} -> {to_state} is not permitted'
        )
    run_id = connection.execute(
        'SELECT run_id FROM TASK WHERE id = ?', (task_id,)
    ).fetchone()[0]
    entering_running = to_state == 'running'
    leaving_running = current == 'running'
    ends_task = to_state in ('complete', 'failed')
    transition_id = transition.id_factory()
    now, reason = transition.now, transition.reason
    lease_agent_session_id = transition.lease_agent_session_id

    def _op(conn: sqlite3.Connection) -> None:
        conn.execute(
            'UPDATE TASK SET state = ?, blocked_reason = ?, '
            'lease_agent_session_id = CASE '
            '  WHEN ? THEN ? WHEN ? THEN NULL ELSE lease_agent_session_id END, '
            'lease_acquired_at = CASE '
            '  WHEN ? THEN ? WHEN ? THEN NULL ELSE lease_acquired_at END, '
            'started_at = CASE WHEN ? AND started_at IS NULL THEN ? ELSE started_at END, '
            'ended_at = CASE WHEN ? THEN ? ELSE ended_at END '
            'WHERE id = ?',
            (
                to_state,
                reason,
                entering_running,
                lease_agent_session_id,
                leaving_running,
                entering_running,
                now,
                leaving_running,
                entering_running,
                now,
                ends_task,
                now if ends_task else None,
                task_id,
            ),
        )
        conn.execute(
            'INSERT INTO TASK_TRANSITION '
            '(id, task_id, run_id, from_state, to_state, reason, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (transition_id, task_id, run_id, current, to_state, reason, now),
        )

    run_write_transaction(connection, _op)

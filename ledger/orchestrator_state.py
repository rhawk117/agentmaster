"""Durable RUN/TASK execution state machine (SPEC.md §9.1, §23 Microtask 19).

Replaces implicit, unvalidated `UPDATE ... SET state = ...` calls with legality-
checked transitions that append an immutable `RUN_TRANSITION`/`TASK_TRANSITION`
row (SPEC.md §9: "record every state transition and its evidence"). A
same-state request is a no-op rather than an error or a duplicate event, so
dispatch and interruption recovery (`ledger.orchestrator_recovery`) can call
these functions without first checking current state (§23 M19: "make dispatch
and transition operations idempotent").

`RUN_TRANSITIONS` is exactly SPEC.md §9.1's diagram, plus `Failed`/`Cancelled`
reachable from every non-terminal state (execution failure or user
cancellation can occur at any point) and `Blocked` only where the diagram
draws it (Preflight). `TASK_TRANSITIONS` has no dedicated spec diagram — it is
a bounded, conservative machine over TASK's existing CHECK-constrained state
set (`ready`, `running`, `blocked`, `failed`, `review-required`, `complete`).

`RUN_COMPLETION_HOOKS` is the seam SPEC.md §9.1 describes for the
Merged->RetrospectivePending->Complete tail ("Feedback capture attaches at
the RetrospectivePending->Complete transition"): a later microtask appends its
feedback-capture callback here. This module fires whatever hooks are
registered but implements none itself.
"""

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

# SPEC.md §20.3: "A stop hook blocks successful execution termination while
# the state is REVIEW_REQUIRED, REVIEWING, FIXES_REQUIRED, MERGE_PENDING, or
# RETROSPECTIVE_PENDING." `hooks/execute_stop.py` cannot import this module
# (hook processes run standalone, copied without the `ledger` package), so it
# duplicates this exact set as a literal -- this constant is that set's
# source of truth for the orchestrator-side callers (`ledger.review_gate`)
# that can import it directly.
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

# SPEC.md §9.1: feedback capture attaches here; Microtask 26 appends its
# hook, this module never populates it.
RUN_COMPLETION_HOOKS: list[Callable[[sqlite3.Connection, str], None]] = []


class RunNotFoundError(ValueError):
    """No RUN row exists for the requested id."""


class TaskNotFoundError(ValueError):
    """No TASK row exists for the requested id."""


class IllegalTransitionError(ValueError):
    """The requested RUN/TASK state transition is not permitted by SPEC.md §9.1."""


@dataclass(frozen=True, slots=True)
class RunTransitionInput:
    """The clock, minting, and reason a `transition_run` call needs."""

    now: str
    id_factory: Callable[[], str]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class TaskTransitionInput:
    """The clock, minting, reason, and lease a `transition_task` call needs."""

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
    """Transition RUN `run_id` to `to_state`, appending a RUN_TRANSITION row.

    Requesting the current state again is a no-op. Reaching `to_state ==
    'Complete'` runs every hook in `RUN_COMPLETION_HOOKS` after the
    transition commits.

    Raises
    ------
    RunNotFoundError
        No RUN row exists for `run_id`.
    IllegalTransitionError
        `current -> to_state` is not in `RUN_TRANSITIONS[current]`.
    """
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
    """Transition TASK `task_id` to `to_state`, appending a TASK_TRANSITION row.

    Requesting the current state again is a no-op. Entering `'running'` sets
    `started_at` (if unset) and the running lease (`lease_agent_session_id`);
    leaving `'running'` releases that lease. Entering `'complete'` or
    `'failed'` sets `ended_at`.

    Raises
    ------
    TaskNotFoundError
        No TASK row exists for `task_id`.
    IllegalTransitionError
        `current -> to_state` is not in `TASK_TRANSITIONS[current]`.
    """
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

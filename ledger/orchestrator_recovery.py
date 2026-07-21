"""Interruption recovery for the RUN/TASK state machine (SPEC.md §9, §23 Microtask 19).

Ledger-only recovery: it reconciles what the ledger itself can prove (stale
task leases left behind by a killed dispatch process) and refuses to guess
at what it cannot — a RUN already past `DeliveryPending` needs git
branch/head, PR, CI, or review state to reconcile safely, and none of
DELIVERY_ATTEMPT/CI_CHECK/REVIEW exist yet (they arrive with Microtasks
21/22). For those states this module records that user direction is
required instead of silently no-opping or guessing (SPEC.md §9: the
orchestrator fails closed).

Every decision `recover_run` makes is recorded as a RECOVERY_EVENT before it
returns. Re-running recovery on an already-consistent database — no stale
lease left, or the same "needs user direction" state already recorded — is
a no-op: it takes no further action and appends no further event.
"""

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.orchestrator_state import (
    RunNotFoundError,
    TaskTransitionInput,
    transition_task,
)
from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

# RUN states whose only outstanding work is local (leases + the task graph);
# recovery can reconcile these without any external system.
_LOCALLY_RECOVERABLE_RUN_STATES = frozenset({
    'Planned',
    'Preflight',
    'Executing',
    'Verifying',
    'FixesRequired',
})

# RUN states that need git/PR/CI/review reconciliation this ledger cannot yet
# perform (SPEC.md §23 Microtasks 21/22 add the tables that would allow it).
_EXTERNAL_RECONCILIATION_RUN_STATES = frozenset({
    'DeliveryPending',
    'CIPending',
    'ReviewRequired',
    'Reviewing',
    'MergePending',
})

STALE_LEASE_REASON = 'recovered after interruption: released a stale running lease'


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """The outcome of one `recover_run` call."""

    run_id: str
    requires_user_direction: bool
    reason: str | None
    released_task_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RecoveryEvent:
    """One RECOVERY_EVENT row's fields, bundled to keep the writer's signature narrow."""

    run_id: str
    task_id: str | None
    decision: str
    detail: str | None
    now: str


def _current_run_state(connection: sqlite3.Connection, run_id: str) -> str:
    row = connection.execute('SELECT state FROM RUN WHERE id = ?', (run_id,)).fetchone()
    if row is None:
        raise RunNotFoundError(run_id)
    return row[0]


def _stale_leased_task_ids(connection: sqlite3.Connection, run_id: str) -> list[str]:
    rows = connection.execute(
        "SELECT id FROM TASK WHERE run_id = ? AND state = 'running' "
        'AND lease_agent_session_id IS NOT NULL',
        (run_id,),
    ).fetchall()
    return [row[0] for row in rows]


def _record_recovery_event(connection: sqlite3.Connection, event: _RecoveryEvent) -> None:
    def _op(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT INTO RECOVERY_EVENT '
            '(id, run_id, task_id, decision, detail, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (
                str(uuid.uuid4()),
                event.run_id,
                event.task_id,
                event.decision,
                event.detail,
                event.now,
            ),
        )

    run_write_transaction(connection, _op)


def _release_stale_leases(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    now: str,
    id_factory: Callable[[], str],
) -> tuple[str, ...]:
    stale_task_ids = _stale_leased_task_ids(connection, run_id)
    for task_id in stale_task_ids:
        transition_task(
            connection,
            task_id,
            'blocked',
            TaskTransitionInput(
                now=now, id_factory=id_factory, reason=STALE_LEASE_REASON
            ),
        )
        _record_recovery_event(
            connection,
            _RecoveryEvent(
                run_id=run_id,
                task_id=task_id,
                decision='released-stale-lease',
                detail=STALE_LEASE_REASON,
                now=now,
            ),
        )
    return tuple(stale_task_ids)


def _already_flagged_for_user_direction(
    connection: sqlite3.Connection, run_id: str, *, state: str
) -> bool:
    row = connection.execute(
        'SELECT 1 FROM RECOVERY_EVENT WHERE run_id = ? AND task_id IS NULL '
        "AND decision = 'requires-user-direction' AND detail = ?",
        (run_id, state),
    ).fetchone()
    return row is not None


def recover_run(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    now: str,
    id_factory: Callable[[], str],
) -> RecoveryReport:
    """Reconcile `run_id` after a killed dispatch process, recording every decision made.

    Raises
    ------
    RunNotFoundError
        No RUN row exists for `run_id`.
    """
    state = _current_run_state(connection, run_id)

    if state in _EXTERNAL_RECONCILIATION_RUN_STATES:
        reason = (
            f'RUN {run_id} is in {state}, which needs git/CI/review reconciliation '
            'not yet available to ledger-only recovery; user direction is required'
        )
        if not _already_flagged_for_user_direction(connection, run_id, state=state):
            _record_recovery_event(
                connection,
                _RecoveryEvent(
                    run_id=run_id,
                    task_id=None,
                    decision='requires-user-direction',
                    detail=state,
                    now=now,
                ),
            )
        return RecoveryReport(
            run_id=run_id,
            requires_user_direction=True,
            reason=reason,
            released_task_ids=(),
        )

    if state not in _LOCALLY_RECOVERABLE_RUN_STATES:
        return RecoveryReport(
            run_id=run_id,
            requires_user_direction=False,
            reason=None,
            released_task_ids=(),
        )

    released = _release_stale_leases(connection, run_id, now=now, id_factory=id_factory)
    return RecoveryReport(
        run_id=run_id,
        requires_user_direction=False,
        reason=None,
        released_task_ids=released,
    )

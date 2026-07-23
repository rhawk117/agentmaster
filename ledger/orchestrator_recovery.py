import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.orchestrator_state import (
    RunNotFoundError,
    RunTransitionInput,
    TaskTransitionInput,
    transition_run,
    transition_task,
)
from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

_LOCALLY_RECOVERABLE_RUN_STATES = frozenset({
    'Planned',
    'Preflight',
    'Executing',
    'Verifying',
    'FixesRequired',
})

_EXTERNAL_RECONCILIATION_RUN_STATES = frozenset({
    'DeliveryPending',
    'CIPending',
    'ReviewRequired',
    'Reviewing',
    'MergePending',
})

STALE_LEASE_REASON = 'recovered after interruption: released a stale running lease'
MERGED_ADVANCE_REASON = (
    'recovered after interruption: Merged needs no external reconciliation -- '
    'the git publisher only records Merged after the GitHub merge succeeds -- '
    'so recovery advanced the RUN to RetrospectivePending'
)
RETROSPECTIVE_RESUMABLE_REASON = (
    'recovered after interruption: RetrospectivePending is resumable in place '
    'because run_retrospective is idempotent'
)


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    run_id: str
    requires_user_direction: bool
    reason: str | None
    released_task_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RecoveryEvent:
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


def _already_recorded_run_decision(
    connection: sqlite3.Connection, run_id: str, *, decision: str, detail: str
) -> bool:
    row = connection.execute(
        'SELECT 1 FROM RECOVERY_EVENT WHERE run_id = ? AND task_id IS NULL '
        'AND decision = ? AND detail = ?',
        (run_id, decision, detail),
    ).fetchone()
    return row is not None


def recover_run(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    now: str,
    id_factory: Callable[[], str],
) -> RecoveryReport:
    state = _current_run_state(connection, run_id)

    if state in _EXTERNAL_RECONCILIATION_RUN_STATES:
        reason = (
            f'RUN {run_id} is in {state}, which needs git/CI/review reconciliation '
            'not yet available to ledger-only recovery; user direction is required'
        )
        if not _already_recorded_run_decision(
            connection, run_id, decision='requires-user-direction', detail=state
        ):
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

    if state == 'Merged':
        transition_run(
            connection,
            run_id,
            'RetrospectivePending',
            RunTransitionInput(now=now, id_factory=id_factory),
        )
        _record_recovery_event(
            connection,
            _RecoveryEvent(
                run_id=run_id,
                task_id=None,
                decision='advanced-to-retrospective-pending',
                detail=MERGED_ADVANCE_REASON,
                now=now,
            ),
        )
        return RecoveryReport(
            run_id=run_id,
            requires_user_direction=False,
            reason=MERGED_ADVANCE_REASON,
            released_task_ids=(),
        )

    if state == 'RetrospectivePending':
        if not _already_recorded_run_decision(
            connection, run_id, decision='retrospective-resumable', detail=state
        ):
            _record_recovery_event(
                connection,
                _RecoveryEvent(
                    run_id=run_id,
                    task_id=None,
                    decision='retrospective-resumable',
                    detail=state,
                    now=now,
                ),
            )
        return RecoveryReport(
            run_id=run_id,
            requires_user_direction=False,
            reason=RETROSPECTIVE_RESUMABLE_REASON,
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

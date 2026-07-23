from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.orchestrator_state import RunTransitionInput, transition_run
from ledger.review import RecordReviewInput, ReviewResult, record_review

if TYPE_CHECKING:
    import sqlite3

    from ledger.artifact_store import ArtifactStore

MAX_REVIEW_ATTEMPTS = 3


class DeliveryAttemptNotFoundError(ValueError): ...


@dataclass(frozen=True, slots=True)
class ReviewGateInput:
    run_id: str
    review_input: RecordReviewInput
    transition: RunTransitionInput


@dataclass(frozen=True, slots=True)
class ReviewGateOutcome:
    outcome: str
    review_id: str
    run_state: str
    unresolved_blockers: tuple[str, ...] = ()


def _current_run_state(connection: sqlite3.Connection, run_id: str) -> str:
    row = connection.execute('SELECT state FROM RUN WHERE id = ?', (run_id,)).fetchone()
    return row[0]


def _delivery_attempt_head_sha(
    connection: sqlite3.Connection, delivery_attempt_id: str
) -> str:
    row = connection.execute(
        'SELECT head_sha FROM DELIVERY_ATTEMPT WHERE id = ?', (delivery_attempt_id,)
    ).fetchone()
    if row is None:
        raise DeliveryAttemptNotFoundError(delivery_attempt_id)
    return row[0]


def _needs_fixes_review_count(
    connection: sqlite3.Connection, delivery_attempt_id: str
) -> int:
    return connection.execute(
        'SELECT COUNT(*) FROM REVIEW '
        "WHERE delivery_attempt_id = ? AND verdict = 'NEEDS_FIXES'",
        (delivery_attempt_id,),
    ).fetchone()[0]


def _accept_open_findings(
    connection: sqlite3.Connection, review_id: str
) -> tuple[str, ...]:
    connection.execute(
        "UPDATE REVIEW_FINDING SET state = 'accepted' "
        "WHERE review_id = ? AND state = 'open'",
        (review_id,),
    )
    connection.commit()
    rows = connection.execute(
        "SELECT summary FROM REVIEW_FINDING WHERE review_id = ? AND state != 'resolved'",
        (review_id,),
    ).fetchall()
    return tuple(row[0] for row in rows)


def apply_review_result(
    connection: sqlite3.Connection,
    store: ArtifactStore,
    gate_input: ReviewGateInput,
    result: ReviewResult,
) -> ReviewGateOutcome:
    run_id, review_input, transition = (
        gate_input.run_id,
        gate_input.review_input,
        gate_input.transition,
    )
    current_head = _delivery_attempt_head_sha(
        connection, review_input.delivery_attempt_id
    )
    recorded = record_review(connection, store, review_input, result)

    if result.reviewed_sha != current_head:
        return ReviewGateOutcome(
            outcome='stale',
            review_id=recorded.review_id,
            run_state=_current_run_state(connection, run_id),
        )

    if result.verdict == 'GOOD':
        transition_run(connection, run_id, 'MergePending', transition)
        return ReviewGateOutcome(
            outcome='good', review_id=recorded.review_id, run_state='MergePending'
        )

    unresolved = _accept_open_findings(connection, recorded.review_id)
    attempts = _needs_fixes_review_count(connection, review_input.delivery_attempt_id)
    if attempts >= MAX_REVIEW_ATTEMPTS:
        transition_run(
            connection,
            run_id,
            'Failed',
            RunTransitionInput(
                now=transition.now,
                id_factory=transition.id_factory,
                reason=(
                    f'review retry ceiling ({MAX_REVIEW_ATTEMPTS}) exhausted with '
                    f'{len(unresolved)} unresolved finding(s)'
                ),
            ),
        )
        return ReviewGateOutcome(
            outcome='retry_ceiling_exhausted',
            review_id=recorded.review_id,
            run_state='Failed',
            unresolved_blockers=unresolved,
        )

    transition_run(connection, run_id, 'FixesRequired', transition)
    return ReviewGateOutcome(
        outcome='needs_fixes',
        review_id=recorded.review_id,
        run_state='FixesRequired',
        unresolved_blockers=unresolved,
    )

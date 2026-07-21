"""Deterministic review-gate transitions (SPEC.md §20.3, §23 Microtask 21).

Applies one recorded reviewer result to `run_id`'s RUN state: GOOD is honored
only when `reviewed_sha` matches the delivery attempt's exact current head
("GOOD is valid only when reviewed_sha equals PR head and CI head"); a stale
verdict (the head moved after review started) is recorded for audit but never
applied, leaving the run's state untouched -- reconciling a moved head back
onto the state machine is Microtask 22's job (git publisher), not this gate's.
NEEDS_FIXES converts every returned finding into accepted task work and
returns the run to FixesRequired, up to a capped retry ceiling after which the
run fails with its unresolved findings surfaced.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.orchestrator_state import RunTransitionInput, transition_run
from ledger.review import RecordReviewInput, ReviewResult, record_review

if TYPE_CHECKING:
    import sqlite3

    from ledger.artifact_store import ArtifactStore

# SPEC.md §20.3 requires a cap ("Cap retry loops and surface unresolved
# blockers to the user") but gives no specific number; 3 is a conservative,
# adjustable default, not a spec-mandated value.
MAX_REVIEW_ATTEMPTS = 3


class DeliveryAttemptNotFoundError(ValueError):
    """No DELIVERY_ATTEMPT row exists for the requested id."""


@dataclass(frozen=True, slots=True)
class ReviewGateInput:
    """The run, recording, and transition inputs one `apply_review_result` call needs."""

    run_id: str
    review_input: RecordReviewInput
    transition: RunTransitionInput


@dataclass(frozen=True, slots=True)
class ReviewGateOutcome:
    """The result of applying one reviewer verdict to a delivery attempt's gate."""

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
    """Convert every open finding on `review_id` into accepted work, SPEC.md §20.3."""
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
    """Record `result` and apply it to `gate_input.run_id`'s review gate.

    Raises
    ------
    DeliveryAttemptNotFoundError
        No DELIVERY_ATTEMPT row exists for `gate_input.review_input.
        delivery_attempt_id`; checked first, so nothing is recorded for an
        unknown attempt.
    MalformedReviewError
        `result` fails validation or reviewer-identity checks (`ledger.
        review`); propagates before anything is recorded, per SPEC.md §20.3
        ("a malformed result is a failed review, never GOOD").
    """
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
    if attempts > MAX_REVIEW_ATTEMPTS:
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

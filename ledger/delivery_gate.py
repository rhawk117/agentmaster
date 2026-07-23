from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.orchestrator_state import RunTransitionInput, transition_run

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

_GREEN_CONCLUSIONS = frozenset({'success'})


class DeliveryAttemptNotFoundError(ValueError): ...


@dataclass(frozen=True, slots=True)
class CiEvaluation:
    outcome: str
    head_sha: str
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MergeGateResult:
    ready: bool
    head_sha: str
    blocking_reasons: tuple[str, ...]


def _delivery_attempt_head_sha(
    connection: sqlite3.Connection, delivery_attempt_id: str
) -> str:
    row = connection.execute(
        'SELECT head_sha FROM DELIVERY_ATTEMPT WHERE id = ?', (delivery_attempt_id,)
    ).fetchone()
    if row is None:
        raise DeliveryAttemptNotFoundError(delivery_attempt_id)
    return row[0]


_CONCLUSION_REASONS = {
    'skipped': 'skipped but required',
    'cancelled': 'cancelled',
}


def _reason_for_conclusion(name: str, conclusion: str) -> str | None:
    if conclusion in _GREEN_CONCLUSIONS:
        return None
    detail = _CONCLUSION_REASONS.get(conclusion, f'conclusion {conclusion!r}')
    return f'{name}: {detail}'


def _evaluate_one_check(
    connection: sqlite3.Connection,
    delivery_attempt_id: str,
    name: str,
    head_sha: str,
) -> str | None:
    rows = connection.execute(
        'SELECT head_sha, status, conclusion, observed_at FROM CI_CHECK '
        'WHERE delivery_attempt_id = ? AND name = ? ORDER BY observed_at DESC',
        (delivery_attempt_id, name),
    ).fetchall()
    if not rows:
        return f'{name}: pending (never observed)'

    at_head = [row for row in rows if row[0] == head_sha]
    if not at_head:
        return f'{name}: stale (last observed at {rows[0][0]!r}, not at {head_sha!r})'

    completed = [row for row in at_head if row[1] == 'completed']
    if not completed:
        return f'{name}: pending (not yet completed at {head_sha!r})'

    latest_observed_at = max(row[3] for row in completed)
    latest = [row for row in completed if row[3] == latest_observed_at]
    conclusions = {row[2] for row in latest}
    if len(conclusions) > 1:
        return f'{name}: ambiguous conclusions at {head_sha!r}: {sorted(conclusions)}'

    return _reason_for_conclusion(name, conclusions.pop())


def evaluate_ci(
    connection: sqlite3.Connection,
    delivery_attempt_id: str,
    required_checks: Sequence[str],
) -> CiEvaluation:
    head_sha = _delivery_attempt_head_sha(connection, delivery_attempt_id)
    reasons = [
        reason
        for reason in (
            _evaluate_one_check(connection, delivery_attempt_id, name, head_sha)
            for name in required_checks
        )
        if reason is not None
    ]

    def _is_waiting(reason: str) -> bool:
        return 'pending' in reason or 'stale' in reason

    if not reasons:
        outcome = 'green'
    elif all(_is_waiting(reason) for reason in reasons):
        outcome = 'pending'
    else:
        outcome = 'failed'
    return CiEvaluation(
        outcome=outcome, head_sha=head_sha, blocking_reasons=tuple(reasons)
    )


def advance_on_green_ci(
    connection: sqlite3.Connection,
    run_id: str,
    delivery_attempt_id: str,
    required_checks: Sequence[str],
    transition: RunTransitionInput,
) -> CiEvaluation:
    evaluation = evaluate_ci(connection, delivery_attempt_id, required_checks)
    if evaluation.outcome == 'green':
        transition_run(connection, run_id, 'ReviewRequired', transition)
    elif evaluation.outcome == 'failed':
        transition_run(connection, run_id, 'FixesRequired', transition)
    return evaluation


def _latest_review(
    connection: sqlite3.Connection, delivery_attempt_id: str
) -> tuple[str, str] | None:
    row = connection.execute(
        'SELECT reviewed_sha, verdict FROM REVIEW WHERE delivery_attempt_id = ? '
        'ORDER BY created_at DESC LIMIT 1',
        (delivery_attempt_id,),
    ).fetchone()
    return None if row is None else (row[0], row[1])


def evaluate_merge_gate(
    connection: sqlite3.Connection,
    delivery_attempt_id: str,
    required_checks: Sequence[str],
) -> MergeGateResult:
    ci = evaluate_ci(connection, delivery_attempt_id, required_checks)
    reasons = list(ci.blocking_reasons)

    review = _latest_review(connection, delivery_attempt_id)
    if review is None:
        reasons.append('no review recorded for this delivery attempt')
    else:
        reviewed_sha, verdict = review
        if reviewed_sha != ci.head_sha:
            reasons.append(
                f'stale review: reviewed_sha {reviewed_sha!r} != head {ci.head_sha!r}'
            )
        elif verdict != 'GOOD':
            reasons.append(f'review verdict is {verdict!r}, not GOOD')

    return MergeGateResult(
        ready=not reasons, head_sha=ci.head_sha, blocking_reasons=tuple(reasons)
    )

"""Delivery gates: CI evaluation and pre-merge SHA-match enforcement
(SPEC.md §9.1, §19, §20.2, §20.3, §23 Microtask 22).

`evaluate_ci` computes the authoritative status of a delivery attempt's
required checks at its *current* head from recorded CI_CHECK rows only,
rejecting pending, skipped-required, cancelled, stale, and ambiguous
observations (§19: "delivery review-gate verifies PR head SHA, CI head SHA,
reviewed SHA, verdict, unresolved findings, and branch protection status").
An observation recorded against any head other than the attempt's current
`head_sha` is stale by construction -- this is what makes a head advance
during CI polling (`ledger.delivery.update_delivery_attempt_head`) safe: old
green checks for the previous head no longer count.

`advance_on_green_ci` is the deterministic trigger plumbing SPEC.md §20.3
requires: on green it transitions the RUN from CIPending to ReviewRequired --
the transition `agentmaster-execute`'s prose watches for before dispatching
`agentmaster-review` -- and on a hard failure it returns the run to
FixesRequired. A merely pending evaluation leaves run state untouched so a
caller can poll again.

`evaluate_merge_gate` is `delivery merge-gate`'s check: PR head, CI head, and
the latest reviewed SHA must be the exact same commit, with a GOOD verdict,
before a merge may proceed (§20.2: "refuse ... to merge a head different from
the reviewed and green SHA").
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.orchestrator_state import RunTransitionInput, transition_run

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

# GitHub Checks API conclusions that count as a green result.
_GREEN_CONCLUSIONS = frozenset({'success', 'neutral'})


class DeliveryAttemptNotFoundError(ValueError):
    """No DELIVERY_ATTEMPT row exists for the requested id."""


@dataclass(frozen=True, slots=True)
class CiEvaluation:
    """The result of evaluating one delivery attempt's required checks."""

    outcome: str  # 'green' | 'pending' | 'failed'
    head_sha: str
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MergeGateResult:
    """The result of `evaluate_merge_gate`: whether a merge may proceed."""

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


# Non-green conclusions with a reason more specific than the generic fallback.
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
    """Return a blocking reason for check `name`, or `None` if it is green."""
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
    """Evaluate `required_checks` at `delivery_attempt_id`'s current head.

    Raises
    ------
    DeliveryAttemptNotFoundError
        No DELIVERY_ATTEMPT row exists for `delivery_attempt_id`.
    """
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
        # Every blocking reason is still in flight -- wait and poll again.
        outcome = 'pending'
    else:
        # At least one check already has a definitive, non-green result
        # (failed/cancelled/skipped/ambiguous); that always wins over a
        # merely pending sibling check.
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
    """Evaluate CI and, on green, transition `run_id` CIPending -> ReviewRequired.

    A hard failure transitions to FixesRequired; a merely pending evaluation
    leaves the run's state untouched so a caller may poll again.
    """
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
    """Check PR head == CI head == reviewed SHA, with a GOOD verdict, before merge.

    Raises
    ------
    DeliveryAttemptNotFoundError
        No DELIVERY_ATTEMPT row exists for `delivery_attempt_id`.
    """
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

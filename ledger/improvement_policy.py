"""Cross-project memory promotion policy (SPEC.md §17.4, §18, §20.4, §23 M23).

`ledger.memory_service.validate_memory` already enforces §17.4's
session-independence rule for the Candidate->Validated step. This module
covers the step above it: "enforce project activation and cross-project
global promotion thresholds" (§23 M23). `distinct_evidence_project_count`
counts *distinct projects*, not evidence rows, so it is resistant to the
confirmation-bias cases SPEC.md §23 M23 names by construction -- "repeated
same-session evidence" and "correlated runs" both add rows to the same
project's count, never a second one. `evaluate_global_promotion` additionally
refuses a memory with any recorded harm signal, so a cheaper-looking but
lower-quality memory cannot outrun that check on evidence volume alone.

Every decision this module returns is a recommendation: nothing here mutates
MEMORY_SCOPE or MEMORY.state. Promotion still requires the explicit approval
transition `ledger.memory_service.activate_memory`/scope changes perform, and
`record_promotion_evaluation` only records the EVALUATION/EVALUATION_METRIC
worth report the decision rests on (SPEC.md §18: "'Worth' is a report, not a
mutable scalar").
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

_MICROUNITS_PER_UNIT = 1_000_000


class MemoryNotEligibleForGlobalPromotionError(ValueError):
    """`memory_id` does not currently meet SPEC.md §17.4's global promotion bar."""


@dataclass(frozen=True, slots=True)
class PromotionThresholds:
    """Evidence thresholds gating cross-project global promotion (SPEC.md §17.4)."""

    global_promotion_min_distinct_projects: int = 2


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """The outcome of one `evaluate_global_promotion` call."""

    decision: str  # 'eligible' | 'insufficient_evidence' | 'contradicted'
    distinct_evidence_projects: int
    reason: str


def distinct_evidence_project_count(
    connection: sqlite3.Connection, memory_id: str
) -> int:
    """Count the distinct projects `memory_id`'s linked evidence originates from.

    Counts *projects*, not evidence rows or runs: repeated evidence from the
    same session, or from correlated runs in the same project, still counts
    as one project (SPEC.md §23 M23's confirmation-bias cases).
    """
    row = connection.execute(
        'SELECT COUNT(DISTINCT r.project_id) '
        'FROM MEMORY_EVIDENCE me '
        'JOIN EVIDENCE e ON e.id = me.evidence_id '
        'JOIN RUN r ON r.id = e.run_id '
        'WHERE me.memory_id = ?',
        (memory_id,),
    ).fetchone()
    return row[0]


def has_harm_signal(connection: sqlite3.Connection, memory_id: str) -> bool:
    """Return whether `memory_id` carries a recorded harm or contradiction signal.

    True when `MEMORY.harmful_count > 0` or an incoming `'contradicts'`
    MEMORY_LINK targets it -- the same check `evaluate_global_promotion` uses
    to refuse promotion, exposed for the demotion/supersession path (SPEC.md
    §23 M23: "add demotion/supersession paths for harmful or stale
    knowledge"). This function only recommends; callers demote or supersede
    through `ledger.memory_service.reject_memory`/`supersede_memory`.
    """
    row = connection.execute(
        'SELECT harmful_count FROM MEMORY WHERE id = ?', (memory_id,)
    ).fetchone()
    if row is not None and row[0] > 0:
        return True
    (contradiction_count,) = connection.execute(
        'SELECT COUNT(*) FROM MEMORY_LINK WHERE target_memory_id = ? '
        "AND link_kind = 'contradicts'",
        (memory_id,),
    ).fetchone()
    return contradiction_count > 0


def evaluate_global_promotion(
    connection: sqlite3.Connection, memory_id: str, thresholds: PromotionThresholds
) -> PromotionDecision:
    """Decide whether `memory_id` has independent, cross-project evidence for
    global promotion.

    A recorded harm signal (`MEMORY.harmful_count` or an incoming `contradicts`
    MEMORY_LINK) always refuses promotion, regardless of evidence volume.
    """
    if has_harm_signal(connection, memory_id):
        distinct_projects = distinct_evidence_project_count(connection, memory_id)
        return PromotionDecision(
            decision='contradicted',
            distinct_evidence_projects=distinct_projects,
            reason='memory has a recorded harm or contradiction signal',
        )

    distinct_projects = distinct_evidence_project_count(connection, memory_id)
    if distinct_projects < thresholds.global_promotion_min_distinct_projects:
        return PromotionDecision(
            decision='insufficient_evidence',
            distinct_evidence_projects=distinct_projects,
            reason=(
                f'only {distinct_projects} distinct project(s) of evidence, '
                f'need {thresholds.global_promotion_min_distinct_projects}'
            ),
        )
    return PromotionDecision(
        decision='eligible',
        distinct_evidence_projects=distinct_projects,
        reason=(f'{distinct_projects} distinct project(s) of independent evidence'),
    )


@dataclass(frozen=True, slots=True)
class PromotionEvaluationInput:
    """Everything `record_promotion_evaluation` needs beyond the decision itself."""

    memory_id: str
    project_id: str
    evaluator_session_id: str | None
    id_factory: Callable[[], str]
    created_at: str


def record_promotion_evaluation(
    connection: sqlite3.Connection,
    decision: PromotionDecision,
    evaluation_input: PromotionEvaluationInput,
) -> str:
    """Record `decision` as an EVALUATION row with its supporting metric.

    Returns the new EVALUATION row's id.
    """
    evaluation_id = evaluation_input.id_factory()

    def _insert(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT INTO EVALUATION '
            '(id, memory_id, project_id, evaluator_session_id, evaluation_kind, '
            'decision, created_at) '
            "VALUES (?, ?, ?, ?, 'promotion', ?, ?)",
            (
                evaluation_id,
                evaluation_input.memory_id,
                evaluation_input.project_id,
                evaluation_input.evaluator_session_id,
                decision.decision,
                evaluation_input.created_at,
            ),
        )
        conn.execute(
            'INSERT INTO EVALUATION_METRIC '
            '(evaluation_id, metric_name, value_microunits, unit, method) '
            "VALUES (?, 'distinct_evidence_projects', ?, 'count', "
            "'distinct-project-evidence-count')",
            (
                evaluation_id,
                decision.distinct_evidence_projects * _MICROUNITS_PER_UNIT,
            ),
        )

    run_write_transaction(connection, _insert)
    return evaluation_id


def promote_to_global_scope(
    connection: sqlite3.Connection,
    memory_id: str,
    thresholds: PromotionThresholds,
    *,
    created_at: str,
) -> PromotionDecision:
    """Add a global MEMORY_SCOPE row for `memory_id`, once it clears `thresholds`.

    Re-evaluates `evaluate_global_promotion` itself rather than trusting a
    caller-supplied decision, so this mutation can never promote a memory
    whose evidence no longer qualifies by the time it is called (SPEC.md
    §1/§5: no silent self-rewriting). Requires `memory_id` to already be
    `Active` at project scope -- global promotion only ever widens an
    already-approved memory's visibility, never substitutes for that first
    approval.

    Raises
    ------
    MemoryNotEligibleForGlobalPromotionError
        `memory_id` is not `Active`, or its current evidence does not clear
        `thresholds`.
    """
    row = connection.execute(
        'SELECT state FROM MEMORY WHERE id = ?', (memory_id,)
    ).fetchone()
    if row is None or row[0] != 'Active':
        raise MemoryNotEligibleForGlobalPromotionError(
            f'{memory_id}: must be Active at project scope before global promotion'
        )

    decision = evaluate_global_promotion(connection, memory_id, thresholds)
    if decision.decision != 'eligible':
        raise MemoryNotEligibleForGlobalPromotionError(f'{memory_id}: {decision.reason}')

    def _insert(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT INTO MEMORY_SCOPE (memory_id, scope_kind, project_id, created_at) '
            "VALUES (?, 'global', NULL, ?)",
            (memory_id, created_at),
        )

    run_write_transaction(connection, _insert)
    return decision

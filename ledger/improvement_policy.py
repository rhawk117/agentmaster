from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

_MICROUNITS_PER_UNIT = 1_000_000


class MemoryNotEligibleForGlobalPromotionError(ValueError): ...


@dataclass(frozen=True, slots=True)
class PromotionThresholds:
    global_promotion_min_distinct_projects: int = 2


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    decision: str
    distinct_evidence_projects: int
    reason: str


def distinct_evidence_project_count(
    connection: sqlite3.Connection, memory_id: str
) -> int:
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

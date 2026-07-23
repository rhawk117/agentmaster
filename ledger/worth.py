from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

_MICROUNITS_PER_UNIT = 1_000_000
_DESCRIPTIVE_METHOD = 'descriptive, no baseline cohort'


@dataclass(frozen=True, slots=True)
class RunWorthReport:
    run_id: str
    outcome_state: str
    task_count: int
    completed_task_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_micro_usd: int
    unresolved_finding_count: int
    cohort: str
    method: str


def compute_run_worth(
    read_connection: sqlite3.Connection, run_id: str
) -> RunWorthReport | None:
    summary = read_connection.execute(
        'SELECT state, task_count, completed_task_count FROM v_run_summary '
        'WHERE run_id = ?',
        (run_id,),
    ).fetchone()
    if summary is None:
        return None
    state, task_count, completed_task_count = summary

    input_tokens, output_tokens, cost_micro_usd = read_connection.execute(
        'SELECT SUM(input_tokens), SUM(output_tokens), SUM(cost_micro_usd) '
        'FROM v_token_usage_by_model WHERE run_id = ?',
        (run_id,),
    ).fetchone()

    attempt_ids = [
        row[0]
        for row in read_connection.execute(
            'SELECT DISTINCT delivery_attempt_id FROM v_delivery_current_head '
            'WHERE run_id = ?',
            (run_id,),
        ).fetchall()
    ]
    unresolved_finding_count = 0
    if attempt_ids:
        placeholders = ','.join('?' * len(attempt_ids))
        query = (
            'SELECT COUNT(*) FROM v_unresolved_review_findings '  # noqa: S608
            f'WHERE delivery_attempt_id IN ({placeholders})'
        )
        unresolved_finding_count = read_connection.execute(query, attempt_ids).fetchone()[
            0
        ]

    return RunWorthReport(
        run_id=run_id,
        outcome_state=state,
        task_count=task_count,
        completed_task_count=completed_task_count,
        total_input_tokens=input_tokens or 0,
        total_output_tokens=output_tokens or 0,
        total_cost_micro_usd=cost_micro_usd or 0,
        unresolved_finding_count=unresolved_finding_count,
        cohort=f'run {run_id} only',
        method=_DESCRIPTIVE_METHOD,
    )


@dataclass(frozen=True, slots=True)
class MemoryWorthReport:
    memory_id: str
    retrieval_count: int
    helpful_count: int
    harmful_count: int
    cohort: str
    method: str


def compute_memory_worth(
    read_connection: sqlite3.Connection, memory_id: str
) -> MemoryWorthReport:
    retrieval_count, helpful_count, harmful_count = read_connection.execute(
        'SELECT COUNT(*), SUM(CASE WHEN helpful = 1 THEN 1 ELSE 0 END), '
        'SUM(CASE WHEN harmful = 1 THEN 1 ELSE 0 END) '
        'FROM v_memory_retrieval_outcomes WHERE memory_id = ?',
        (memory_id,),
    ).fetchone()
    return MemoryWorthReport(
        memory_id=memory_id,
        retrieval_count=retrieval_count or 0,
        helpful_count=helpful_count or 0,
        harmful_count=harmful_count or 0,
        cohort=f'memory {memory_id} retrievals only',
        method=_DESCRIPTIVE_METHOD,
    )


@dataclass(frozen=True, slots=True)
class ProcedureWorthReport:
    procedure_id: str
    use_count: int
    outcome_counts: dict[str, int]
    cohort: str
    method: str


def compute_procedure_worth(
    read_connection: sqlite3.Connection, procedure_id: str
) -> ProcedureWorthReport:
    rows = read_connection.execute(
        'SELECT outcome, use_count FROM v_procedure_effectiveness WHERE procedure_id = ?',
        (procedure_id,),
    ).fetchall()
    outcome_counts = {
        outcome: count for outcome, count in rows if outcome is not None and count
    }
    return ProcedureWorthReport(
        procedure_id=procedure_id,
        use_count=sum(outcome_counts.values()),
        outcome_counts=outcome_counts,
        cohort=f'procedure {procedure_id} uses only',
        method=_DESCRIPTIVE_METHOD,
    )


@dataclass(frozen=True, slots=True)
class MetricInput:
    metric_name: str
    value: float
    unit: str
    method: str


@dataclass(frozen=True, slots=True)
class EvaluationInput:
    id: str
    project_id: str
    decision: str
    created_at: str
    memory_id: str | None = None
    procedure_version_id: str | None = None
    evaluator_session_id: str | None = None
    evaluation_kind: str = 'worth'


def record_evaluation(
    connection: sqlite3.Connection,
    evaluation: EvaluationInput,
    metrics: Sequence[MetricInput],
) -> str:

    def _insert(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT INTO EVALUATION '
            '(id, memory_id, procedure_version_id, project_id, evaluator_session_id, '
            'evaluation_kind, decision, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                evaluation.id,
                evaluation.memory_id,
                evaluation.procedure_version_id,
                evaluation.project_id,
                evaluation.evaluator_session_id,
                evaluation.evaluation_kind,
                evaluation.decision,
                evaluation.created_at,
            ),
        )
        for metric in metrics:
            conn.execute(
                'INSERT INTO EVALUATION_METRIC '
                '(evaluation_id, metric_name, value_microunits, unit, method) '
                'VALUES (?, ?, ?, ?, ?)',
                (
                    evaluation.id,
                    metric.metric_name,
                    round(metric.value * _MICROUNITS_PER_UNIT),
                    metric.unit,
                    metric.method,
                ),
            )

    run_write_transaction(connection, _insert)
    return evaluation.id

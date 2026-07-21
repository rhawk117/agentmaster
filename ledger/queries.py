"""Read-only ledger query verbs behind `agentmaster ledger query` (SPEC.md §19)."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True, slots=True)
class EntrypointRow:
    """One ENTRYPOINT row (SPEC.md §17.1)."""

    id: str
    kind: str
    name: str
    source_path: str | None
    active: bool
    created_at: str


def query_entrypoints(connection: sqlite3.Connection) -> list[EntrypointRow]:
    """List ENTRYPOINT rows ordered by kind then name.

    Returns an empty list before Microtask 19 seeds any rows (SPEC.md §19:
    "query entrypoints [--json] lists ENTRYPOINT rows... matching the
    sub-verb form of the other query actions").
    """
    rows = connection.execute(
        'SELECT id, kind, name, source_path, active, created_at '
        'FROM ENTRYPOINT ORDER BY kind, name'
    ).fetchall()
    return [
        EntrypointRow(
            id=row[0],
            kind=row[1],
            name=row[2],
            source_path=row[3],
            active=bool(row[4]),
            created_at=row[5],
        )
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class RunSummaryRow:
    """One RUN row summarized via `v_run_summary` (SPEC.md §18, §23 Microtask 17)."""

    run_id: str
    project_id: str
    user_session_id: str
    delivery_mode: str
    state: str
    started_at: str
    ended_at: str | None
    duration_ms: int | None
    task_count: int
    completed_task_count: int


def query_runs(connection: sqlite3.Connection) -> list[RunSummaryRow]:
    """List RUN rows via `v_run_summary`, most recently started first.

    Meaningful now that hook-event ingestion (Microtask 17) records RUN
    rows; before that this always returned an empty list.
    """
    rows = connection.execute(
        'SELECT run_id, project_id, user_session_id, delivery_mode, state, '
        'started_at, ended_at, duration_ms, task_count, completed_task_count '
        'FROM v_run_summary ORDER BY started_at DESC'
    ).fetchall()
    return [RunSummaryRow(*row) for row in rows]


@dataclass(frozen=True, slots=True)
class TokenUsageRow:
    """One run/model token-usage total via `v_token_usage_by_model` (SPEC.md §18)."""

    run_id: str
    model: str
    call_count: int
    input_tokens: int | None
    output_tokens: int | None
    cost_micro_usd: int | None


def query_tokens(
    connection: sqlite3.Connection, *, run_id: str | None = None
) -> list[TokenUsageRow]:
    """List per-run, per-model token totals via `v_token_usage_by_model`.

    Filters to `run_id` when given, else lists every run.
    """
    if run_id is not None:
        rows = connection.execute(
            'SELECT run_id, model, call_count, input_tokens, output_tokens, '
            'cost_micro_usd FROM v_token_usage_by_model WHERE run_id = ? '
            'ORDER BY model',
            (run_id,),
        ).fetchall()
    else:
        rows = connection.execute(
            'SELECT run_id, model, call_count, input_tokens, output_tokens, '
            'cost_micro_usd FROM v_token_usage_by_model ORDER BY run_id, model'
        ).fetchall()
    return [TokenUsageRow(*row) for row in rows]

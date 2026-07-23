from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True, slots=True)
class EntrypointRow:
    id: str
    kind: str
    name: str
    source_path: str | None
    active: bool
    created_at: str


def query_entrypoints(connection: sqlite3.Connection) -> list[EntrypointRow]:
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
    rows = connection.execute(
        'SELECT run_id, project_id, user_session_id, delivery_mode, state, '
        'started_at, ended_at, duration_ms, task_count, completed_task_count '
        'FROM v_run_summary ORDER BY started_at DESC'
    ).fetchall()
    return [RunSummaryRow(*row) for row in rows]


@dataclass(frozen=True, slots=True)
class TokenUsageRow:
    run_id: str
    model: str
    call_count: int
    input_tokens: int | None
    output_tokens: int | None
    cost_micro_usd: int | None


def query_tokens(
    connection: sqlite3.Connection, *, run_id: str | None = None
) -> list[TokenUsageRow]:
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

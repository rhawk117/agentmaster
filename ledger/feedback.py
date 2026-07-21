"""Record FEEDBACK rows for the retrospective feedback-capture flow (SPEC.md §17.2, §19).

SPEC.md §19: "record-feedback writes a FEEDBACK row (§17.2): user_session_id
and run_id are required, task_id and memory_id are optional, and rating is
the tri-state integer described in §17.2." Referenced ids are checked before
the insert so an unknown id raises a clear domain error instead of a raw
`sqlite3.IntegrityError`.

When `feedback.memory_id` names a memory that was actually retrieved during
`feedback.run_id` (it has a `memory_access` row for that run), the rating also
propagates onto that access row's helpful/harmful flags and `MEMORY`'s
usefulness_count/harmful_count (SPEC.md §17.2: rating "map[s] harmful/neutral/
helpful directly onto memory_access's helpful/harmful semantics"). A memory_id
with no matching access row in that run is left untouched: the feedback isn't
about a memory the run actually used.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3

VALID_RATINGS: tuple[int, ...] = (-1, 0, 1)


class UnknownReferenceError(ValueError):
    """A FEEDBACK row named a user_session/run/task/memory id that does not exist."""


@dataclass(frozen=True, slots=True)
class FeedbackInput:
    """Everything needed to insert one FEEDBACK row (SPEC.md §17.2)."""

    id: str
    user_session_id: str
    run_id: str
    rating: int
    created_at: str
    task_id: str | None = None
    memory_id: str | None = None
    comment: str | None = None


def _require_row(
    connection: sqlite3.Connection, *, table: str, id_column: str, value: str
) -> None:
    row = connection.execute(
        f'SELECT 1 FROM {table} WHERE {id_column} = ?',  # noqa: S608
        (value,),
    ).fetchone()
    if row is None:
        raise UnknownReferenceError(f'{table}.{id_column} = {value!r} does not exist')


def _apply_memory_feedback(
    connection: sqlite3.Connection, *, run_id: str, memory_id: str, rating: int
) -> None:
    helpful = 1 if rating == 1 else 0
    harmful = 1 if rating == -1 else 0
    cursor = connection.execute(
        'UPDATE memory_access SET helpful = ?, harmful = ? '
        'WHERE run_id = ? AND memory_id = ?',
        (helpful, harmful, run_id, memory_id),
    )
    if cursor.rowcount <= 0:
        return
    if rating == 1:
        connection.execute(
            'UPDATE MEMORY SET usefulness_count = usefulness_count + 1 WHERE id = ?',
            (memory_id,),
        )
    elif rating == -1:
        connection.execute(
            'UPDATE MEMORY SET harmful_count = harmful_count + 1 WHERE id = ?',
            (memory_id,),
        )


def record_feedback(connection: sqlite3.Connection, feedback: FeedbackInput) -> None:
    """Validate `feedback` and insert its FEEDBACK row.

    Raises
    ------
    ValueError
        `feedback.rating` is not -1, 0, or 1.
    UnknownReferenceError
        `user_session_id`, `run_id`, `task_id`, or `memory_id` names a row
        that does not exist.
    """
    if feedback.rating not in VALID_RATINGS:
        raise ValueError(f'rating must be one of {VALID_RATINGS}, got {feedback.rating}')
    _require_row(
        connection,
        table='USER_SESSION',
        id_column='user_session_id',
        value=feedback.user_session_id,
    )
    _require_row(connection, table='RUN', id_column='id', value=feedback.run_id)
    if feedback.task_id is not None:
        _require_row(connection, table='TASK', id_column='id', value=feedback.task_id)
    if feedback.memory_id is not None:
        _require_row(connection, table='MEMORY', id_column='id', value=feedback.memory_id)

    def _insert(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT INTO FEEDBACK '
            '(id, user_session_id, run_id, task_id, memory_id, rating, comment, '
            'created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                feedback.id,
                feedback.user_session_id,
                feedback.run_id,
                feedback.task_id,
                feedback.memory_id,
                feedback.rating,
                feedback.comment,
                feedback.created_at,
            ),
        )
        if feedback.memory_id is not None:
            _apply_memory_feedback(
                conn,
                run_id=feedback.run_id,
                memory_id=feedback.memory_id,
                rating=feedback.rating,
            )

    run_write_transaction(connection, _insert)

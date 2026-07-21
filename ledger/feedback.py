"""Record FEEDBACK rows for the retrospective feedback-capture flow (SPEC.md §17.2, §19).

SPEC.md §19: "record-feedback writes a FEEDBACK row (§17.2): user_session_id
and run_id are required, task_id and memory_id are optional, and rating is
the tri-state integer described in §17.2." Referenced ids are checked before
the insert so an unknown id raises a clear domain error instead of a raw
`sqlite3.IntegrityError`.
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

    run_write_transaction(connection, _insert)

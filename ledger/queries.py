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

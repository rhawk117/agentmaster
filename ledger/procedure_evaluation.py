from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3


class ProcedureVersionNotFoundError(ValueError): ...


class IllegalProcedureVersionTransitionError(ValueError): ...


@dataclass(frozen=True, slots=True)
class ProcedureVersionInput:
    id: str
    procedure_id: str
    content_hash: str
    artifact_id: str | None = None


def _next_version_no(connection: sqlite3.Connection, procedure_id: str) -> int:
    row = connection.execute(
        'SELECT MAX(version_no) FROM PROCEDURE_VERSION WHERE procedure_id = ?',
        (procedure_id,),
    ).fetchone()
    return (row[0] or 0) + 1


def propose_procedure_version(
    connection: sqlite3.Connection, version: ProcedureVersionInput, *, created_at: str
) -> str:
    version_no = _next_version_no(connection, version.procedure_id)

    def _insert(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT INTO PROCEDURE_VERSION '
            '(id, procedure_id, version_no, content_hash, artifact_id, status, '
            'created_at) '
            "VALUES (?, ?, ?, ?, ?, 'inactive', ?)",
            (
                version.id,
                version.procedure_id,
                version_no,
                version.content_hash,
                version.artifact_id,
                created_at,
            ),
        )

    run_write_transaction(connection, _insert)
    return version.id


def _procedure_id_for_version(
    connection: sqlite3.Connection, procedure_version_id: str
) -> str:
    row = connection.execute(
        'SELECT procedure_id FROM PROCEDURE_VERSION WHERE id = ?',
        (procedure_version_id,),
    ).fetchone()
    if row is None:
        raise ProcedureVersionNotFoundError(procedure_version_id)
    return row[0]


def activate_procedure_version(
    connection: sqlite3.Connection, procedure_version_id: str
) -> None:
    procedure_id = _procedure_id_for_version(connection, procedure_version_id)

    def _activate(conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE PROCEDURE_VERSION SET status = 'inactive' "
            "WHERE procedure_id = ? AND status = 'active'",
            (procedure_id,),
        )
        conn.execute(
            "UPDATE PROCEDURE_VERSION SET status = 'active' WHERE id = ?",
            (procedure_version_id,),
        )

    run_write_transaction(connection, _activate)


def demote_procedure_version(
    connection: sqlite3.Connection, procedure_version_id: str
) -> None:
    row = connection.execute(
        'SELECT status FROM PROCEDURE_VERSION WHERE id = ?', (procedure_version_id,)
    ).fetchone()
    if row is None:
        raise ProcedureVersionNotFoundError(procedure_version_id)
    if row[0] != 'active':
        raise IllegalProcedureVersionTransitionError(
            f'{procedure_version_id}: only an active version can be demoted '
            f'(current status: {row[0]!r})'
        )

    def _demote(conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE PROCEDURE_VERSION SET status = 'inactive' WHERE id = ?",
            (procedure_version_id,),
        )

    run_write_transaction(connection, _demote)

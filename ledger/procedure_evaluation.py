"""Procedure-version proposal, activation, and demotion (SPEC.md §20.4, §23 M23).

"A procedure proposal creates a new inactive PROCEDURE_VERSION; it never edits
the active skill in place. Adoption requires a normal branch, tests, CI,
independent review, and merge" (§20.4). `propose_procedure_version` is only
the ledger side of that first sentence: it never sets a version `'active'`.
`activate_procedure_version` is the typed command the adoption workflow's
merge step calls once that normal branch/CI/review/merge has already
happened -- this module does not decide *when* to call it, matching SPEC.md
§1/§5's "no silent self-rewriting." `demote_procedure_version` is the
"demotion/supersession path for harmful or stale knowledge" §23 M23 also
asks for, symmetric to `ledger.memory_service`'s memory-side transitions.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3


class ProcedureVersionNotFoundError(ValueError):
    """No PROCEDURE_VERSION row exists for the requested id."""


class IllegalProcedureVersionTransitionError(ValueError):
    """The requested PROCEDURE_VERSION status transition is not permitted."""


@dataclass(frozen=True, slots=True)
class ProcedureVersionInput:
    """Everything needed to propose one new, inactive PROCEDURE_VERSION."""

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
    """Create one new, `'inactive'` PROCEDURE_VERSION row for `version.procedure_id`.

    The new row's `version_no` is one past the highest existing version for
    that procedure; it never activates it and never touches any other
    version's status.
    """
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
    """Activate `procedure_version_id`, deactivating any other active version
    of the same procedure.

    Called only after the normal branch/tests/CI/independent-review/merge
    workflow §20.4 requires has already happened; this function performs no
    part of that workflow itself.

    Raises
    ------
    ProcedureVersionNotFoundError
        No PROCEDURE_VERSION row exists for `procedure_version_id`.
    """
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
    """Demote an `'active'` PROCEDURE_VERSION back to `'inactive'`.

    The supersession/demotion path for a procedure version found harmful or
    stale after adoption.

    Raises
    ------
    ProcedureVersionNotFoundError
        No PROCEDURE_VERSION row exists for `procedure_version_id`.
    IllegalProcedureVersionTransitionError
        `procedure_version_id` is not currently `'active'`.
    """
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

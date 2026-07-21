"""Tests for procedure-version proposal/activation/demotion (SPEC.md §20.4, §23 M23)."""

from typing import TYPE_CHECKING

import pytest
from conftest import LEDGER_SEED_CREATED_AT

from ledger.procedure_evaluation import (
    IllegalProcedureVersionTransitionError,
    ProcedureVersionInput,
    ProcedureVersionNotFoundError,
    activate_procedure_version,
    demote_procedure_version,
    propose_procedure_version,
)

if TYPE_CHECKING:
    import sqlite3

_CREATED_AT = LEDGER_SEED_CREATED_AT


def _seed_procedure(
    connection: sqlite3.Connection, *, procedure_id: str = 'procedure-1'
) -> None:
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        'VALUES (?, ?, ?, ?, ?)',
        ('project-1', '/repo', 'fp-project-1', _CREATED_AT, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO PROCEDURE (id, project_id, name, scope, state, created_at) '
        "VALUES (?, 'project-1', 'name', 'skill', 'active', ?)",
        (procedure_id, _CREATED_AT),
    )
    connection.commit()


@pytest.mark.sqlite
def test_propose_procedure_version_starts_at_version_1(ledger_connection):
    _seed_procedure(ledger_connection)

    version_id = propose_procedure_version(
        ledger_connection,
        ProcedureVersionInput(
            id='pv-1', procedure_id='procedure-1', content_hash='hash-1'
        ),
        created_at=_CREATED_AT,
    )

    version_no, status = ledger_connection.execute(
        'SELECT version_no, status FROM PROCEDURE_VERSION WHERE id = ?', (version_id,)
    ).fetchone()
    assert (version_no, status) == (1, 'inactive')


@pytest.mark.sqlite
def test_propose_procedure_version_increments_from_the_latest_version(
    ledger_connection,
):
    _seed_procedure(ledger_connection)
    propose_procedure_version(
        ledger_connection,
        ProcedureVersionInput(
            id='pv-1', procedure_id='procedure-1', content_hash='hash-1'
        ),
        created_at=_CREATED_AT,
    )

    version_id = propose_procedure_version(
        ledger_connection,
        ProcedureVersionInput(
            id='pv-2', procedure_id='procedure-1', content_hash='hash-2'
        ),
        created_at=_CREATED_AT,
    )

    (version_no,) = ledger_connection.execute(
        'SELECT version_no FROM PROCEDURE_VERSION WHERE id = ?', (version_id,)
    ).fetchone()
    assert version_no == 2


@pytest.mark.sqlite
def test_activate_procedure_version_deactivates_the_previous_active_version(
    ledger_connection,
):
    _seed_procedure(ledger_connection)
    first_id = propose_procedure_version(
        ledger_connection,
        ProcedureVersionInput(
            id='pv-1', procedure_id='procedure-1', content_hash='hash-1'
        ),
        created_at=_CREATED_AT,
    )
    activate_procedure_version(ledger_connection, first_id)
    second_id = propose_procedure_version(
        ledger_connection,
        ProcedureVersionInput(
            id='pv-2', procedure_id='procedure-1', content_hash='hash-2'
        ),
        created_at=_CREATED_AT,
    )

    activate_procedure_version(ledger_connection, second_id)

    first_status = ledger_connection.execute(
        'SELECT status FROM PROCEDURE_VERSION WHERE id = ?', (first_id,)
    ).fetchone()[0]
    second_status = ledger_connection.execute(
        'SELECT status FROM PROCEDURE_VERSION WHERE id = ?', (second_id,)
    ).fetchone()[0]
    assert (first_status, second_status) == ('inactive', 'active')


@pytest.mark.sqlite
def test_activate_procedure_version_rejects_an_unknown_version(ledger_connection):
    _seed_procedure(ledger_connection)

    with pytest.raises(ProcedureVersionNotFoundError):
        activate_procedure_version(ledger_connection, 'no-such-version')


@pytest.mark.sqlite
def test_demote_procedure_version_sets_an_active_version_back_to_inactive(
    ledger_connection,
):
    _seed_procedure(ledger_connection)
    version_id = propose_procedure_version(
        ledger_connection,
        ProcedureVersionInput(
            id='pv-1', procedure_id='procedure-1', content_hash='hash-1'
        ),
        created_at=_CREATED_AT,
    )
    activate_procedure_version(ledger_connection, version_id)

    demote_procedure_version(ledger_connection, version_id)

    status = ledger_connection.execute(
        'SELECT status FROM PROCEDURE_VERSION WHERE id = ?', (version_id,)
    ).fetchone()[0]
    assert status == 'inactive'


@pytest.mark.sqlite
def test_demote_procedure_version_rejects_a_version_that_is_not_active(
    ledger_connection,
):
    _seed_procedure(ledger_connection)
    version_id = propose_procedure_version(
        ledger_connection,
        ProcedureVersionInput(
            id='pv-1', procedure_id='procedure-1', content_hash='hash-1'
        ),
        created_at=_CREATED_AT,
    )

    with pytest.raises(IllegalProcedureVersionTransitionError):
        demote_procedure_version(ledger_connection, version_id)

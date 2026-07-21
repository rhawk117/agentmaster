"""Tests for PROJECT identity in the execution schema (SPEC.md §17.1, §17.3)."""

import sqlite3

import pytest

from ledger.connection import connect
from ledger.migrations import migrate

_CREATED_AT = '2026-07-20T00:00:00Z'


@pytest.mark.sqlite
def test_project_fingerprint_is_unique(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        "VALUES ('project-1', '/repo', 'fp-shared', ?, ?)",
        (_CREATED_AT, _CREATED_AT),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO PROJECT '
            '(id, canonical_root, fingerprint, created_at, last_seen_at) '
            "VALUES ('project-2', '/other-repo', 'fp-shared', ?, ?)",
            (_CREATED_AT, _CREATED_AT),
        )
    connection.close()


@pytest.mark.sqlite
def test_a_moved_checkout_relinks_without_a_new_project_row(tmp_path):
    """Root aliasing (§17.3): the same fingerprint keeps the same project id."""
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        "VALUES ('project-1', '/old/checkout', 'fp-1', ?, ?)",
        (_CREATED_AT, _CREATED_AT),
    )
    connection.commit()

    connection.execute(
        "UPDATE PROJECT SET canonical_root = '/new/checkout', last_seen_at = ? "
        "WHERE fingerprint = 'fp-1'",
        (_CREATED_AT,),
    )
    connection.commit()

    row = connection.execute(
        'SELECT id, canonical_root FROM PROJECT WHERE fingerprint = ?', ('fp-1',)
    ).fetchone()

    assert row == ('project-1', '/new/checkout')
    connection.close()


@pytest.mark.sqlite
def test_run_insert_fails_for_an_unknown_project(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        "VALUES ('user-session-1', 'harness-1', ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO RUN '
            '(id, project_id, user_session_id, delivery_mode, state, started_at) '
            "VALUES ('run-1', 'no-such-project', 'user-session-1', "
            "'local', 'Planned', ?)",
            (_CREATED_AT,),
        )
    connection.close()

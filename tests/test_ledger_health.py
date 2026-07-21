"""Tests for the ledger_health record (SPEC.md §16.1)."""

import pytest

from ledger.connection import connect
from ledger.health import read_health, record_health
from ledger.migrations import migrate


@pytest.mark.sqlite
def test_read_health_before_any_record_is_none(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    assert read_health(connection) is None
    connection.close()


@pytest.mark.sqlite
def test_record_health_then_read_health_round_trips(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    record_health(
        connection, journal_mode='WAL', reason='local filesystem and sqlite >= 3.51.3'
    )
    health = read_health(connection)

    assert health is not None
    assert health.journal_mode == 'WAL'
    assert health.reason == 'local filesystem and sqlite >= 3.51.3'
    assert health.sqlite_version
    assert health.checked_at
    connection.close()


@pytest.mark.sqlite
def test_record_health_overwrites_the_singleton_row(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    record_health(connection, journal_mode='WAL', reason='first')
    record_health(connection, journal_mode='DELETE', reason='second')

    rows = connection.execute('SELECT COUNT(*) FROM ledger_health').fetchone()
    assert rows == (1,)
    health = read_health(connection)
    assert health is not None
    assert health.journal_mode == 'DELETE'
    assert health.reason == 'second'
    connection.close()

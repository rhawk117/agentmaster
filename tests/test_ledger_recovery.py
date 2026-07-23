import sqlite3

import pytest

from ledger.cli import cmd_doctor, cmd_init, cmd_migrate
from ledger.connection import connect
from ledger.migrations import Migration, MigrationError, current_version, migrate
from ledger.schema import SUPPORTED_SCHEMA_VERSION
from ledger.transactions import BusyRetriesExhaustedError, run_write_transaction


@pytest.mark.sqlite
def test_migrate_rolls_back_a_failed_migration(tmp_path, monkeypatch):
    def _broken(connection: sqlite3.Connection) -> None:
        connection.execute('CREATE TABLE partial (value TEXT)')
        raise sqlite3.OperationalError('boom')

    fake_migrations = (Migration(to_version=1, description='broken', apply=_broken),)
    monkeypatch.setattr('ledger.migrations.MIGRATIONS', fake_migrations)
    monkeypatch.setattr('ledger.migrations.SUPPORTED_SCHEMA_VERSION', 1)
    connection = connect(tmp_path / 'ledger.sqlite3')

    with pytest.raises(MigrationError, match='boom'):
        migrate(connection)

    assert current_version(connection) == 0
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'partial'"
    ).fetchall()
    assert tables == []
    connection.close()


@pytest.mark.sqlite
def test_migrate_refuses_a_newer_schema_version(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    connection.execute(f'PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION + 1}')
    connection.commit()

    with pytest.raises(MigrationError, match='newer than supported'):
        migrate(connection)

    connection.close()


@pytest.mark.sqlite
def test_migrate_on_a_corrupt_database_fails_closed(tmp_path):
    ledger_path = tmp_path / 'ledger.sqlite3'
    ledger_path.write_bytes(b'not a sqlite database at all, just garbage bytes')
    connection = sqlite3.connect(ledger_path)

    with pytest.raises(MigrationError):
        migrate(connection)

    connection.close()


@pytest.mark.sqlite
def test_cmd_doctor_works_on_a_read_only_ledger_file(tmp_path):
    ledger_path = tmp_path / 'ledger.sqlite3'
    cmd_init(ledger_path)
    ledger_path.chmod(0o400)

    try:
        exit_code = cmd_doctor(ledger_path)
    finally:
        ledger_path.chmod(0o600)

    assert exit_code == 0


@pytest.mark.sqlite
def test_cmd_migrate_on_a_read_only_ledger_fails_closed(tmp_path):
    ledger_path = tmp_path / 'ledger.sqlite3'
    sqlite3.connect(ledger_path).close()
    ledger_path.chmod(0o400)

    try:
        exit_code = cmd_migrate(ledger_path)
    finally:
        ledger_path.chmod(0o600)

    assert exit_code == 1


@pytest.mark.sqlite
def test_run_write_transaction_exhausts_retries_when_perpetually_busy(tmp_path):
    ledger_path = tmp_path / 'ledger.sqlite3'
    locker = connect(ledger_path)
    locker.execute('CREATE TABLE example (value TEXT)')
    locker.commit()
    locker.execute('BEGIN IMMEDIATE')
    locker.execute("INSERT INTO example VALUES ('locked')")

    blocked = sqlite3.connect(ledger_path, timeout=0)

    def _insert(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO example VALUES ('blocked')")

    with pytest.raises(BusyRetriesExhaustedError):
        run_write_transaction(blocked, _insert, max_retries=2, base_backoff_seconds=0.001)

    locker.rollback()
    locker.close()
    blocked.close()

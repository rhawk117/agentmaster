"""Tests for the versioned SQLite migration runner (SPEC.md §16.3)."""

import pytest

from ledger.connection import connect
from ledger.migrations import Migration, migrate
from ledger.schema import SUPPORTED_SCHEMA_VERSION


@pytest.mark.sqlite
def test_migrate_on_a_clean_database_reaches_the_supported_version(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')

    final_version = migrate(connection)

    assert final_version == SUPPORTED_SCHEMA_VERSION
    connection.close()


@pytest.mark.sqlite
def test_migrate_creates_the_ledger_health_table(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')

    migrate(connection)

    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'ledger_health'"
    ).fetchall()
    assert tables == [('ledger_health',)]
    connection.close()


@pytest.mark.sqlite
def test_migrate_is_idempotent_on_a_repeated_call(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    final_version = migrate(connection)  # no raise re-applying an already-created table

    assert final_version == SUPPORTED_SCHEMA_VERSION
    connection.close()


@pytest.mark.sqlite
def test_migrate_applies_pending_migrations_in_order(tmp_path, monkeypatch):
    applied: list[int] = []
    fake_migrations = (
        Migration(
            to_version=1,
            description='first',
            apply=lambda _connection: applied.append(1),
        ),
        Migration(
            to_version=2,
            description='second',
            apply=lambda _connection: applied.append(2),
        ),
    )
    monkeypatch.setattr('ledger.migrations.MIGRATIONS', fake_migrations)
    monkeypatch.setattr('ledger.migrations.SUPPORTED_SCHEMA_VERSION', 2)
    connection = connect(tmp_path / 'ledger.sqlite3')

    final_version = migrate(connection)

    assert applied == [1, 2]
    assert final_version == 2
    connection.close()


@pytest.mark.sqlite
def test_migrate_backs_up_before_a_pending_migration_on_a_non_fresh_database(
    tmp_path, monkeypatch
):
    ledger_path = tmp_path / 'ledger.sqlite3'
    backup_path = tmp_path / 'backup.sqlite3'
    first = Migration(to_version=1, description='first', apply=lambda _connection: None)
    second = Migration(to_version=2, description='second', apply=lambda _connection: None)
    monkeypatch.setattr('ledger.migrations.MIGRATIONS', (first,))
    monkeypatch.setattr('ledger.migrations.SUPPORTED_SCHEMA_VERSION', 1)
    seed_connection = connect(ledger_path)
    migrate(seed_connection)
    assert not backup_path.exists()
    seed_connection.close()
    monkeypatch.undo()

    monkeypatch.setattr('ledger.migrations.MIGRATIONS', (first, second))
    monkeypatch.setattr('ledger.migrations.SUPPORTED_SCHEMA_VERSION', 2)
    connection = connect(ledger_path)
    final_version = migrate(connection, backup_path=backup_path)

    assert final_version == 2
    assert backup_path.exists()
    connection.close()

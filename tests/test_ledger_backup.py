import sqlite3
import stat

import pytest

from ledger.backup import backup_to
from ledger.connection import connect


@pytest.mark.sqlite
def test_backup_to_creates_a_consistent_copy(tmp_path):
    source_path = tmp_path / 'ledger.sqlite3'
    connection = connect(source_path)
    connection.execute('CREATE TABLE example (value TEXT)')
    connection.execute("INSERT INTO example VALUES ('hello')")
    connection.commit()

    destination_path = tmp_path / 'backups' / 'ledger-backup.sqlite3'
    backup_to(connection, destination_path)
    connection.close()

    backup_connection = sqlite3.connect(destination_path)
    try:
        rows = backup_connection.execute('SELECT value FROM example').fetchall()
    finally:
        backup_connection.close()
    assert rows == [('hello',)]


@pytest.mark.sqlite
def test_backup_to_sets_safe_permissions(tmp_path):
    source_path = tmp_path / 'ledger.sqlite3'
    connection = connect(source_path)

    destination_path = tmp_path / 'backups' / 'ledger-backup.sqlite3'
    backup_to(connection, destination_path)
    connection.close()

    assert stat.S_IMODE(destination_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination_path.stat().st_mode) == 0o600


@pytest.mark.sqlite
def test_backup_to_checkpoints_wal_before_copying(tmp_path, monkeypatch):
    monkeypatch.setattr('sqlite3.sqlite_version', '3.51.3')
    monkeypatch.setattr('ledger.connection._is_network_filesystem', lambda _path: False)
    source_path = tmp_path / 'ledger.sqlite3'
    connection = connect(source_path)
    connection.execute('CREATE TABLE example (value TEXT)')
    connection.commit()

    destination_path = tmp_path / 'ledger-backup.sqlite3'
    backup_to(connection, destination_path)

    wal_path = tmp_path / 'ledger.sqlite3-wal'
    assert not wal_path.exists() or wal_path.stat().st_size == 0
    connection.close()

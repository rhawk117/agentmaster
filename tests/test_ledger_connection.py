"""Tests for the standard-library SQLite connection factory (SPEC.md §16.1)."""

import sqlite3

import pytest

from ledger.connection import BUSY_TIMEOUT_MS, connect, select_journal_mode


@pytest.mark.sqlite
def test_connect_enables_foreign_keys(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    try:
        (enabled,) = connection.execute('PRAGMA foreign_keys').fetchone()
        assert enabled == 1
    finally:
        connection.close()


@pytest.mark.sqlite
def test_connect_sets_busy_timeout(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    try:
        (timeout_ms,) = connection.execute('PRAGMA busy_timeout').fetchone()
        assert timeout_ms == BUSY_TIMEOUT_MS
    finally:
        connection.close()


@pytest.mark.sqlite
def test_connect_selects_wal_on_a_safe_local_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite3, 'sqlite_version', '3.51.3')
    monkeypatch.setattr('ledger.connection._is_network_filesystem', lambda _path: False)

    connection = connect(tmp_path / 'ledger.sqlite3')
    try:
        (mode,) = connection.execute('PRAGMA journal_mode').fetchone()
        assert mode.lower() == 'wal'
    finally:
        connection.close()


@pytest.mark.sqlite
def test_connect_falls_back_to_delete_on_an_old_sqlite_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite3, 'sqlite_version', '3.45.0')

    connection = connect(tmp_path / 'ledger.sqlite3')
    try:
        (mode,) = connection.execute('PRAGMA journal_mode').fetchone()
        assert mode.lower() == 'delete'
    finally:
        connection.close()


@pytest.mark.sqlite
def test_connect_falls_back_to_delete_on_a_network_filesystem(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite3, 'sqlite_version', '3.51.3')
    monkeypatch.setattr('ledger.connection._is_network_filesystem', lambda _path: True)

    connection = connect(tmp_path / 'ledger.sqlite3')
    try:
        (mode,) = connection.execute('PRAGMA journal_mode').fetchone()
        assert mode.lower() == 'delete'
    finally:
        connection.close()


def test_select_journal_mode_records_old_sqlite_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite3, 'sqlite_version', '3.45.0')

    decision = select_journal_mode(tmp_path / 'ledger.sqlite3')

    assert decision.mode == 'DELETE'
    assert '3.45.0' in decision.reason


def test_select_journal_mode_records_network_filesystem_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite3, 'sqlite_version', '3.51.3')
    monkeypatch.setattr('ledger.connection._is_network_filesystem', lambda _path: True)

    decision = select_journal_mode(tmp_path / 'ledger.sqlite3')

    assert decision.mode == 'DELETE'
    assert 'network filesystem' in decision.reason


@pytest.mark.sqlite
def test_connect_closes_the_connection_if_pragma_setup_fails(tmp_path, monkeypatch):
    ledger_path = tmp_path / 'ledger.sqlite3'
    captured: list[sqlite3.Connection] = []

    class _FailingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if not captured:
                captured.append(self)
            if sql.startswith('PRAGMA busy_timeout'):
                raise sqlite3.OperationalError('forced failure')
            return super().execute(sql, *args, **kwargs)

    real_connect = sqlite3.connect

    def _connect_with_failing_factory(*args, **kwargs):
        kwargs['factory'] = _FailingConnection
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', _connect_with_failing_factory)

    with pytest.raises(sqlite3.OperationalError, match='forced failure'):
        connect(ledger_path)

    assert len(captured) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
        captured[0].execute('SELECT 1')

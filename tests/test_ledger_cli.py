"""Tests for the ledger init/migrate/backup/doctor commands (SPEC.md §19)."""

import sqlite3
import stat

import pytest

from ledger.cli import cmd_backup, cmd_doctor, cmd_init, cmd_migrate, main
from ledger.migrations import current_version
from ledger.schema import SUPPORTED_SCHEMA_VERSION


@pytest.mark.sqlite
def test_cmd_init_creates_ledger_with_safe_permissions(tmp_path):
    ledger_path = tmp_path / 'agentmaster' / 'ledger.sqlite3'

    exit_code = cmd_init(ledger_path)

    assert exit_code == 0
    assert stat.S_IMODE(ledger_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(ledger_path.stat().st_mode) == 0o600
    connection = sqlite3.connect(ledger_path)
    assert current_version(connection) == SUPPORTED_SCHEMA_VERSION
    connection.close()


@pytest.mark.sqlite
def test_cmd_init_is_idempotent(tmp_path):
    ledger_path = tmp_path / 'ledger.sqlite3'

    assert cmd_init(ledger_path) == 0
    assert cmd_init(ledger_path) == 0  # repeated initialize, no raise

    connection = sqlite3.connect(ledger_path)
    assert current_version(connection) == SUPPORTED_SCHEMA_VERSION
    connection.close()


@pytest.mark.sqlite
def test_cmd_migrate_on_an_uninitialized_path_creates_the_schema(tmp_path):
    ledger_path = tmp_path / 'ledger.sqlite3'
    ledger_path.parent.mkdir(exist_ok=True)
    connection = sqlite3.connect(ledger_path)
    connection.close()

    exit_code = cmd_migrate(ledger_path)

    assert exit_code == 0
    connection = sqlite3.connect(ledger_path)
    assert current_version(connection) == SUPPORTED_SCHEMA_VERSION
    connection.close()


@pytest.mark.sqlite
def test_cmd_backup_writes_a_restorable_copy(tmp_path):
    ledger_path = tmp_path / 'ledger.sqlite3'
    cmd_init(ledger_path)
    destination = tmp_path / 'backup.sqlite3'

    exit_code = cmd_backup(ledger_path, destination)

    assert exit_code == 0
    connection = sqlite3.connect(destination)
    assert current_version(connection) == SUPPORTED_SCHEMA_VERSION
    connection.close()


@pytest.mark.sqlite
def test_cmd_doctor_reports_without_mutating(tmp_path):
    ledger_path = tmp_path / 'ledger.sqlite3'
    cmd_init(ledger_path)
    before = ledger_path.read_bytes()

    exit_code = cmd_doctor(ledger_path)

    assert exit_code == 0
    assert ledger_path.read_bytes() == before


@pytest.mark.sqlite
def test_cmd_doctor_on_a_missing_ledger_fails_without_mutating(tmp_path):
    ledger_path = tmp_path / 'ledger.sqlite3'

    exit_code = cmd_doctor(ledger_path)

    assert exit_code == 1
    assert not ledger_path.exists()


@pytest.mark.sqlite
def test_main_dispatches_init_subcommand(tmp_path):
    ledger_path = tmp_path / 'ledger.sqlite3'

    exit_code = main(['init', '--path', str(ledger_path)])

    assert exit_code == 0
    assert ledger_path.is_file()

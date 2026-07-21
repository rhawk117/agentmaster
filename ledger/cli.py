"""Ledger init/migrate/backup/doctor commands (SPEC.md §19).

A minimal repository script per SPEC.md §19 ("the exact packaging may be
python -m agentmaster ... or a repository script"); a later microtask wires
these into the unified `agentmaster` command entry point.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

from ledger.backup import backup_to
from ledger.connection import connect
from ledger.health import read_health
from ledger.migrations import MigrationError, current_version, migrate
from ledger.schema import SUPPORTED_SCHEMA_VERSION


def cmd_init(ledger_path: Path) -> int:
    """Create the ledger at `ledger_path` and migrate it to the latest schema version."""
    ledger_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        connection = connect(ledger_path)
    except sqlite3.OperationalError as error:
        print(f'ledger init: {error}', file=sys.stderr)
        return 1
    try:
        migrate(connection)
    except MigrationError as error:
        print(f'ledger init: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    ledger_path.chmod(0o600)
    return 0


def cmd_migrate(ledger_path: Path) -> int:
    """Apply any pending migrations to an existing ledger."""
    try:
        connection = connect(ledger_path)
    except sqlite3.OperationalError as error:
        print(f'ledger migrate: {error}', file=sys.stderr)
        return 1
    try:
        migrate(connection)
    except MigrationError as error:
        print(f'ledger migrate: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    return 0


def cmd_backup(ledger_path: Path, destination: Path) -> int:
    """Write a consistent backup of the ledger to `destination`."""
    connection = connect(ledger_path)
    try:
        backup_to(connection, destination)
    finally:
        connection.close()
    return 0


def cmd_doctor(ledger_path: Path) -> int:
    """Report schema version, journaling decision, and integrity without mutating.

    Returns nonzero if the ledger is missing, its integrity check fails, or
    its schema version is newer than this package understands.
    """
    if not ledger_path.exists():
        print(f'{ledger_path}: does not exist', file=sys.stderr)
        return 1
    connection = sqlite3.connect(ledger_path)
    try:
        try:
            version = current_version(connection)
        except MigrationError as error:
            print(f'ledger doctor: {error}', file=sys.stderr)
            return 1
        integrity = connection.execute('PRAGMA integrity_check').fetchone()[0]
        journal_mode = connection.execute('PRAGMA journal_mode').fetchone()[0]
        health = read_health(connection)
    finally:
        connection.close()
    print(f'schema version: {version} (supported: {SUPPORTED_SCHEMA_VERSION})')
    print(f'journal mode: {journal_mode}')
    print(f'integrity check: {integrity}')
    if health is not None:
        print(f'journaling reason: {health.reason}')
    if version < SUPPORTED_SCHEMA_VERSION:
        print(f'pending migrations: {SUPPORTED_SCHEMA_VERSION - version}')
    healthy = integrity == 'ok' and version <= SUPPORTED_SCHEMA_VERSION
    return 0 if healthy else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='ledger')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'migrate', 'doctor'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--path', required=True)
    backup_parser = sub.add_parser('backup')
    backup_parser.add_argument('--path', required=True)
    backup_parser.add_argument('--destination', required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    ledger_path = Path(args.path)
    if args.command == 'init':
        return cmd_init(ledger_path)
    if args.command == 'migrate':
        return cmd_migrate(ledger_path)
    if args.command == 'backup':
        return cmd_backup(ledger_path, Path(args.destination))
    return cmd_doctor(ledger_path)


if __name__ == '__main__':
    sys.exit(main())

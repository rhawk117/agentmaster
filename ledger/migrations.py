import sqlite3
from typing import TYPE_CHECKING

from ledger.backup import backup_to
from ledger.schema import MIGRATIONS, SUPPORTED_SCHEMA_VERSION, Migration

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    'MIGRATIONS',
    'SUPPORTED_SCHEMA_VERSION',
    'Migration',
    'MigrationError',
    'current_version',
    'migrate',
]


class MigrationError(RuntimeError): ...


def current_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute('PRAGMA user_version').fetchone()
    except sqlite3.DatabaseError as error:
        raise MigrationError(f'cannot read schema version: {error}') from error
    return int(row[0])


def migrate(connection: sqlite3.Connection, *, backup_path: Path | None = None) -> int:
    version = current_version(connection)
    if version > SUPPORTED_SCHEMA_VERSION:
        raise MigrationError(
            f'schema version {version} is newer than supported {SUPPORTED_SCHEMA_VERSION}'
        )
    pending = [migration for migration in MIGRATIONS if migration.to_version > version]
    if pending and version > 0 and backup_path is not None:
        backup_to(connection, backup_path)
    for migration in pending:
        _apply(connection, migration)
    return current_version(connection)


def _apply(connection: sqlite3.Connection, migration: Migration) -> None:
    try:
        connection.execute('BEGIN')
        migration.apply(connection)
        connection.execute(f'PRAGMA user_version = {migration.to_version}')
        connection.commit()
    except sqlite3.Error as error:
        connection.rollback()
        raise MigrationError(
            f'migration to version {migration.to_version} ({migration.description}) '
            f'failed: {error}'
        ) from error

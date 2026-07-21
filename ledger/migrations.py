"""Forward-only, transactional, versioned SQLite migrations (SPEC.md §16.3).

Each migration runs in its own transaction and bumps `PRAGMA user_version`
on success; a failure rolls back only that migration, leaving earlier ones
applied. A database reporting a schema version newer than
`SUPPORTED_SCHEMA_VERSION` is refused rather than risk misreading it.

`MIGRATIONS` is discovered from `ledger/migrations/<name>/upgrade.sql`
directories (`ledger/schema.py`), applied in lexicographic directory-name
order, and stamps `user_version` with each migration's numeric ordinal.
Pre-release policy: until v2.0.0 ships, schema changes edit
`ledger/migrations/0001_initial/upgrade.sql` in place; the chain only grows
once v2.0.0 has released.
"""

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


class MigrationError(RuntimeError):
    """The database's schema version is unsupported, or a migration failed."""


def current_version(connection: sqlite3.Connection) -> int:
    """Return the schema version recorded in `PRAGMA user_version`.

    Raises
    ------
    MigrationError
        The database file is unreadable or not a valid SQLite database.
    """
    try:
        row = connection.execute('PRAGMA user_version').fetchone()
    except sqlite3.DatabaseError as error:
        raise MigrationError(f'cannot read schema version: {error}') from error
    return int(row[0])


def migrate(connection: sqlite3.Connection, *, backup_path: Path | None = None) -> int:
    """Apply pending migrations in order and return the resulting version.

    When `backup_path` is given and the database already has data (version
    greater than zero), a consistent backup is written before the first
    pending migration runs (SPEC.md §16: "Back up before migrations that
    transform existing data").

    Raises
    ------
    MigrationError
        The database reports a schema version newer than
        `SUPPORTED_SCHEMA_VERSION`, or a migration raised a SQLite error.
    """
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

"""Ledger schema version and migration metadata (SPEC.md §16.3, §16.4).

Table DDL for later migrations lives with the migration that introduces it,
not here; this module only holds the version number this package understands
and the ordered list of migrations that reach it.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class Migration:
    """One forward-only schema step and the version it produces."""

    to_version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]


def _create_ledger_health(connection: sqlite3.Connection) -> None:
    """Add the singleton table `doctor`/`connect` use to report journaling decisions."""
    connection.execute(
        'CREATE TABLE ledger_health ('
        'id INTEGER PRIMARY KEY CHECK (id = 1), '
        'journal_mode TEXT NOT NULL, '
        'journal_mode_reason TEXT NOT NULL, '
        'sqlite_version TEXT NOT NULL, '
        'checked_at TEXT NOT NULL'
        ')'
    )


SUPPORTED_SCHEMA_VERSION = 1

MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        to_version=1, description='add ledger_health table', apply=_create_ledger_health
    ),
)

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class HealthRecord:
    journal_mode: str
    reason: str
    sqlite_version: str
    checked_at: str


def record_health(
    connection: sqlite3.Connection, *, journal_mode: str, reason: str
) -> None:
    connection.execute(
        'INSERT INTO ledger_health '
        '(id, journal_mode, journal_mode_reason, sqlite_version, checked_at) '
        'VALUES (1, ?, ?, ?, ?) '
        'ON CONFLICT(id) DO UPDATE SET '
        'journal_mode = excluded.journal_mode, '
        'journal_mode_reason = excluded.journal_mode_reason, '
        'sqlite_version = excluded.sqlite_version, '
        'checked_at = excluded.checked_at',
        (journal_mode, reason, sqlite3.sqlite_version, datetime.now(UTC).isoformat()),
    )
    connection.commit()


def read_health(connection: sqlite3.Connection) -> HealthRecord | None:
    row = connection.execute(
        'SELECT journal_mode, journal_mode_reason, sqlite_version, checked_at '
        'FROM ledger_health WHERE id = 1'
    ).fetchone()
    if row is None:
        return None
    return HealthRecord(*row)

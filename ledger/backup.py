"""SQLite online backup API wrapper (SPEC.md §16.1)."""

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def backup_to(source: sqlite3.Connection, destination_path: Path) -> None:
    """Write a consistent copy of `source` to `destination_path`.

    Checkpoints any WAL data into the main database file first, so the
    backup is complete even without copying WAL/SHM sidecar files, then uses
    SQLite's online backup API for a live-safe copy.
    """
    source.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    destination_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
    destination_path.chmod(0o600)

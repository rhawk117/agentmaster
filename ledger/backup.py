import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def backup_to(source: sqlite3.Connection, destination_path: Path) -> None:
    source.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    destination_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
    destination_path.chmod(0o600)

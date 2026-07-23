import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ledger.connection import connect as connect_ledger
from ledger.entrypoint_seed import seed_entrypoints
from ledger.migrations import migrate
from ledger.schema import SUPPORTED_SCHEMA_VERSION

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    'SUPPORTED_SCHEMA_VERSION',
    'LedgerBootstrapError',
    'LedgerBootstrapPlan',
    'bootstrap',
]


class LedgerBootstrapError(ValueError): ...


@dataclass(frozen=True, slots=True)
class LedgerBootstrapPlan:
    ledger_path: Path
    artifact_path: Path


def _schema_version(ledger_path: Path) -> int:
    connection = sqlite3.connect(ledger_path)
    try:
        row = connection.execute('PRAGMA user_version').fetchone()
        return int(row[0])
    finally:
        connection.close()


def _create_ledger(ledger_path: Path) -> None:
    ledger_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = connect_ledger(ledger_path)
    try:
        migrate(connection)
    finally:
        connection.close()
    ledger_path.chmod(0o600)


def _seed_entrypoints(ledger_path: Path) -> None:
    connection = connect_ledger(ledger_path)
    try:
        seed_entrypoints(
            connection,
            id_factory=lambda: str(uuid.uuid4()),
            now=lambda: datetime.now(UTC).isoformat(),
        )
    finally:
        connection.close()


def bootstrap(plan: LedgerBootstrapPlan, *, dry_run: bool) -> None:
    exists = plan.ledger_path.exists()
    if exists:
        version = _schema_version(plan.ledger_path)
        if version > SUPPORTED_SCHEMA_VERSION:
            raise LedgerBootstrapError(
                f'{plan.ledger_path}: schema version {version} is newer than '
                f'supported {SUPPORTED_SCHEMA_VERSION}; refusing to touch it'
            )
    if dry_run:
        return
    if not exists:
        _create_ledger(plan.ledger_path)
    _seed_entrypoints(plan.ledger_path)
    plan.artifact_path.mkdir(mode=0o700, parents=True, exist_ok=True)

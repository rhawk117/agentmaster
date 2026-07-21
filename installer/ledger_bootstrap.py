"""Idempotent ledger bootstrap for the install CLI (SPEC.md §16.1).

`bootstrap` establishes a least-privilege directory layout and the versioned
SQLite schema via `ledger.migrations`, and refuses to touch an existing
database whose schema is newer than this installer understands rather than
risk creating an incompatible one.
"""

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.connection import connect as connect_ledger
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


class LedgerBootstrapError(ValueError):
    """An existing ledger database's schema is newer than this installer understands."""


@dataclass(frozen=True, slots=True)
class LedgerBootstrapPlan:
    """Resolved ledger/artifact paths this bootstrap step will establish."""

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


def bootstrap(plan: LedgerBootstrapPlan, *, dry_run: bool) -> None:
    """Validate, and (unless `dry_run`) create, the ledger and artifact paths.

    Schema compatibility is checked even on a dry run (SPEC.md §11: "Dry-run
    may read and validate the ledger"), but nothing is created until
    `dry_run` is `False`. A second call against an already-bootstrapped,
    compatible database is a no-op.

    Raises
    ------
    LedgerBootstrapError
        The database at `plan.ledger_path` already exists and reports a
        schema version newer than `SUPPORTED_SCHEMA_VERSION`.
    """
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
    plan.artifact_path.mkdir(mode=0o700, parents=True, exist_ok=True)

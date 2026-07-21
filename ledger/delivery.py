"""DELIVERY_ATTEMPT and CI_CHECK recording (SPEC.md §17.1, §20.2, §23 Microtask 22).

The DDL for both tables landed with REVIEW in Microtask 21 (`ledger/
migrations/0001_initial/upgrade.sql`), which explicitly deferred all
ingestion/CLI behavior for them to this microtask. This module only records
rows; `ledger.delivery_gate` reads them back to decide whether CI is green or
a merge may proceed.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True, slots=True)
class DeliveryAttemptInput:
    """Everything needed to insert one DELIVERY_ATTEMPT row (SPEC.md §17.1)."""

    id: str
    run_id: str
    branch: str
    base_sha: str
    head_sha: str
    created_at: str
    pr_number: int | None = None
    pr_url: str | None = None
    state: str = 'open'


@dataclass(frozen=True, slots=True)
class CiCheckInput:
    """Everything needed to insert one CI_CHECK row (SPEC.md §17.1)."""

    id: str
    delivery_attempt_id: str
    name: str
    head_sha: str
    status: str
    observed_at: str
    conclusion: str | None = None
    provider_check_id: str | None = None
    url: str | None = None


def next_attempt_no(connection: sqlite3.Connection, run_id: str) -> int:
    """Return the next 1-based `attempt_no` for `run_id`'s delivery attempts."""
    row = connection.execute(
        'SELECT COALESCE(MAX(attempt_no), 0) FROM DELIVERY_ATTEMPT WHERE run_id = ?',
        (run_id,),
    ).fetchone()
    return row[0] + 1


def record_delivery_attempt(
    connection: sqlite3.Connection, delivery: DeliveryAttemptInput
) -> int:
    """Insert one DELIVERY_ATTEMPT row and return its assigned `attempt_no`."""
    attempt_no = next_attempt_no(connection, delivery.run_id)

    def _insert(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT INTO DELIVERY_ATTEMPT '
            '(id, run_id, attempt_no, branch, base_sha, head_sha, pr_number, pr_url, '
            'state, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                delivery.id,
                delivery.run_id,
                attempt_no,
                delivery.branch,
                delivery.base_sha,
                delivery.head_sha,
                delivery.pr_number,
                delivery.pr_url,
                delivery.state,
                delivery.created_at,
            ),
        )

    run_write_transaction(connection, _insert)
    return attempt_no


def update_delivery_attempt_head(
    connection: sqlite3.Connection, delivery_attempt_id: str, head_sha: str
) -> None:
    """Update a DELIVERY_ATTEMPT's `head_sha` after a new commit lands on the PR.

    Every CI_CHECK/REVIEW row recorded against the old head becomes stale for
    `ledger.delivery_gate` once this runs, since it filters strictly on the
    attempt's current `head_sha`.
    """

    def _update(conn: sqlite3.Connection) -> None:
        conn.execute(
            'UPDATE DELIVERY_ATTEMPT SET head_sha = ? WHERE id = ?',
            (head_sha, delivery_attempt_id),
        )

    run_write_transaction(connection, _update)


def update_delivery_attempt_state(
    connection: sqlite3.Connection,
    delivery_attempt_id: str,
    state: str,
    *,
    completed_at: str | None = None,
) -> None:
    """Update a DELIVERY_ATTEMPT's `state` (and optionally `completed_at`)."""

    def _update(conn: sqlite3.Connection) -> None:
        conn.execute(
            'UPDATE DELIVERY_ATTEMPT '
            'SET state = ?, completed_at = COALESCE(?, completed_at) '
            'WHERE id = ?',
            (state, completed_at, delivery_attempt_id),
        )

    run_write_transaction(connection, _update)


def record_ci_check(connection: sqlite3.Connection, check: CiCheckInput) -> None:
    """Insert one observed CI_CHECK row.

    Raises
    ------
    sqlite3.IntegrityError
        `check.delivery_attempt_id` does not name an existing DELIVERY_ATTEMPT
        row (enforced by the ledger connection's `PRAGMA foreign_keys = ON`).
    """

    def _insert(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT INTO CI_CHECK '
            '(id, delivery_attempt_id, provider_check_id, name, head_sha, status, '
            'conclusion, url, observed_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                check.id,
                check.delivery_attempt_id,
                check.provider_check_id,
                check.name,
                check.head_sha,
                check.status,
                check.conclusion,
                check.url,
                check.observed_at,
            ),
        )

    run_write_transaction(connection, _insert)

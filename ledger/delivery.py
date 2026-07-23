from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True, slots=True)
class DeliveryAttemptInput:
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
    row = connection.execute(
        'SELECT COALESCE(MAX(attempt_no), 0) FROM DELIVERY_ATTEMPT WHERE run_id = ?',
        (run_id,),
    ).fetchone()
    return row[0] + 1


def record_delivery_attempt(
    connection: sqlite3.Connection, delivery: DeliveryAttemptInput
) -> int:
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

    def _update(conn: sqlite3.Connection) -> None:
        conn.execute(
            'UPDATE DELIVERY_ATTEMPT '
            'SET state = ?, completed_at = COALESCE(?, completed_at) '
            'WHERE id = ?',
            (state, completed_at, delivery_attempt_id),
        )

    run_write_transaction(connection, _update)


def record_ci_check(connection: sqlite3.Connection, check: CiCheckInput) -> None:

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

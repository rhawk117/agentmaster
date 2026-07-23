import random
import sqlite3
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

MAX_BUSY_RETRIES = 5
BASE_BACKOFF_SECONDS = 0.05


class BusyRetriesExhaustedError(RuntimeError): ...


def run_write_transaction[T](
    connection: sqlite3.Connection,
    operation: Callable[[sqlite3.Connection], T],
    *,
    max_retries: int = MAX_BUSY_RETRIES,
    base_backoff_seconds: float = BASE_BACKOFF_SECONDS,
) -> T:
    last_error: sqlite3.OperationalError | None = None
    for attempt in range(max_retries):
        try:
            connection.execute('BEGIN IMMEDIATE')
            result = operation(connection)
            connection.commit()
        except sqlite3.OperationalError as error:
            connection.rollback()
            if 'locked' not in str(error).lower() and 'busy' not in str(error).lower():
                raise
            last_error = error
            time.sleep(base_backoff_seconds * (2**attempt) * random.random())  # noqa: S311
            continue
        else:
            return result
    raise BusyRetriesExhaustedError(
        f'write transaction still busy after {max_retries} attempts'
    ) from last_error

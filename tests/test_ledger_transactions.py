import pytest

from ledger.connection import connect
from ledger.transactions import run_write_transaction


@pytest.mark.sqlite
def test_run_write_transaction_commits_on_success(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    connection.execute('CREATE TABLE example (value TEXT)')
    connection.commit()

    def _insert(conn):
        conn.execute("INSERT INTO example VALUES ('hi')")
        return 'ok'

    result = run_write_transaction(connection, _insert)

    assert result == 'ok'
    assert connection.execute('SELECT value FROM example').fetchall() == [('hi',)]
    connection.close()

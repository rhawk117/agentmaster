"""Tests for the execute Stop hook (SPEC.md §20.3, §23 Microtask 21)."""

import pytest

from ledger.connection import connect
from ledger.migrations import migrate
from tests.conftest import SeededRun, seed_project_run_task

pytestmark = pytest.mark.subprocess


def _write_config(tmp_path, ledger_path) -> None:
    am = tmp_path / '.agentmaster'
    am.mkdir(parents=True, exist_ok=True)
    (am / 'config.toml').write_text(
        f'schema_version = 1\n\n[paths]\nledger = "{ledger_path.as_posix()}"\n',
        encoding='utf-8',
    )


def _seed_run_in_state(ledger_path, state: str, *, run_id: str = 'run-1') -> None:
    connection = connect(ledger_path)
    migrate(connection)
    seed_project_run_task(connection, seed=SeededRun(run_id=run_id))
    if state != 'Planned':
        connection.execute('UPDATE RUN SET state = ? WHERE id = ?', (state, run_id))
        connection.commit()
    connection.close()


def _write_run_id_marker(tmp_path, run_id: str, *, session: str = 'default') -> None:
    sdir = tmp_path / '.agentmaster' / 'sessions' / session
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / '.run_id').write_text(run_id, encoding='utf-8')


def test_allows_when_no_run_id_marker(tmp_path, run_hook):
    ledger_path = tmp_path / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, 'ReviewRequired')
    _write_config(tmp_path, ledger_path)

    result = run_hook('execute_stop', {'cwd': str(tmp_path)})

    assert result.returncode == 0


def test_allows_when_ledger_is_missing(tmp_path, run_hook):
    _write_run_id_marker(tmp_path, 'run-1')

    result = run_hook('execute_stop', {'cwd': str(tmp_path)})

    assert result.returncode == 0


def test_allows_when_no_config(tmp_path, run_hook):
    ledger_path = tmp_path / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, 'ReviewRequired')
    _write_run_id_marker(tmp_path, 'run-1')

    result = run_hook('execute_stop', {'cwd': str(tmp_path)})

    assert result.returncode == 0


@pytest.mark.parametrize(
    'state',
    [
        'ReviewRequired',
        'Reviewing',
        'FixesRequired',
        'MergePending',
        'RetrospectivePending',
    ],
)
def test_blocks_while_a_gate_state_is_incomplete(tmp_path, run_hook, state):
    ledger_path = tmp_path / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, state)
    _write_config(tmp_path, ledger_path)
    _write_run_id_marker(tmp_path, 'run-1')

    result = run_hook('execute_stop', {'cwd': str(tmp_path)})

    assert result.returncode == 2
    assert 'run-1' in result.stderr
    assert state in result.stderr


@pytest.mark.parametrize('state', ['Planned', 'Merged', 'Complete', 'Failed'])
def test_allows_when_state_is_not_a_blocking_gate(tmp_path, run_hook, state):
    ledger_path = tmp_path / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, state)
    _write_config(tmp_path, ledger_path)
    _write_run_id_marker(tmp_path, 'run-1')

    result = run_hook('execute_stop', {'cwd': str(tmp_path)})

    assert result.returncode == 0


def test_allows_when_run_id_has_no_matching_run(tmp_path, run_hook):
    ledger_path = tmp_path / 'ledger.sqlite3'
    connection = connect(ledger_path)
    migrate(connection)
    connection.close()
    _write_config(tmp_path, ledger_path)
    _write_run_id_marker(tmp_path, 'no-such-run')

    result = run_hook('execute_stop', {'cwd': str(tmp_path)})

    assert result.returncode == 0


def test_stops_recursively_relaunching_after_the_retry_ceiling(tmp_path, run_hook):
    ledger_path = tmp_path / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, 'ReviewRequired')
    _write_config(tmp_path, ledger_path)
    _write_run_id_marker(tmp_path, 'run-1')

    results = [run_hook('execute_stop', {'cwd': str(tmp_path)}) for _ in range(4)]

    assert [r.returncode for r in results] == [2, 2, 2, 0]
    assert 'not blocking again' in results[-1].stderr


def test_retry_counter_resets_once_the_gate_clears(tmp_path, run_hook):
    ledger_path = tmp_path / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, 'ReviewRequired')
    _write_config(tmp_path, ledger_path)
    _write_run_id_marker(tmp_path, 'run-1')

    blocked = run_hook('execute_stop', {'cwd': str(tmp_path)})
    assert blocked.returncode == 2
    assert (
        tmp_path / '.agentmaster' / 'sessions' / 'default' / '.stop_hook_retries'
    ).is_file()

    connection = connect(ledger_path)
    connection.execute("UPDATE RUN SET state = 'Merged' WHERE id = 'run-1'")
    connection.commit()
    connection.close()

    cleared = run_hook('execute_stop', {'cwd': str(tmp_path)})
    assert cleared.returncode == 0
    assert not (
        tmp_path / '.agentmaster' / 'sessions' / 'default' / '.stop_hook_retries'
    ).is_file()


def test_malformed_json_exits_zero(run_hook):
    result = run_hook('execute_stop', None, raw='not json')
    assert result.returncode == 0

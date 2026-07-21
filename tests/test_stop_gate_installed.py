"""Stop gate reads the installed runtime config, not a fabricated workspace one.

(Scenario 6.)

`hooks/execute_stop.py` resolves the ledger path from
`<workspace>/.agentmaster/config.toml` today (evidence 11) -- a file that
need not exist in a real installed layout, where the canonical config lives
under the agentmaster home (e.g. `<agentmaster-home>/config.toml`), not the
target repo's workspace. Red reason: given a real installed layout with no
workspace `config.toml`, the hook fails open (allows) instead of blocking a
run that is genuinely stuck in a gate state -- because it can't find the
ledger through the workspace-relative path it currently hardcodes.
"""

import pytest

from ledger.connection import connect as connect_ledger
from ledger.migrations import migrate as migrate_ledger
from tests.conftest import SeededRun, seed_project_run_task

pytestmark = pytest.mark.subprocess


def _seed_run_in_state(ledger_path, state: str, *, run_id: str = 'run-1') -> None:
    connection = connect_ledger(ledger_path)
    migrate_ledger(connection)
    seed_project_run_task(connection, seed=SeededRun(run_id=run_id))
    if state != 'Planned':
        connection.execute('UPDATE RUN SET state = ? WHERE id = ?', (state, run_id))
        connection.commit()
    connection.close()


def _write_run_id_marker(workspace, run_id: str, *, session: str = 'default') -> None:
    sdir = workspace / '.agentmaster' / 'sessions' / session
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / '.run_id').write_text(run_id, encoding='utf-8')


def test_stop_gate_blocks_using_the_canonical_installed_config(tmp_path, run_hook):
    """Real installed layout: the canonical config lives under a separate
    agentmaster home, not `<workspace>/.agentmaster/config.toml` -- the
    workspace has no config.toml at all, matching an actual installed
    session. The hook must still find the ledger (via the installed runtime
    descriptor, T2/T5) and block the still-incomplete gate state.
    """
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    agentmaster_home = tmp_path / 'agentmaster-home'
    agentmaster_home.mkdir()
    ledger_path = agentmaster_home / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, 'ReviewRequired')
    _write_run_id_marker(workspace, 'run-1')

    # Deliberately no `<workspace>/.agentmaster/config.toml` -- the canonical
    # config is under `agentmaster_home`, as a real install would have it.
    assert not (workspace / '.agentmaster' / 'config.toml').exists()

    result = run_hook('execute_stop', {'cwd': str(workspace)})

    assert result.returncode == 2, (
        'execute_stop.py resolves config from '
        '`<workspace>/.agentmaster/config.toml` (evidence 11), which does not '
        'exist in a real installed layout, so it fails open '
        f'(returncode={result.returncode}) instead of blocking the still-'
        "incomplete 'ReviewRequired' gate; this goes green once T5 reads the "
        'installed runtime descriptor instead'
    )
    assert 'run-1' in result.stderr

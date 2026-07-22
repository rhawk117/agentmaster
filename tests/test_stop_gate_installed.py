"""Stop gate reads the installed runtime config, not a fabricated workspace one.

(Scenario 6.)

`hooks/execute_stop.py` used to resolve the ledger path from
`<workspace>/.agentmaster/config.toml` (evidence 11) -- a file that need not
exist in a real installed layout, where the canonical config/ledger live
under the agentmaster home, addressed by the installed runtime descriptor
(`hooklib.load_runtime_descriptor`), not the target repo's workspace. This
installs a real Claude target into a disposable home and runs the INSTALLED
`execute_stop.py` (so `runtime.json` sits beside it, per T2's contract),
exactly like `tests/test_ledger_ingestion_e2e.py` does for the telemetry hook.
"""

import pytest

from ledger.connection import connect as connect_ledger
from ledger.migrations import migrate as migrate_ledger
from tests.conftest import SeededRun, seed_project_run_task

pytestmark = pytest.mark.subprocess


def _install_claude(run_cli, repo_root, tmp_path):
    """Install the Claude target into a disposable home, ledger enabled."""
    claude_home = tmp_path / 'claude-home'
    agentmaster_home = tmp_path / 'agentmaster-home'
    result = run_cli(
        [
            'install',
            '--target',
            'claude',
            '--no-input',
            '--agentmaster-home',
            str(agentmaster_home),
        ],
        cwd=repo_root,
        env_extra={'CLAUDE_CONFIG_DIR': str(claude_home)},
    )
    assert result.returncode == 0, result.stderr
    return claude_home, agentmaster_home


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


@pytest.mark.integration
def test_stop_gate_blocks_using_the_canonical_installed_config(
    tmp_path, run_cli, repo_root, installed_hook
):
    """Real installed layout: the canonical config/ledger live under the
    installed agentmaster home, not `<workspace>/.agentmaster/config.toml` --
    the workspace has no config.toml at all, matching an actual installed
    session. The hook must still find the ledger (via the installed runtime
    descriptor, T2/T5) and block the still-incomplete gate state.
    """
    claude_home, agentmaster_home = _install_claude(run_cli, repo_root, tmp_path)
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'execute_stop.py'
    ledger_path = agentmaster_home / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, 'ReviewRequired')

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    _write_run_id_marker(workspace, 'run-1')

    # Deliberately no `<workspace>/.agentmaster/config.toml` -- the canonical
    # config is under `agentmaster_home`, as a real install would have it.
    assert not (workspace / '.agentmaster' / 'config.toml').exists()

    result = installed_hook(hook_path, {'cwd': str(workspace)}, cwd=workspace)

    assert result.returncode == 2, (
        'execute_stop.py must resolve the ledger via the installed runtime '
        f'descriptor beside {hook_path}, not a workspace config.toml, and '
        "block the still-incomplete 'ReviewRequired' gate "
        f'(returncode={result.returncode})'
    )
    assert 'run-1' in result.stderr

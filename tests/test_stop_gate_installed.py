import pytest

from ledger.connection import connect as connect_ledger
from ledger.migrations import migrate as migrate_ledger
from tests.conftest import SeededRun, seed_project_run_task

pytestmark = pytest.mark.subprocess


def _install_claude(run_cli, repo_root, tmp_path):
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
    claude_home, agentmaster_home = _install_claude(run_cli, repo_root, tmp_path)
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'execute_stop.py'
    ledger_path = agentmaster_home / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, 'ReviewRequired')

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    _write_run_id_marker(workspace, 'run-1')

    assert not (workspace / '.agentmaster' / 'config.toml').exists()

    result = installed_hook(hook_path, {'cwd': str(workspace)}, cwd=workspace)

    assert result.returncode == 2, (
        'execute_stop.py must resolve the ledger via the installed runtime '
        f'descriptor beside {hook_path}, not a workspace config.toml, and '
        "block the still-incomplete 'ReviewRequired' gate "
        f'(returncode={result.returncode})'
    )
    assert 'run-1' in result.stderr

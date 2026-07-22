"""Tests for the execute Stop hook (SPEC.md §20.3, §23 Microtask 21).

Runs the INSTALLED `execute_stop.py` (real `install.py` into a disposable
Claude home) so `runtime.json` sits beside it, exactly as a real session
would see it -- the hook resolves the ledger from that installed runtime
descriptor (`hooklib.load_runtime_descriptor`), never from a workspace
`<workspace>/.agentmaster/config.toml` (that path no longer exists).
"""

import pytest

from ledger.connection import connect
from ledger.migrations import migrate
from tests.conftest import SeededRun, seed_project_run_task

pytestmark = pytest.mark.subprocess


def _install_claude(run_cli, repo_root, tmp_path, *, no_ledger: bool = False):
    """Install the Claude target into a disposable home."""
    claude_home = tmp_path / 'claude-home'
    agentmaster_home = tmp_path / 'agentmaster-home'
    args = [
        'install',
        '--target',
        'claude',
        '--no-input',
        '--agentmaster-home',
        str(agentmaster_home),
    ]
    if no_ledger:
        args.append('--no-ledger')
    result = run_cli(
        args, cwd=repo_root, env_extra={'CLAUDE_CONFIG_DIR': str(claude_home)}
    )
    assert result.returncode == 0, result.stderr
    return claude_home, agentmaster_home


def _seed_run_in_state(ledger_path, state: str, *, run_id: str = 'run-1') -> None:
    connection = connect(ledger_path)
    migrate(connection)
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
def test_allows_when_no_run_id_marker(tmp_path, run_cli, repo_root, installed_hook):
    claude_home, agentmaster_home = _install_claude(run_cli, repo_root, tmp_path)
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'execute_stop.py'
    ledger_path = agentmaster_home / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, 'ReviewRequired')

    workspace = tmp_path / 'workspace'
    workspace.mkdir()

    result = installed_hook(hook_path, {'cwd': str(workspace)}, cwd=workspace)

    assert result.returncode == 0


@pytest.mark.integration
def test_allows_when_ledger_is_missing(tmp_path, run_cli, repo_root, installed_hook):
    claude_home, agentmaster_home = _install_claude(run_cli, repo_root, tmp_path)
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'execute_stop.py'
    ledger_path = agentmaster_home / 'ledger.sqlite3'
    # The descriptor still names this path, but the file itself is gone --
    # a corrupted/partially-uninstalled home, not merely a disabled ledger.
    ledger_path.unlink(missing_ok=True)

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    _write_run_id_marker(workspace, 'run-1')

    result = installed_hook(hook_path, {'cwd': str(workspace)}, cwd=workspace)

    assert result.returncode == 0


@pytest.mark.integration
def test_allows_when_ledger_is_disabled(tmp_path, run_cli, repo_root, installed_hook):
    """Replaces the old workspace-`config.toml`-absent case: with the
    workspace config path dropped entirely, a disabled ledger
    (`--no-ledger`) is the fail-open path this now exercises.
    """
    claude_home, _agentmaster_home = _install_claude(
        run_cli, repo_root, tmp_path, no_ledger=True
    )
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'execute_stop.py'

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    _write_run_id_marker(workspace, 'run-1')

    result = installed_hook(hook_path, {'cwd': str(workspace)}, cwd=workspace)

    assert result.returncode == 0


@pytest.mark.integration
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
def test_blocks_while_a_gate_state_is_incomplete(
    tmp_path, run_cli, repo_root, installed_hook, state
):
    claude_home, agentmaster_home = _install_claude(run_cli, repo_root, tmp_path)
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'execute_stop.py'
    ledger_path = agentmaster_home / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, state)

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    _write_run_id_marker(workspace, 'run-1')

    result = installed_hook(hook_path, {'cwd': str(workspace)}, cwd=workspace)

    assert result.returncode == 2
    assert 'run-1' in result.stderr
    assert state in result.stderr


@pytest.mark.integration
@pytest.mark.parametrize('state', ['Planned', 'Merged', 'Complete', 'Failed'])
def test_allows_when_state_is_not_a_blocking_gate(
    tmp_path, run_cli, repo_root, installed_hook, state
):
    claude_home, agentmaster_home = _install_claude(run_cli, repo_root, tmp_path)
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'execute_stop.py'
    ledger_path = agentmaster_home / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, state)

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    _write_run_id_marker(workspace, 'run-1')

    result = installed_hook(hook_path, {'cwd': str(workspace)}, cwd=workspace)

    assert result.returncode == 0


@pytest.mark.integration
def test_allows_when_run_id_has_no_matching_run(
    tmp_path, run_cli, repo_root, installed_hook
):
    claude_home, _agentmaster_home = _install_claude(run_cli, repo_root, tmp_path)
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'execute_stop.py'
    # `install` already bootstraps a migrated, unseeded ledger at this path.

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    _write_run_id_marker(workspace, 'no-such-run')

    result = installed_hook(hook_path, {'cwd': str(workspace)}, cwd=workspace)

    assert result.returncode == 0


@pytest.mark.integration
def test_stops_recursively_relaunching_after_the_retry_ceiling(
    tmp_path, run_cli, repo_root, installed_hook
):
    claude_home, agentmaster_home = _install_claude(run_cli, repo_root, tmp_path)
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'execute_stop.py'
    ledger_path = agentmaster_home / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, 'ReviewRequired')

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    _write_run_id_marker(workspace, 'run-1')

    results = [
        installed_hook(hook_path, {'cwd': str(workspace)}, cwd=workspace)
        for _ in range(4)
    ]

    assert [r.returncode for r in results] == [2, 2, 2, 0]
    assert 'not blocking again' in results[-1].stderr


@pytest.mark.integration
def test_retry_counter_resets_once_the_gate_clears(
    tmp_path, run_cli, repo_root, installed_hook
):
    claude_home, agentmaster_home = _install_claude(run_cli, repo_root, tmp_path)
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'execute_stop.py'
    ledger_path = agentmaster_home / 'ledger.sqlite3'
    _seed_run_in_state(ledger_path, 'ReviewRequired')

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    _write_run_id_marker(workspace, 'run-1')

    blocked = installed_hook(hook_path, {'cwd': str(workspace)}, cwd=workspace)
    assert blocked.returncode == 2
    assert (
        workspace / '.agentmaster' / 'sessions' / 'default' / '.stop_hook_retries'
    ).is_file()

    connection = connect(ledger_path)
    connection.execute("UPDATE RUN SET state = 'Merged' WHERE id = 'run-1'")
    connection.commit()
    connection.close()

    cleared = installed_hook(hook_path, {'cwd': str(workspace)}, cwd=workspace)
    assert cleared.returncode == 0
    assert not (
        workspace / '.agentmaster' / 'sessions' / 'default' / '.stop_hook_retries'
    ).is_file()


def test_malformed_json_exits_zero(run_hook):
    result = run_hook('execute_stop', None, raw='not json')
    assert result.returncode == 0


def _load_execute_stop(hooks_dir):
    """Load `execute_stop.py` in-process (not via subprocess) so its module
    attributes are directly inspectable, matching `tests/test_hooklib.py`'s
    `importlib.util`-based loading convention.
    """
    import importlib.util
    import sys

    sys.path.insert(0, str(hooks_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            'execute_stop', hooks_dir / 'execute_stop.py'
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(hooks_dir))


def test_blocking_states_match_the_orchestrator_source_of_truth(repo_root):
    """Drift guard (SPEC.md §20.3): the standalone hook can't import
    `ledger.orchestrator_state` (it runs copied without the `ledger`
    package), so its hand-duplicated `BLOCKING_STATES` set must be asserted
    identical to `BLOCKING_COMPLETION_STATES`, the orchestrator-side source
    of truth, rather than silently drifting apart.
    """
    from ledger.orchestrator_state import BLOCKING_COMPLETION_STATES

    execute_stop = _load_execute_stop(repo_root / 'hooks')

    assert execute_stop.BLOCKING_STATES == BLOCKING_COMPLETION_STATES

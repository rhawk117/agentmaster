import json
import sqlite3
import subprocess

import pytest

pytestmark = [pytest.mark.subprocess, pytest.mark.integration]

_DESCRIPTOR_FIELDS = {
    'config_path',
    'launcher',
    'ledger_path',
    'ledger_enabled',
    'artifact_dir',
    'schema_version',
}


def _install(run_cli, repo_root, tmp_path, *, extra_args=(), no_ledger=False):
    claude_home = tmp_path / 'claude-home'
    agentmaster_home = tmp_path / 'agentmaster-home'
    args = [
        'install',
        '--target',
        'claude',
        '--no-input',
        '--agentmaster-home',
        str(agentmaster_home),
        *extra_args,
    ]
    if no_ledger:
        args.append('--no-ledger')
    result = run_cli(
        args,
        cwd=repo_root,
        env_extra={'CLAUDE_CONFIG_DIR': str(claude_home)},
    )
    return result, claude_home, agentmaster_home


def test_installed_runtime_emits_descriptor_beside_claude_hooks(
    run_cli, repo_root, tmp_path
):
    result, claude_home, agentmaster_home = _install(run_cli, repo_root, tmp_path)
    assert result.returncode == 0, result.stderr

    descriptor_path = claude_home / 'agentmaster' / 'runtime.json'
    assert descriptor_path.is_file(), (
        'installed runtime must write a descriptor beside the Claude hooks '
        f'at {descriptor_path}, but the installer does not emit one (T2 not '
        'yet implemented)'
    )
    descriptor = json.loads(descriptor_path.read_text(encoding='utf-8'))
    assert descriptor.keys() >= _DESCRIPTOR_FIELDS, (
        f'descriptor missing contract fields: {_DESCRIPTOR_FIELDS - descriptor.keys()}'
    )
    assert descriptor['config_path'] == str(agentmaster_home / 'config.toml')
    assert descriptor['ledger_path'] == str(agentmaster_home / 'ledger.sqlite3')
    assert descriptor['ledger_enabled'] is True
    assert descriptor['schema_version'] == 1
    launcher = descriptor['launcher']
    assert launcher.startswith(str(agentmaster_home)), (
        'launcher must live under <agentmaster-home>/bin/, decoupled from the '
        'source checkout'
    )


def test_no_ledger_produces_a_disabled_descriptor_and_no_db(run_cli, repo_root, tmp_path):
    result, claude_home, agentmaster_home = _install(
        run_cli, repo_root, tmp_path, no_ledger=True
    )
    assert result.returncode == 0, result.stderr

    descriptor_path = claude_home / 'agentmaster' / 'runtime.json'
    assert descriptor_path.is_file(), (
        f'no descriptor written at {descriptor_path} (T2 not yet implemented)'
    )
    descriptor = json.loads(descriptor_path.read_text(encoding='utf-8'))
    assert descriptor['ledger_enabled'] is False
    assert descriptor['ledger_path'] is None
    assert not (agentmaster_home / 'ledger.sqlite3').exists()


def test_installed_launcher_runs_standalone_from_a_separate_repo(
    run_cli, repo_root, tmp_path
):
    result, _claude_home, agentmaster_home = _install(run_cli, repo_root, tmp_path)
    assert result.returncode == 0, result.stderr

    launcher = agentmaster_home / 'bin' / 'agentmaster'
    assert launcher.is_file(), (
        f'no installed launcher at {launcher}; the runtime is not decoupled '
        'from the source checkout (T2 not yet implemented)'
    )

    target_repo = tmp_path / 'separate-target-repo'
    target_repo.mkdir()

    env = {'PATH': '/usr/bin:/bin'}
    proc = subprocess.run(  # noqa: S603
        [
            str(launcher),
            'ledger',
            'doctor',
            '--path',
            str(agentmaster_home / 'ledger.sqlite3'),
        ],
        cwd=str(target_repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, (
        f'installed launcher failed standalone (stdout={proc.stdout!r} '
        f'stderr={proc.stderr!r})'
    )


def test_success_is_judged_by_committed_rows_never_file_size(
    run_cli, repo_root, tmp_path, installed_hook
):
    result, claude_home, agentmaster_home = _install(run_cli, repo_root, tmp_path)
    assert result.returncode == 0, result.stderr

    ledger_path = agentmaster_home / 'ledger.sqlite3'
    assert ledger_path.is_file()

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'telemetry.py'
    hook_result = installed_hook(
        hook_path,
        {
            'cwd': str(workspace),
            'session_id': 'sess-claude-8',
            'hook_event_name': 'SubagentStop',
            'agent_type': 'implementer',
            'agent_id': 'agent-8',
            'agent_model': 'claude-sonnet-5',
            'total_tokens': 900,
        },
        cwd=workspace,
    )
    assert hook_result.returncode == 0, hook_result.stderr

    connection = sqlite3.connect(str(ledger_path))
    try:
        agent_session_count = connection.execute(
            'SELECT COUNT(*) FROM AGENT_SESSION'
        ).fetchone()[0]
    finally:
        connection.close()

    assert agent_session_count > 0, (
        'expected at least one AGENT_SESSION row committed by the installed '
        'runtime, proving success via row visibility rather than file size; '
        'currently nothing auto-drains hook telemetry into the ledger '
        '(evidence 2/12), so no rows exist post-install'
    )

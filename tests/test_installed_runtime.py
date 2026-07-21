"""Installed-runtime independence + the runtime descriptor contract.

Red against v2.0.0 for a structural reason (evidence 12/13 in the ledger
runtime plan), never a crash: the installer bakes a `Path(sys.executable)`
interpreter into hook command strings and never emits a `runtime.json`
descriptor or a `<agentmaster-home>/bin/` launcher, so hooks have no
checkout-independent way to find their config/ledger. These tests assert the
authoritative descriptor contract verbatim (scenario 1, 7) and that success is
judged by row visibility, never file size (scenario 8).
"""

import json
import sqlite3
import subprocess

import pytest

pytestmark = [pytest.mark.subprocess, pytest.mark.integration]

# Fields the "Runtime descriptor contract" section of the plan requires,
# verbatim -- T2 must implement exactly this shape.
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
    """Scenario 1 + 7: the installer must emit `runtime.json` next to the
    installed Claude hooks (`<CLAUDE_CONFIG_DIR>/agentmaster/runtime.json`),
    shaped exactly per the Runtime descriptor contract.
    """
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
    """Scenario 7: `--no-ledger` must set `ledger_enabled=false`,
    `ledger_path=null`, and create no database file -- the disabled-ledger
    invariant.
    """
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
    """Scenario 1: after install, a launcher under `<agentmaster-home>/bin/`
    must be able to initialize/query/ingest against the ledger from a target
    repo that is not the source checkout, with the checkout absent from cwd
    and PYTHONPATH.
    """
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
    run_cli, repo_root, tmp_path
):
    """Scenario 8: assert row visibility after ingestion, explicitly not
    ledger.sqlite3 file-size/`du` growth.
    """
    result, _claude_home, agentmaster_home = _install(run_cli, repo_root, tmp_path)
    assert result.returncode == 0, result.stderr

    ledger_path = agentmaster_home / 'ledger.sqlite3'
    assert ledger_path.is_file()

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

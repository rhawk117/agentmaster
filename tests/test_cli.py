"""CLI subprocess coverage for install.py.

Exercises the installer through a real subprocess so exit codes, argparse
error messages, and stdout/stderr formatting are covered end to end. Parity
tests (generated-file/source equivalence) live in tests/test_parity.py.
"""

import json

import pytest

from installer.parity import validate


@pytest.mark.subprocess
def test_cli_install_dry_run_writes_nothing(tmp_path, run_cli, repo_root):
    claude_home = tmp_path / 'claude-home'
    copilot_home = tmp_path / 'copilot-home'

    result = run_cli(
        ['install', '--target', 'all', '--dry-run', '--no-input'],
        cwd=repo_root,
        env_extra={
            'CLAUDE_CONFIG_DIR': str(claude_home),
            'COPILOT_CONFIG_DIR': str(copilot_home),
        },
    )

    assert result.returncode == 0, result.stderr
    assert 'create' in result.stdout
    assert not claude_home.exists()
    assert not copilot_home.exists()


@pytest.mark.subprocess
def test_cli_validate_clean_exits_zero(run_cli, repo_root):
    result = run_cli(['validate'], cwd=repo_root)

    assert result.returncode == 0, result.stderr


@pytest.mark.subprocess
def test_cli_validate_drift_exits_one(repo_copy, run_cli):
    drifted = repo_copy / 'agents' / 'scout.md'
    drifted.write_text(drifted.read_text(encoding='utf-8') + 'x\n')

    result = run_cli(['validate'], cwd=repo_copy)

    assert result.returncode == 1
    assert 'scout.md' in result.stdout + result.stderr


@pytest.mark.subprocess
def test_cli_sync_is_idempotent_on_clean_tree(repo_copy, run_cli):
    result = run_cli(['sync'], cwd=repo_copy)

    assert result.returncode == 0, result.stderr
    assert validate(repo_copy) == []


@pytest.mark.subprocess
def test_cli_rejects_removed_model_flag(run_cli, repo_root):
    result = run_cli(
        ['install', '--target', 'claude', '--model', 'opus', '--dry-run'],
        cwd=repo_root,
    )

    assert result.returncode != 0
    assert '--claude-model' in (result.stdout + result.stderr)


@pytest.mark.subprocess
def test_cli_rejects_invalid_role_model(run_cli, repo_root):
    result = run_cli(
        ['install', '--target', 'claude', '--claude-model', 'bad model!', '--dry-run'],
        cwd=repo_root,
    )

    assert result.returncode != 0
    assert 'model' in (result.stdout + result.stderr).lower()


@pytest.mark.subprocess
def test_cli_rejects_claude_flag_without_claude_target(run_cli, repo_root):
    result = run_cli(
        [
            'install',
            '--target',
            'copilot',
            '--claude-implementer-model',
            'sonnet',
            '--dry-run',
        ],
        cwd=repo_root,
    )

    assert result.returncode != 0
    assert '--claude-implementer-model' in (result.stdout + result.stderr)


@pytest.mark.subprocess
def test_cli_rejects_auto_compact_percent_without_claude_target(run_cli, repo_root):
    result = run_cli(
        ['install', '--target', 'copilot', '--auto-compact-percent', '50', '--dry-run'],
        cwd=repo_root,
    )

    assert result.returncode != 0
    assert '--auto-compact-percent' in (result.stdout + result.stderr)


@pytest.mark.subprocess
def test_cli_rejects_clear_auto_compact_override_without_claude_target(
    run_cli, repo_root
):
    result = run_cli(
        ['install', '--target', 'copilot', '--clear-auto-compact-override', '--dry-run'],
        cwd=repo_root,
    )

    assert result.returncode != 0
    assert '--clear-auto-compact-override' in (result.stdout + result.stderr)


@pytest.mark.subprocess
def test_cli_rejects_auto_compact_percent_out_of_range(run_cli, repo_root):
    result = run_cli(
        ['install', '--target', 'claude', '--auto-compact-percent', '101', '--dry-run'],
        cwd=repo_root,
    )

    assert result.returncode != 0
    assert 'auto-compact-percent' in (result.stdout + result.stderr)


@pytest.mark.subprocess
def test_cli_install_auto_compact_percent_writes_env_override(
    tmp_path, run_cli, repo_root
):
    result = run_cli(
        [
            'install',
            '--target',
            'claude',
            '--no-input',
            '--auto-compact-percent',
            '50',
            '--agentmaster-home',
            str(tmp_path / 'agentmaster-home'),
        ],
        cwd=repo_root,
        env_extra={'CLAUDE_CONFIG_DIR': str(tmp_path / 'claude-home')},
    )

    assert result.returncode == 0, result.stderr
    settings = json.loads(
        (tmp_path / 'claude-home' / 'settings.json').read_text(encoding='utf-8')
    )
    assert settings['env']['CLAUDE_AUTOCOMPACT_PCT_OVERRIDE'] == '50'


@pytest.mark.subprocess
def test_cli_install_no_input_never_prompts(tmp_path, run_cli, repo_root):
    """--no-input on a would-be-interactive run must not block on stdin."""
    result = run_cli(
        ['install', '--target', 'claude', '--dry-run', '--no-input'],
        cwd=repo_root,
        env_extra={'CLAUDE_CONFIG_DIR': str(tmp_path / 'claude-home')},
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.subprocess
def test_cli_config_rejects_unknown_delivery_mode(tmp_path, run_cli, repo_root):
    config = tmp_path / 'config.toml'
    config.write_text('schema_version = 1\n[orchestration]\ndelivery_mode = "bogus"\n')

    result = run_cli(
        ['install', '--target', 'claude', '--dry-run', '--config', str(config)],
        cwd=repo_root,
    )

    assert result.returncode != 0
    assert 'orchestration.delivery_mode' in result.stdout + result.stderr


@pytest.mark.subprocess
def test_cli_rejects_no_ledger_with_ledger_path(tmp_path, run_cli, repo_root):
    result = run_cli(
        [
            'install',
            '--target',
            'claude',
            '--dry-run',
            '--no-ledger',
            '--ledger-path',
            str(tmp_path / 'ledger.sqlite3'),
        ],
        cwd=repo_root,
    )

    assert result.returncode != 0
    assert 'no-ledger' in (result.stdout + result.stderr)


@pytest.mark.subprocess
def test_cli_install_dry_run_creates_no_ledger(tmp_path, run_cli, repo_root):
    agentmaster_home = tmp_path / 'agentmaster-home'

    result = run_cli(
        [
            'install',
            '--target',
            'claude',
            '--dry-run',
            '--no-input',
            '--agentmaster-home',
            str(agentmaster_home),
        ],
        cwd=repo_root,
        env_extra={'CLAUDE_CONFIG_DIR': str(tmp_path / 'claude-home')},
    )

    assert result.returncode == 0, result.stderr
    assert not agentmaster_home.exists()


@pytest.mark.subprocess
def test_cli_install_no_ledger_creates_no_ledger_file(tmp_path, run_cli, repo_root):
    agentmaster_home = tmp_path / 'agentmaster-home'

    result = run_cli(
        [
            'install',
            '--target',
            'claude',
            '--no-input',
            '--no-ledger',
            '--agentmaster-home',
            str(agentmaster_home),
        ],
        cwd=repo_root,
        env_extra={'CLAUDE_CONFIG_DIR': str(tmp_path / 'claude-home')},
    )

    assert result.returncode == 0, result.stderr
    assert not (agentmaster_home / 'ledger.sqlite3').exists()


@pytest.mark.subprocess
def test_cli_install_ledger_path_and_artifact_dir_are_resolved(
    tmp_path, run_cli, repo_root
):
    agentmaster_home = tmp_path / 'agentmaster-home'
    ledger_path = tmp_path / 'custom-ledger.sqlite3'
    artifact_dir = tmp_path / 'custom-artifacts'

    result = run_cli(
        [
            'install',
            '--target',
            'claude',
            '--no-input',
            '--agentmaster-home',
            str(agentmaster_home),
            '--ledger-path',
            str(ledger_path),
            '--artifact-dir',
            str(artifact_dir),
        ],
        cwd=repo_root,
        env_extra={'CLAUDE_CONFIG_DIR': str(tmp_path / 'claude-home')},
    )

    assert result.returncode == 0, result.stderr
    assert ledger_path.is_file()
    assert artifact_dir.is_dir()
    assert str(ledger_path) in result.stdout
    assert str(artifact_dir) in result.stdout

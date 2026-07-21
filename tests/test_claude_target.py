"""Tests for the Claude Code install target of the Python installer."""

import json
import sys
from pathlib import Path

import pytest

from installer.claude import ClaudeInstallOptions, default_home
from installer.claude import install as _claude_install
from installer.claude import uninstall as _claude_uninstall
from installer.config import (
    AutoCompactOverride,
    ClaudeRoleConfig,
    DeliveryMode,
    Effort,
    RawCapture,
    RedactionMode,
    ResolvedConfig,
    RoleOverride,
    Target,
)
from installer.render import render_worker


def _roles(
    *,
    coordinator: str = 'opus',
    orchestrator: str = 'sonnet',
    orchestrator_effort: Effort = Effort.MEDIUM,
    implementer: str = 'sonnet',
    implementer_effort: Effort = Effort.MEDIUM,
    reviewer: str = 'opus',
    reviewer_effort: Effort = Effort.HIGH,
) -> ClaudeRoleConfig:
    return ClaudeRoleConfig(
        coordinator_model=coordinator,
        orchestrator=RoleOverride(model=orchestrator, effort=orchestrator_effort),
        implementer=RoleOverride(model=implementer, effort=implementer_effort),
        reviewer=RoleOverride(model=reviewer, effort=reviewer_effort),
    )


def _resolved_config(home, agentmaster_home, *, dry_run) -> ResolvedConfig:
    return ResolvedConfig(
        targets=(Target.CLAUDE,),
        dry_run=dry_run,
        no_input=True,
        claude_dir=home,
        copilot_dir=None,
        agentmaster_home=agentmaster_home,
        ledger_path=agentmaster_home / 'ledger.sqlite3',
        artifact_path=agentmaster_home / 'artifacts',
        ledger_enabled=True,
        delivery_mode=DeliveryMode.LOCAL,
        raw_capture=RawCapture.FAILURES,
        redaction=RedactionMode.STANDARD,
    )


def install(
    root,
    home,
    *,
    roles=None,
    dry_run=False,
    manifest=None,
    agentmaster_home=None,
    auto_compact_percent=None,
    clear_auto_compact_override=False,
):
    kwargs = {} if manifest is None else {'manifest': manifest}
    resolved_agentmaster_home = agentmaster_home or (home.parent / 'agentmaster-home')
    options = ClaudeInstallOptions(
        roles=roles or _roles(),
        resolved=_resolved_config(home, resolved_agentmaster_home, dry_run=dry_run),
        auto_compact=AutoCompactOverride(
            auto_compact_percent, clear_auto_compact_override
        ),
        **kwargs,
    )
    return _claude_install(root, home, options)


def uninstall(home, *, dry_run=False, agentmaster_home=None):
    return _claude_uninstall(
        home,
        agentmaster_home=agentmaster_home or (home.parent / 'agentmaster-home'),
        dry_run=dry_run,
    )


def _agentmaster_entry_count(settings: dict) -> int:
    count = 0
    for entries in settings.get('hooks', {}).values():
        for entry in entries:
            if any(
                'agentmaster/hooks' in hook.get('command', '')
                for hook in entry.get('hooks', [])
            ):
                count += 1
    return count


def _read_settings(home: Path) -> dict:
    return json.loads((home / 'settings.json').read_text(encoding='utf-8'))


def test_default_home_honors_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', '/custom/claude')
    assert default_home() == Path('/custom/claude')
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    assert default_home() == Path.home() / '.claude'


def test_fresh_install_writes_everything(tmp_path: Path, repo_root, statuses) -> None:
    home = tmp_path / 'claude-home'

    report = install(repo_root, home, roles=_roles(), dry_run=False)

    assert set(statuses(report.entries)) == {'create'}

    for skill in ('agentmaster-plan', 'agentmaster-execute', 'agentmaster-review'):
        assert (home / 'skills' / skill / 'SKILL.md').is_file()

    for agent in ('scout', 'code-analyst', 'plan-critic', 'implementer', 'explore'):
        assert (home / 'agents' / f'{agent}.md').is_file()

    hooks = (
        'dispatch_guard.py',
        'execute_stop.py',
        'hooklib.py',
        'precompact_snapshot.py',
        'session_context.py',
        'subagent_start.py',
        'telemetry.py',
    )
    for hook in hooks:
        path = home / 'agentmaster' / 'hooks' / hook
        assert path.is_file()
        assert path.stat().st_mode & 0o111

    settings = _read_settings(home)
    assert set(settings['hooks']) == {
        'SubagentStart',
        'SubagentStop',
        'PreToolUse',
        'PreCompact',
        'SessionStart',
        'Stop',
    }


def test_skill_roles_pin_independently(tmp_path: Path, repo_root) -> None:
    home = tmp_path / 'claude-home'
    roles = _roles(
        coordinator='coord-model',
        orchestrator='orch-model',
        orchestrator_effort=Effort.LOW,
        reviewer='review-model',
        reviewer_effort=Effort.XHIGH,
    )

    install(repo_root, home, roles=roles, dry_run=False)

    def _read(skill: str) -> str:
        return (home / 'skills' / skill / 'SKILL.md').read_text(encoding='utf-8')

    def _frontmatter_block(text: str) -> list[str]:
        lines = text.splitlines()
        closing = next(i for i in range(1, len(lines)) if lines[i] == '---')
        return lines[1:closing]

    for skill in ('agentmaster-plan', 'agentmaster-retro'):
        text = _read(skill)
        assert 'model: coord-model\n' in text
        block = _frontmatter_block(text)
        assert not any(line.startswith('effort:') for line in block)

    execute = _read('agentmaster-execute')
    assert 'model: orch-model\n' in execute
    assert 'effort: low\n' in execute

    review = _read('agentmaster-review')
    assert 'model: review-model\n' in review
    assert 'effort: xhigh\n' in review


def test_workers_installed_verbatim(tmp_path: Path, repo_root) -> None:
    home = tmp_path / 'claude-home'
    install(repo_root, home, roles=_roles(), dry_run=False)

    for worker in ('scout', 'implementer'):
        text = (home / 'agents' / f'{worker}.md').read_text(encoding='utf-8')
        assert text == render_worker(worker, 'claude')


def test_cost_boundary_rewritten_in_skills(tmp_path: Path, repo_root) -> None:
    home = tmp_path / 'claude-home'
    install(repo_root, home, roles=_roles(), dry_run=False)

    interpreter = Path(sys.executable).as_posix()
    home_posix = home.resolve().as_posix()
    rewritten = f'"{interpreter}" "{home_posix}/agentmaster/hooks/cost_boundary.py"'
    for skill in ('agentmaster-plan', 'agentmaster-execute', 'agentmaster-review'):
        text = (home / 'skills' / skill / 'SKILL.md').read_text(encoding='utf-8')
        assert rewritten in text
        assert 'python3 "$HOME/.claude/agentmaster/hooks/cost_boundary.py"' not in text


def test_second_install_is_idempotent(tmp_path: Path, repo_root, statuses) -> None:
    home = tmp_path / 'claude-home'
    home.mkdir()
    (home / 'settings.json').write_text(
        json.dumps({
            'hooks': {
                'PreToolUse': [
                    {
                        'matcher': 'Bash',
                        'hooks': [{'type': 'command', 'command': 'echo custom'}],
                    }
                ]
            },
            'keepme': True,
        }),
        encoding='utf-8',
    )

    install(repo_root, home, roles=_roles(), dry_run=False)
    first = _read_settings(home)
    first_count = _agentmaster_entry_count(first)

    report = install(repo_root, home, roles=_roles(), dry_run=False)

    assert 'create' not in statuses(report.entries)
    second = _read_settings(home)
    assert _agentmaster_entry_count(second) == first_count
    assert second['keepme'] is True
    pre_tool = second['hooks']['PreToolUse']
    assert any(
        entry.get('matcher') == 'Bash' and entry['hooks'][0]['command'] == 'echo custom'
        for entry in pre_tool
    )


def test_dry_run_writes_nothing(tmp_path: Path, repo_root) -> None:
    home = tmp_path / 'claude-home'

    report = install(repo_root, home, roles=_roles(), dry_run=True)

    assert report.entries
    assert not home.exists()


def test_uninstall_removes_agentmaster_only(tmp_path: Path, repo_root) -> None:
    home = tmp_path / 'claude-home'
    home.mkdir()
    (home / 'settings.json').write_text(
        json.dumps({
            'hooks': {
                'PreToolUse': [
                    {
                        'matcher': 'Bash',
                        'hooks': [{'type': 'command', 'command': 'echo custom'}],
                    }
                ]
            }
        }),
        encoding='utf-8',
    )

    install(repo_root, home, roles=_roles(), dry_run=False)
    uninstall(home, dry_run=False)

    for skill in ('agentmaster-plan', 'agentmaster-execute', 'agentmaster-review'):
        assert not (home / 'skills' / skill).exists()
    for agent in ('scout', 'code-analyst', 'plan-critic', 'implementer', 'explore'):
        assert not (home / 'agents' / f'{agent}.md').exists()
    assert not (home / 'agentmaster').exists()

    settings = _read_settings(home)
    assert _agentmaster_entry_count(settings) == 0
    pre_tool = settings['hooks']['PreToolUse']
    assert any(entry.get('matcher') == 'Bash' for entry in pre_tool)


def _build_fake_root(root: Path, *, with_hook: bool = True) -> None:
    (root / 'skills' / 'myskill').mkdir(parents=True)
    (root / 'skills' / 'myskill' / 'SKILL.md').write_text('skill\n', encoding='utf-8')
    (root / 'shared' / 'agents').mkdir(parents=True)
    (root / 'shared' / 'agents' / 'scout.md').write_text('body\n', encoding='utf-8')
    if with_hook:
        (root / 'hooks').mkdir(parents=True)
        (root / 'hooks' / 'myhook.py').write_text('hook\n', encoding='utf-8')


def test_fake_manifest_installs_exactly_its_files(tmp_path: Path, make_manifest) -> None:
    root = tmp_path / 'root'
    _build_fake_root(root)
    home = tmp_path / 'home'
    manifest = make_manifest(
        workers=('scout',),
        claude_skills=('myskill',),
        claude_hooks=('myhook.py',),
        claude_frontmatter={'scout': 'name: scout\nmodel: haiku\n'},
    )

    install(root, home, roles=_roles(), dry_run=False, manifest=manifest)

    assert (home / 'skills' / 'myskill' / 'SKILL.md').is_file()
    installed_scout = (home / 'agents' / 'scout.md').read_text(encoding='utf-8')
    assert 'body' in installed_scout  # rendered from the fake root's shared body
    assert (home / 'agentmaster' / 'hooks' / 'myhook.py').is_file()
    assert not (home / 'agents' / 'explore.md').exists()


def test_preflight_missing_source_raises_and_writes_nothing(
    tmp_path: Path, make_manifest
) -> None:
    root = tmp_path / 'root'
    _build_fake_root(root, with_hook=False)
    home = tmp_path / 'home'
    manifest = make_manifest(
        workers=('scout',),
        claude_skills=('myskill',),
        claude_hooks=('myhook.py',),
        claude_frontmatter={'scout': 'name: scout\nmodel: haiku\n'},
    )

    with pytest.raises(FileNotFoundError):
        install(root, home, roles=_roles(), dry_run=False, manifest=manifest)

    assert not home.exists()


def test_install_fails_closed_on_malformed_settings(tmp_path, repo_root):
    home = tmp_path / 'claude-home'
    home.mkdir()
    (home / 'settings.json').write_text('[]\n')

    with pytest.raises(ValueError, match=r'settings\.json'):
        install(repo_root, home, roles=_roles(), dry_run=False)

    assert not (home / 'skills').exists()


def test_install_fails_closed_on_non_object_hooks(tmp_path, repo_root):
    home = tmp_path / 'claude-home'
    home.mkdir()
    (home / 'settings.json').write_text('{"hooks": []}\n')

    with pytest.raises(ValueError, match='hooks'):
        install(repo_root, home, roles=_roles(), dry_run=False)

    assert not (home / 'skills').exists()


def test_install_writes_agentmaster_config_and_owned_state(
    tmp_path: Path, repo_root
) -> None:
    home = tmp_path / 'claude-home'
    agentmaster_home = tmp_path / 'agentmaster-home'
    roles = _roles(orchestrator='orch-model', orchestrator_effort=Effort.LOW)

    install(
        repo_root, home, roles=roles, dry_run=False, agentmaster_home=agentmaster_home
    )

    config_text = (agentmaster_home / 'config.toml').read_text(encoding='utf-8')
    assert 'schema_version = 1' in config_text
    assert 'delivery_mode = "local"' in config_text
    assert 'model = "orch-model"' in config_text
    assert 'effort = "low"' in config_text

    owned_state = json.loads(
        (agentmaster_home / 'owned-state.json').read_text(encoding='utf-8')
    )
    assert 'PreToolUse' in owned_state['targets']['claude']['hooks']


def test_managed_files_participate_in_dry_run_reporting(
    tmp_path: Path, repo_root
) -> None:
    home = tmp_path / 'claude-home'
    agentmaster_home = tmp_path / 'agentmaster-home'

    report = install(repo_root, home, dry_run=True, agentmaster_home=agentmaster_home)

    destinations = {path.name for _, path in report.entries}
    assert {'settings.json', 'config.toml', 'owned-state.json'} <= destinations
    assert not agentmaster_home.exists()


def test_uninstall_preserves_user_edited_hook_entry(tmp_path: Path, repo_root) -> None:
    """The Task 6 fix: editing a managed hook entry protects it from uninstall."""
    home = tmp_path / 'claude-home'
    agentmaster_home = tmp_path / 'agentmaster-home'

    install(repo_root, home, dry_run=False, agentmaster_home=agentmaster_home)
    settings = _read_settings(home)
    owned_entry = next(
        entry
        for entry in settings['hooks']['PreToolUse']
        if 'dispatch_guard.py' in entry['hooks'][0]['command']
    )
    edited_entry = json.loads(json.dumps(owned_entry))
    edited_entry['hooks'][0]['command'] += ' --user-added-flag'
    settings['hooks']['PreToolUse'] = [
        edited_entry if entry is owned_entry else entry
        for entry in settings['hooks']['PreToolUse']
    ]
    (home / 'settings.json').write_text(json.dumps(settings, indent=2), encoding='utf-8')

    uninstall(home, dry_run=False, agentmaster_home=agentmaster_home)

    surviving = _read_settings(home)
    assert edited_entry in surviving['hooks']['PreToolUse']


def test_second_install_owned_state_stays_stable(tmp_path: Path, repo_root) -> None:
    home = tmp_path / 'claude-home'
    agentmaster_home = tmp_path / 'agentmaster-home'

    install(repo_root, home, dry_run=False, agentmaster_home=agentmaster_home)
    first = (agentmaster_home / 'owned-state.json').read_text(encoding='utf-8')

    report = install(repo_root, home, dry_run=False, agentmaster_home=agentmaster_home)
    second = (agentmaster_home / 'owned-state.json').read_text(encoding='utf-8')

    assert first == second
    owned_state_entries = [
        status for status, path in report.entries if path.name == 'owned-state.json'
    ]
    assert owned_state_entries == ['skip']


def test_install_with_auto_compact_percent_writes_env_override(
    tmp_path: Path, repo_root
) -> None:
    home = tmp_path / 'claude-home'

    install(repo_root, home, dry_run=False, auto_compact_percent=50)

    settings = _read_settings(home)
    assert settings['env']['CLAUDE_AUTOCOMPACT_PCT_OVERRIDE'] == '50'


def test_install_without_auto_compact_flags_preserves_existing_env(
    tmp_path: Path, repo_root
) -> None:
    home = tmp_path / 'claude-home'
    home.mkdir()
    (home / 'settings.json').write_text(
        json.dumps({'env': {'CLAUDE_AUTOCOMPACT_PCT_OVERRIDE': 'user-value'}}),
        encoding='utf-8',
    )

    install(repo_root, home, dry_run=False)

    settings = _read_settings(home)
    assert settings['env']['CLAUDE_AUTOCOMPACT_PCT_OVERRIDE'] == 'user-value'


def test_uninstall_restores_original_auto_compact_value(
    tmp_path: Path, repo_root
) -> None:
    home = tmp_path / 'claude-home'
    agentmaster_home = tmp_path / 'agentmaster-home'
    home.mkdir()
    (home / 'settings.json').write_text(
        json.dumps({'env': {'CLAUDE_AUTOCOMPACT_PCT_OVERRIDE': 'pre-existing'}}),
        encoding='utf-8',
    )

    install(
        repo_root,
        home,
        dry_run=False,
        agentmaster_home=agentmaster_home,
        auto_compact_percent=50,
    )
    uninstall(home, dry_run=False, agentmaster_home=agentmaster_home)

    settings = _read_settings(home)
    assert settings['env']['CLAUDE_AUTOCOMPACT_PCT_OVERRIDE'] == 'pre-existing'


def test_uninstall_leaves_user_edited_auto_compact_value_alone(
    tmp_path: Path, repo_root
) -> None:
    home = tmp_path / 'claude-home'
    agentmaster_home = tmp_path / 'agentmaster-home'

    install(
        repo_root,
        home,
        dry_run=False,
        agentmaster_home=agentmaster_home,
        auto_compact_percent=50,
    )
    settings = _read_settings(home)
    settings['env']['CLAUDE_AUTOCOMPACT_PCT_OVERRIDE'] = 'user-changed-it'
    (home / 'settings.json').write_text(json.dumps(settings), encoding='utf-8')

    uninstall(home, dry_run=False, agentmaster_home=agentmaster_home)

    surviving = _read_settings(home)
    assert surviving['env']['CLAUDE_AUTOCOMPACT_PCT_OVERRIDE'] == 'user-changed-it'


def test_install_clear_auto_compact_override_restores_original(
    tmp_path: Path, repo_root
) -> None:
    home = tmp_path / 'claude-home'
    agentmaster_home = tmp_path / 'agentmaster-home'
    home.mkdir()
    (home / 'settings.json').write_text(
        json.dumps({'env': {'CLAUDE_AUTOCOMPACT_PCT_OVERRIDE': 'pre-existing'}}),
        encoding='utf-8',
    )

    install(
        repo_root,
        home,
        dry_run=False,
        agentmaster_home=agentmaster_home,
        auto_compact_percent=50,
    )
    install(
        repo_root,
        home,
        dry_run=False,
        agentmaster_home=agentmaster_home,
        clear_auto_compact_override=True,
    )

    settings = _read_settings(home)
    assert settings['env']['CLAUDE_AUTOCOMPACT_PCT_OVERRIDE'] == 'pre-existing'

"""Tests for the Claude Code install target of the Python installer."""

import json
import sys
from pathlib import Path

import pytest

from installer.claude import default_home, install, uninstall
from installer.render import render_worker


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

    report = install(repo_root, home, model='opus', dry_run=False)

    assert set(statuses(report.entries)) == {'create'}

    for skill in ('agentmaster-plan', 'agentmaster-execute', 'agentmaster-review'):
        assert (home / 'skills' / skill / 'SKILL.md').is_file()

    for agent in ('scout', 'code-analyst', 'plan-critic', 'implementer', 'explore'):
        assert (home / 'agents' / f'{agent}.md').is_file()

    hooks = (
        'dispatch_guard.py',
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
    }


def test_model_pin_only_in_plan_and_review(tmp_path: Path, repo_root) -> None:
    home = tmp_path / 'claude-home'
    install(repo_root, home, model='opus', dry_run=False)

    pin = 'model: opus  # set by install.py'
    for skill in ('agentmaster-plan', 'agentmaster-review', 'agentmaster-retro'):
        text = (home / 'skills' / skill / 'SKILL.md').read_text(encoding='utf-8')
        assert pin in text
    execute = (home / 'skills' / 'agentmaster-execute' / 'SKILL.md').read_text(
        encoding='utf-8'
    )
    assert pin not in execute


def test_workers_installed_verbatim(tmp_path: Path, repo_root) -> None:
    home = tmp_path / 'claude-home'
    install(repo_root, home, model='opus', dry_run=False)

    for worker in ('scout', 'implementer'):
        text = (home / 'agents' / f'{worker}.md').read_text(encoding='utf-8')
        assert text == render_worker(worker, 'claude')


def test_cost_boundary_rewritten_in_skills(tmp_path: Path, repo_root) -> None:
    home = tmp_path / 'claude-home'
    install(repo_root, home, model='opus', dry_run=False)

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

    install(repo_root, home, model='opus', dry_run=False)
    first = _read_settings(home)
    first_count = _agentmaster_entry_count(first)

    report = install(repo_root, home, model='opus', dry_run=False)

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

    report = install(repo_root, home, model='opus', dry_run=True)

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

    install(repo_root, home, model='opus', dry_run=False)
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

    install(root, home, model='opus', dry_run=False, manifest=manifest)

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
        install(root, home, model='opus', dry_run=False, manifest=manifest)

    assert not home.exists()


def test_install_fails_closed_on_malformed_settings(tmp_path, repo_root):
    home = tmp_path / 'claude-home'
    home.mkdir()
    (home / 'settings.json').write_text('[]\n')

    with pytest.raises(ValueError, match=r'settings\.json'):
        install(repo_root, home, model='opus', dry_run=False)

    assert not (home / 'skills').exists()


def test_install_fails_closed_on_non_object_hooks(tmp_path, repo_root):
    home = tmp_path / 'claude-home'
    home.mkdir()
    (home / 'settings.json').write_text('{"hooks": []}\n')

    with pytest.raises(ValueError, match='hooks'):
        install(repo_root, home, model='opus', dry_run=False)

    assert not (home / 'skills').exists()

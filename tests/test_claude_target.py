"""Tests for the Claude Code install target of the Python installer."""

import json
import sys
from pathlib import Path

import pytest

from installer.claude import default_home, install, uninstall
from installer.manifest import Manifest
from installer.render import render_worker

ROOT = Path(__file__).resolve().parent.parent


def _statuses(entries) -> list[str]:
    return [status for status, _ in entries]


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


def test_fresh_install_writes_everything(tmp_path: Path) -> None:
    home = tmp_path / 'claude-home'

    report = install(ROOT, home, model='opus', dry_run=False)

    assert set(_statuses(report.entries)) == {'create'}

    for skill in ('agentmaster-plan', 'agentmaster-execute', 'agentmaster-review'):
        assert (home / 'skills' / skill / 'SKILL.md').is_file()

    for agent in ('scout', 'code-analyst', 'plan-critic', 'implementer', 'explore'):
        assert (home / 'agents' / f'{agent}.md').is_file()

    hooks = (
        'dispatch_guard.py',
        'git_guard.py',
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


def test_model_pin_only_in_plan_and_review(tmp_path: Path) -> None:
    home = tmp_path / 'claude-home'
    install(ROOT, home, model='opus', dry_run=False)

    pin = 'model: opus  # set by install.py'
    for skill in ('agentmaster-plan', 'agentmaster-review'):
        text = (home / 'skills' / skill / 'SKILL.md').read_text(encoding='utf-8')
        assert pin in text
    execute = (home / 'skills' / 'agentmaster-execute' / 'SKILL.md').read_text(
        encoding='utf-8'
    )
    assert pin not in execute


def test_scout_verbatim_implementer_rewritten(tmp_path: Path) -> None:
    home = tmp_path / 'claude-home'
    install(ROOT, home, model='opus', dry_run=False)

    scout = (home / 'agents' / 'scout.md').read_text(encoding='utf-8')
    assert scout == render_worker('scout', 'claude')

    implementer = (home / 'agents' / 'implementer.md').read_text(encoding='utf-8')
    interpreter = Path(sys.executable).as_posix()
    home_posix = home.resolve().as_posix()
    assert interpreter in implementer
    assert f'"{interpreter}" "{home_posix}/agentmaster/hooks/git_guard.py"' in implementer
    assert 'python3 "$HOME/.claude/agentmaster/hooks/git_guard.py"' not in implementer


def test_second_install_is_idempotent(tmp_path: Path) -> None:
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

    install(ROOT, home, model='opus', dry_run=False)
    first = _read_settings(home)
    first_count = _agentmaster_entry_count(first)

    report = install(ROOT, home, model='opus', dry_run=False)

    assert 'create' not in _statuses(report.entries)
    second = _read_settings(home)
    assert _agentmaster_entry_count(second) == first_count
    assert second['keepme'] is True
    pre_tool = second['hooks']['PreToolUse']
    assert any(
        entry.get('matcher') == 'Bash' and entry['hooks'][0]['command'] == 'echo custom'
        for entry in pre_tool
    )


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    home = tmp_path / 'claude-home'

    report = install(ROOT, home, model='opus', dry_run=True)

    assert report.entries
    assert not home.exists()


def test_uninstall_removes_agentmaster_only(tmp_path: Path) -> None:
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

    install(ROOT, home, model='opus', dry_run=False)
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


def _fake_manifest() -> Manifest:
    return Manifest(
        workers=('scout',),
        claude_skills=('myskill',),
        copilot_coordinators=(),
        claude_only_agents=(),
        claude_hooks=('myhook.py',),
        copilot_hooks=(),
        claude_frontmatter={'scout': 'name: scout\nmodel: haiku\n'},
        copilot_frontmatter={},
        substitutions={},
    )


def _build_fake_root(root: Path, *, with_hook: bool = True) -> None:
    (root / 'skills' / 'myskill').mkdir(parents=True)
    (root / 'skills' / 'myskill' / 'SKILL.md').write_text('skill\n', encoding='utf-8')
    (root / 'shared' / 'agents').mkdir(parents=True)
    (root / 'shared' / 'agents' / 'scout.md').write_text('body\n', encoding='utf-8')
    if with_hook:
        (root / 'hooks').mkdir(parents=True)
        (root / 'hooks' / 'myhook.py').write_text('hook\n', encoding='utf-8')


def test_fake_manifest_installs_exactly_its_files(tmp_path: Path) -> None:
    root = tmp_path / 'root'
    _build_fake_root(root)
    home = tmp_path / 'home'
    manifest = _fake_manifest()

    install(root, home, model='opus', dry_run=False, manifest=manifest)

    assert (home / 'skills' / 'myskill' / 'SKILL.md').is_file()
    assert (home / 'agents' / 'scout.md').is_file()
    assert (home / 'agentmaster' / 'hooks' / 'myhook.py').is_file()
    assert not (home / 'agents' / 'explore.md').exists()


def test_preflight_missing_source_raises_and_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / 'root'
    _build_fake_root(root, with_hook=False)
    home = tmp_path / 'home'
    manifest = _fake_manifest()

    with pytest.raises(FileNotFoundError):
        install(root, home, model='opus', dry_run=False, manifest=manifest)

    assert not home.exists()

"""Tests for the GitHub Copilot install target."""

import json
import shlex
from pathlib import Path

import pytest

from installer.copilot import default_home, install, uninstall
from installer.manifest import Manifest

ROOT = Path(__file__).resolve().parent.parent


def _statuses(entries: list) -> list[str]:
    return [status for status, _ in entries]


def _hook_commands(agentmaster_json: Path) -> list[str]:
    config = json.loads(agentmaster_json.read_text(encoding='utf-8'))
    commands: list[str] = []
    for entries in config['hooks'].values():
        commands.extend(entry['bash'] for entry in entries)
    return commands


def _referenced_hook(command: str) -> Path:
    interp, hook_path = shlex.split(command)
    assert interp
    return Path(hook_path)


def test_fresh_install_creates_everything(tmp_path: Path) -> None:
    home = tmp_path / 'copilot-home'

    report = install(ROOT, home, model='opus-test', dry_run=False)

    assert set(_statuses(report.entries)) == {'create'}
    agents = sorted(p.name for p in (home / 'agents').glob('*.agent.md'))
    assert len(agents) == 7
    for skill in ('agentmaster-plan', 'agentmaster-execute', 'agentmaster-review'):
        assert (home / 'skills' / skill / 'SKILL.md').is_file()
    hooks = sorted(p.name for p in (home / 'agentmaster-hooks').iterdir())
    assert len(hooks) == 5
    for hook in (home / 'agentmaster-hooks').iterdir():
        assert hook.stat().st_mode & 0o111

    agentmaster_json = home / 'hooks' / 'agentmaster.json'
    for command in _hook_commands(agentmaster_json):
        assert _referenced_hook(command).is_file()


def test_coordinators_repinned_workers_keep_pins(tmp_path: Path) -> None:
    home = tmp_path / 'copilot-home'

    install(ROOT, home, model='opus-test', dry_run=False)

    for coordinator in ('agentmaster-plan', 'agentmaster-execute', 'agentmaster-review'):
        text = (home / 'agents' / f'{coordinator}.agent.md').read_text(encoding='utf-8')
        assert 'model: opus-test\n' in text
    scout = (home / 'agents' / 'scout.agent.md').read_text(encoding='utf-8')
    assert 'model: claude-haiku-4.5\n' in scout


def test_git_guard_enabled_by_default(tmp_path: Path) -> None:
    home = tmp_path / 'copilot-home'

    install(ROOT, home, model='opus-test', dry_run=False)

    commands = _hook_commands(home / 'hooks' / 'agentmaster.json')
    assert any('git_guard.py' in command for command in commands)


def test_git_guard_disabled_omits_entry(tmp_path: Path) -> None:
    home = tmp_path / 'copilot-home'

    install(ROOT, home, model='opus-test', dry_run=False, git_guard=False)

    config = json.loads((home / 'hooks' / 'agentmaster.json').read_text(encoding='utf-8'))
    assert len(config['hooks']['preToolUse']) == 1
    commands = _hook_commands(home / 'hooks' / 'agentmaster.json')
    assert not any('git_guard.py' in command for command in commands)


def test_idempotent_rerun_creates_nothing(tmp_path: Path) -> None:
    home = tmp_path / 'copilot-home'
    install(ROOT, home, model='opus-test', dry_run=False)

    report = install(ROOT, home, model='opus-test', dry_run=False)

    assert 'create' not in _statuses(report.entries)


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    home = tmp_path / 'copilot-home'

    report = install(ROOT, home, model='opus-test', dry_run=True)

    assert report.entries
    assert not home.exists()


def test_uninstall_removes_ours_and_spares_others(tmp_path: Path) -> None:
    home = tmp_path / 'copilot-home'
    install(ROOT, home, model='opus-test', dry_run=False)
    other = home / 'hooks' / 'other.json'
    other.write_text('{}\n', encoding='utf-8')

    uninstall(home, dry_run=False)

    assert not (home / 'agents').exists() or not any((home / 'agents').iterdir())
    for skill in ('agentmaster-plan', 'agentmaster-execute', 'agentmaster-review'):
        assert not (home / 'skills' / skill).exists()
    assert not (home / 'agentmaster-hooks').exists()
    assert not (home / 'hooks' / 'agentmaster.json').exists()
    assert other.is_file()


def test_default_home_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv('COPILOT_CONFIG_DIR', str(tmp_path / 'custom'))
    assert default_home() == tmp_path / 'custom'
    monkeypatch.delenv('COPILOT_CONFIG_DIR', raising=False)
    assert default_home() == Path.home() / '.copilot'


def _fake_manifest() -> Manifest:
    return Manifest(
        workers=('scout',),
        claude_skills=(),
        copilot_coordinators=('co',),
        claude_only_agents=(),
        claude_hooks=(),
        copilot_hooks=('myhook.py',),
        claude_frontmatter={},
        copilot_frontmatter={'scout': 'name: scout\nmodel: claude-haiku-4.5\n'},
        substitutions={'%USES_RULE%': {'claude': 'x', 'copilot': 'y'}},
    )


def _build_fake_root(root: Path) -> None:
    (root / 'copilot' / 'agents').mkdir(parents=True)
    (root / 'copilot' / 'agents' / 'co.agent.md').write_text(
        '---\nname: co\nmodel: placeholder\n---\nbody\n', encoding='utf-8'
    )
    (root / 'copilot' / 'skills' / 'co').mkdir(parents=True)
    (root / 'copilot' / 'skills' / 'co' / 'SKILL.md').write_text(
        'skill\n', encoding='utf-8'
    )
    (root / 'hooks').mkdir(parents=True)
    (root / 'hooks' / 'myhook.py').write_text('print("hi")\n', encoding='utf-8')
    (root / 'shared' / 'agents').mkdir(parents=True)
    (root / 'shared' / 'agents' / 'scout.md').write_text(
        'shared body\n', encoding='utf-8'
    )


def test_fake_manifest_installs_only_declared(tmp_path: Path) -> None:
    fake_root = tmp_path / 'root'
    _build_fake_root(fake_root)
    home = tmp_path / 'copilot-home'
    manifest = _fake_manifest()

    install(fake_root, home, model='m1', dry_run=False, manifest=manifest)

    assert (home / 'agents' / 'scout.agent.md').is_file()
    assert (home / 'agents' / 'co.agent.md').is_file()
    assert sorted(p.name for p in (home / 'agents').iterdir()) == [
        'co.agent.md',
        'scout.agent.md',
    ]
    coordinator = (home / 'agents' / 'co.agent.md').read_text(encoding='utf-8')
    assert 'model: m1\n' in coordinator
    assert (home / 'skills' / 'co' / 'SKILL.md').is_file()
    assert sorted(p.name for p in (home / 'agentmaster-hooks').iterdir()) == ['myhook.py']


def test_preflight_missing_source_raises_and_writes_nothing(tmp_path: Path) -> None:
    fake_root = tmp_path / 'root'
    _build_fake_root(fake_root)
    (fake_root / 'copilot' / 'agents' / 'co.agent.md').unlink()
    home = tmp_path / 'copilot-home'
    manifest = _fake_manifest()

    with pytest.raises(FileNotFoundError):
        install(fake_root, home, model='m1', dry_run=False, manifest=manifest)

    assert not home.exists()

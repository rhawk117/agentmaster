import json
import shlex
from pathlib import Path

import pytest

from installer.config import CopilotRoleConfig
from installer.copilot import CopilotInstallOptions, default_home
from installer.copilot import install as _copilot_install
from installer.copilot import uninstall as _copilot_uninstall


def _roles(
    *, coordinator: str = 'opus-test', implementer: str = 'claude-sonnet-4.6'
) -> CopilotRoleConfig:
    return CopilotRoleConfig(coordinator_model=coordinator, implementer_model=implementer)


def install(
    root,
    home,
    *,
    roles=None,
    dry_run=False,
    manifest=None,
    agentmaster_home=None,
):
    kwargs = {} if manifest is None else {'manifest': manifest}
    resolved_agentmaster_home = agentmaster_home or (home.parent / 'agentmaster-home')
    options = CopilotInstallOptions(
        roles=roles or _roles(),
        agentmaster_home=resolved_agentmaster_home,
        ledger_path=resolved_agentmaster_home / 'ledger.sqlite3',
        ledger_enabled=True,
        artifact_path=resolved_agentmaster_home / 'artifacts',
        dry_run=dry_run,
        **kwargs,
    )
    return _copilot_install(root, home, options)


def uninstall(home, *, dry_run=False, agentmaster_home=None):
    return _copilot_uninstall(
        home,
        agentmaster_home=agentmaster_home or (home.parent / 'agentmaster-home'),
        dry_run=dry_run,
    )


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


def test_fresh_install_creates_everything(tmp_path: Path, repo_root, statuses) -> None:
    home = tmp_path / 'copilot-home'

    report = install(repo_root, home, roles=_roles(), dry_run=False)

    assert set(statuses(report.entries)) == {'create'}
    agents = sorted(p.name for p in (home / 'agents').glob('*.agent.md'))
    assert len(agents) == 9
    for skill in (
        'agentmaster-plan',
        'agentmaster-execute',
        'agentmaster-review',
        'agentmaster-retro',
    ):
        assert (home / 'skills' / skill / 'SKILL.md').is_file()
    hook_files = [p for p in (home / 'agentmaster-hooks').iterdir() if p.suffix == '.py']
    assert len(hook_files) == 4
    for hook in hook_files:
        assert hook.stat().st_mode & 0o111
    assert (home / 'agentmaster-hooks' / 'runtime.json').is_file()

    agentmaster_json = home / 'hooks' / 'agentmaster.json'
    for command in _hook_commands(agentmaster_json):
        assert _referenced_hook(command).is_file()


def test_coordinators_repinned_workers_keep_pins(tmp_path: Path, repo_root) -> None:
    home = tmp_path / 'copilot-home'

    install(repo_root, home, roles=_roles(), dry_run=False)

    for coordinator in (
        'agentmaster-plan',
        'agentmaster-execute',
        'agentmaster-review',
        'agentmaster-retro',
    ):
        text = (home / 'agents' / f'{coordinator}.agent.md').read_text(encoding='utf-8')
        assert 'model: opus-test\n' in text
    scout = (home / 'agents' / 'scout.agent.md').read_text(encoding='utf-8')
    assert 'model: claude-haiku-4.5\n' in scout


def test_idempotent_rerun_creates_nothing(tmp_path: Path, repo_root, statuses) -> None:
    home = tmp_path / 'copilot-home'
    install(repo_root, home, roles=_roles(), dry_run=False)

    report = install(repo_root, home, roles=_roles(), dry_run=False)

    assert 'create' not in statuses(report.entries)


def test_dry_run_writes_nothing(tmp_path: Path, repo_root) -> None:
    home = tmp_path / 'copilot-home'

    report = install(repo_root, home, roles=_roles(), dry_run=True)

    assert report.entries
    assert not home.exists()


def test_uninstall_removes_ours_and_spares_others(tmp_path: Path, repo_root) -> None:
    home = tmp_path / 'copilot-home'
    install(repo_root, home, roles=_roles(), dry_run=False)
    other = home / 'hooks' / 'other.json'
    other.write_text('{}\n', encoding='utf-8')

    uninstall(home, dry_run=False)

    assert not (home / 'agents').exists() or not any((home / 'agents').iterdir())
    for skill in (
        'agentmaster-plan',
        'agentmaster-execute',
        'agentmaster-review',
        'agentmaster-retro',
    ):
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


def test_fake_manifest_installs_only_declared(tmp_path: Path, make_manifest) -> None:
    fake_root = tmp_path / 'root'
    _build_fake_root(fake_root)
    home = tmp_path / 'copilot-home'
    manifest = make_manifest(
        workers=('scout',),
        copilot_coordinators=('co',),
        copilot_hooks=('myhook.py',),
        copilot_frontmatter={'scout': 'name: scout\nmodel: claude-haiku-4.5\n'},
        substitutions={'%USES_RULE%': {'claude': 'x', 'copilot': 'y'}},
    )

    install(
        fake_root,
        home,
        roles=_roles(coordinator='m1', implementer='m1'),
        dry_run=False,
        manifest=manifest,
    )

    installed_scout = (home / 'agents' / 'scout.agent.md').read_text(encoding='utf-8')
    assert 'shared body' in installed_scout
    assert (home / 'agents' / 'co.agent.md').is_file()
    assert sorted(p.name for p in (home / 'agents').iterdir()) == [
        'co.agent.md',
        'scout.agent.md',
    ]
    coordinator = (home / 'agents' / 'co.agent.md').read_text(encoding='utf-8')
    assert 'model: m1\n' in coordinator
    assert (home / 'skills' / 'co' / 'SKILL.md').is_file()
    hook_files = sorted(
        p.name for p in (home / 'agentmaster-hooks').iterdir() if p.suffix == '.py'
    )
    assert hook_files == ['myhook.py']


def test_preflight_missing_source_raises_and_writes_nothing(
    tmp_path: Path, make_manifest
) -> None:
    fake_root = tmp_path / 'root'
    _build_fake_root(fake_root)
    (fake_root / 'copilot' / 'agents' / 'co.agent.md').unlink()
    home = tmp_path / 'copilot-home'
    manifest = make_manifest(
        workers=('scout',),
        copilot_coordinators=('co',),
        copilot_hooks=('myhook.py',),
        copilot_frontmatter={'scout': 'name: scout\nmodel: claude-haiku-4.5\n'},
        substitutions={'%USES_RULE%': {'claude': 'x', 'copilot': 'y'}},
    )

    with pytest.raises(FileNotFoundError):
        install(
            fake_root,
            home,
            roles=_roles(coordinator='m1', implementer='m1'),
            dry_run=False,
            manifest=manifest,
        )

    assert not home.exists()

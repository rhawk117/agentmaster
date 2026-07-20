"""Claude Code install target — composes skills, workers, and the hook layer.

Ports the behaviour of the retired shell installer: a completeness
preflight over the bundle sources, a single transactional `apply_plans` call
that places skill trees, rendered worker agents, and the lifecycle hooks, then
an idempotent merge of the five agentmaster hook events into `settings.json`.
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from installer.actions import FilePlan, apply_plans, remove_paths
from installer.frontmatter import update_frontmatter
from installer.manifest import MANIFEST, Manifest
from installer.render import render_worker

if TYPE_CHECKING:
    from installer.actions import InstallReport

_MODEL_SKILLS = frozenset({'agentmaster-plan', 'agentmaster-review', 'agentmaster-retro'})
_COST_BOUNDARY_SOURCE = 'python3 "$HOME/.claude/agentmaster/hooks/cost_boundary.py"'
_ROSTER = '^(scout|code-analyst|plan-critic|implementer|Explore)$'


def default_home() -> Path:
    """Return the Claude config dir — `CLAUDE_CONFIG_DIR` if set, else `~/.claude`."""
    override = os.environ.get('CLAUDE_CONFIG_DIR')
    if override:
        return Path(override)
    return Path.home() / '.claude'


def _interpreter() -> str:
    return Path(sys.executable).as_posix()


def _preflight(root: Path, manifest: Manifest) -> None:
    sources = [
        *(f'skills/{skill}/SKILL.md' for skill in manifest.claude_skills),
        *(f'agents/{agent}.md' for agent in manifest.claude_only_agents),
        *(f'hooks/{hook}' for hook in manifest.claude_hooks),
        *(f'shared/agents/{worker}.md' for worker in manifest.workers),
    ]
    missing = [rel for rel in sources if not (root / rel).is_file()]
    if missing:
        raise FileNotFoundError('missing installer sources: ' + ', '.join(missing))


def _skill_plans(
    root: Path, home: Path, model: str, manifest: Manifest
) -> list[FilePlan]:
    interpreter = _interpreter()
    boundary = f'"{interpreter}" "{home.as_posix()}/agentmaster/hooks/cost_boundary.py"'
    plans: list[FilePlan] = []
    for skill in manifest.claude_skills:
        src_dir = root / 'skills' / skill
        for src in sorted(p for p in src_dir.rglob('*') if p.is_file()):
            content = src.read_text(encoding='utf-8')
            if src.name == 'SKILL.md':
                content = content.replace(_COST_BOUNDARY_SOURCE, boundary)
                if skill in _MODEL_SKILLS:
                    content = update_frontmatter(
                        content, {'model': f'{model}  # set by install.py'}
                    )
            relative = src.relative_to(src_dir)
            plans.append(
                FilePlan(content=content, destination=home / 'skills' / skill / relative)
            )
    return plans


def _agent_plans(root: Path, home: Path, manifest: Manifest) -> list[FilePlan]:
    plans: list[FilePlan] = []
    for worker in manifest.workers:
        text = render_worker(worker, 'claude', manifest, root)
        plans.append(FilePlan(content=text, destination=home / 'agents' / f'{worker}.md'))
    for agent in manifest.claude_only_agents:
        content = (root / 'agents' / f'{agent}.md').read_text(encoding='utf-8')
        destination = home / 'agents' / f'{agent}.md'
        plans.append(FilePlan(content=content, destination=destination))
    return plans


def _hook_plans(root: Path, home: Path, manifest: Manifest) -> list[FilePlan]:
    return [
        FilePlan(
            content=(root / 'hooks' / hook).read_text(encoding='utf-8'),
            destination=home / 'agentmaster' / 'hooks' / hook,
            executable=True,
        )
        for hook in manifest.claude_hooks
    ]


def _is_ours(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    return any(
        isinstance(hook, dict) and 'agentmaster/hooks' in hook.get('command', '')
        for hook in entry.get('hooks', [])
    )


def _load_settings(settings_path: Path) -> dict:
    """Parse and shape-check settings.json, failing closed on malformed content."""
    try:
        settings = json.loads(settings_path.read_text(encoding='utf-8'))
    except ValueError as error:
        msg = f'{settings_path} is not valid JSON: {error}'
        raise ValueError(msg) from error
    if not isinstance(settings, dict):
        msg = f'{settings_path}: settings.json must contain a JSON object'
        raise ValueError(msg)  # noqa: TRY004 -- file content, not a type bug
    hooks = settings.get('hooks', {})
    if not isinstance(hooks, dict):
        msg = f'{settings_path}: "hooks" must be a JSON object'
        raise ValueError(msg)  # noqa: TRY004 -- file content, not a type bug
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            msg = f'{settings_path}: hooks[{event!r}] must be a JSON array'
            raise ValueError(msg)  # noqa: TRY004 -- file content, not a type bug
    return settings


def _hook_events(home: Path) -> dict[str, list[dict]]:
    interpreter = _interpreter()
    hook_dir = (home / 'agentmaster' / 'hooks').as_posix()

    def cmd(name: str) -> dict:
        return {'type': 'command', 'command': f'"{interpreter}" "{hook_dir}/{name}"'}

    return {
        'SubagentStart': [{'matcher': _ROSTER, 'hooks': [cmd('subagent_start.py')]}],
        'SubagentStop': [{'matcher': _ROSTER, 'hooks': [cmd('telemetry.py')]}],
        'PreToolUse': [
            {'matcher': '^(Agent|Task)$', 'hooks': [cmd('dispatch_guard.py')]}
        ],
        'PreCompact': [{'hooks': [cmd('precompact_snapshot.py')]}],
        'SessionStart': [{'hooks': [cmd('session_context.py')]}],
    }


def _merge_settings(home: Path) -> None:
    settings_path = home / 'settings.json'
    if settings_path.exists():
        backup = home / f'settings.json.agentmaster-backup-{int(time.time())}'
        shutil.copy2(settings_path, backup)
        settings = _load_settings(settings_path)
    else:
        settings = {}
    hooks = settings.setdefault('hooks', {})
    for event, entries in _hook_events(home).items():
        current = hooks.setdefault(event, [])
        current[:] = [entry for entry in current if not _is_ours(entry)]
        current.extend(entries)
    settings_path.write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')


def _strip_settings(home: Path) -> None:
    settings_path = home / 'settings.json'
    if not settings_path.exists():
        return
    settings = _load_settings(settings_path)
    hooks = settings.get('hooks', {})
    for entries in hooks.values():
        entries[:] = [entry for entry in entries if not _is_ours(entry)]
    settings_path.write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')


def install(
    root: Path,
    home: Path,
    *,
    model: str,
    dry_run: bool,
    manifest: Manifest = MANIFEST,
) -> InstallReport:
    """Install skills, workers, and the hook layer into a Claude config home."""
    home = home.resolve()
    _preflight(root, manifest)
    settings_path = home / 'settings.json'
    if settings_path.exists():
        _load_settings(settings_path)  # fail closed before any file is written
    plans = [
        *_skill_plans(root, home, model, manifest),
        *_agent_plans(root, home, manifest),
        *_hook_plans(root, home, manifest),
    ]
    report = apply_plans(plans, backup_root=home, dry_run=dry_run)
    if not dry_run:
        _merge_settings(home)
    return report


def uninstall(
    home: Path, *, dry_run: bool, manifest: Manifest = MANIFEST
) -> InstallReport:
    """Remove agentmaster skills, agents, and hooks; strip only its hook entries."""
    home = home.resolve()
    paths = [home / 'skills' / skill for skill in manifest.claude_skills]
    paths += [home / 'agents' / f'{worker}.md' for worker in manifest.workers]
    paths += [home / 'agents' / f'{agent}.md' for agent in manifest.claude_only_agents]
    paths.append(home / 'agentmaster')
    report = remove_paths(paths, dry_run=dry_run)
    if not dry_run:
        _strip_settings(home)
    return report

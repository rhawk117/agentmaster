"""GitHub Copilot CLI install target.

Composes the transactional actions core, the manifest, and the worker
renderer into a single `install`/`uninstall` pair for the Copilot user
scope. Ported from the retired shell installer: 4 rendered
workers plus 4 re-pinned coordinator files under `home/agents/`, the 4
router-skill trees under `home/skills/`, the 4 hook scripts under
`home/agentmaster-hooks/`, and a `home/hooks/agentmaster.json` event
config that participates in the same classify/backup/dry-run pass.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from installer.actions import FilePlan, apply_plans, remove_paths
from installer.manifest import MANIFEST
from installer.render import render_worker

if TYPE_CHECKING:
    from collections.abc import Iterator

    from installer.actions import InstallReport
    from installer.manifest import Manifest

_MODEL_LINE = re.compile(r'(?m)^model: .*$')


def default_home() -> Path:
    """Return the Copilot config dir: `$COPILOT_CONFIG_DIR` or `~/.copilot`."""
    override = os.environ.get('COPILOT_CONFIG_DIR')
    return Path(override) if override else Path.home() / '.copilot'


def _required_sources(root: Path, manifest: Manifest) -> Iterator[Path]:
    for coordinator in manifest.copilot_coordinators:
        yield root / 'copilot' / 'agents' / f'{coordinator}.agent.md'
    for skill in manifest.copilot_coordinators:
        yield root / 'copilot' / 'skills' / skill / 'SKILL.md'
    for hook in manifest.copilot_hooks:
        yield root / 'hooks' / hook
    for worker in manifest.workers:
        yield root / 'shared' / 'agents' / f'{worker}.md'


def _preflight(root: Path, manifest: Manifest) -> None:
    missing = [path for path in _required_sources(root, manifest) if not path.is_file()]
    if missing:
        listed = ', '.join(str(path) for path in missing)
        msg = f'missing required Copilot source files: {listed}'
        raise FileNotFoundError(msg)


def _worker_plans(root: Path, home: Path, manifest: Manifest) -> list[FilePlan]:
    return [
        FilePlan(
            content=render_worker(worker, 'copilot', manifest, root),
            destination=home / 'agents' / f'{worker}.agent.md',
        )
        for worker in manifest.workers
    ]


def _coordinator_plans(
    root: Path, home: Path, model: str, manifest: Manifest
) -> list[FilePlan]:
    plans: list[FilePlan] = []
    for coordinator in manifest.copilot_coordinators:
        source = root / 'copilot' / 'agents' / f'{coordinator}.agent.md'
        text = source.read_text(encoding='utf-8')
        repinned = _MODEL_LINE.sub(lambda _: f'model: {model}', text)
        plans.append(
            FilePlan(
                content=repinned,
                destination=home / 'agents' / f'{coordinator}.agent.md',
            )
        )
    return plans


def _skill_plans(root: Path, home: Path, manifest: Manifest) -> list[FilePlan]:
    plans: list[FilePlan] = []
    for skill in manifest.copilot_coordinators:
        skill_root = root / 'copilot' / 'skills' / skill
        for path in sorted(skill_root.rglob('*')):
            if not path.is_file():
                continue
            relative = path.relative_to(skill_root)
            plans.append(
                FilePlan(
                    content=path.read_text(encoding='utf-8'),
                    destination=home / 'skills' / skill / relative,
                )
            )
    return plans


def _hook_plans(root: Path, home: Path, manifest: Manifest) -> list[FilePlan]:
    return [
        FilePlan(
            content=(root / 'hooks' / hook).read_text(encoding='utf-8'),
            destination=home / 'agentmaster-hooks' / hook,
            executable=True,
        )
        for hook in manifest.copilot_hooks
    ]


def _hook_entry(home: Path, hook: str) -> dict[str, object]:
    interpreter = Path(sys.executable).as_posix()
    hook_path = (home / 'agentmaster-hooks' / hook).as_posix()
    return {
        'type': 'command',
        'bash': f'"{interpreter}" "{hook_path}"',
        'timeoutSec': 5,
    }


def _hooks_json(home: Path) -> str:
    config = {
        'version': 1,
        'hooks': {
            'preToolUse': [_hook_entry(home, 'copilot_telemetry_pre.py')],
            'postToolUse': [_hook_entry(home, 'copilot_telemetry_post.py')],
            'sessionStart': [_hook_entry(home, 'session_context.py')],
        },
    }
    return json.dumps(config, indent=2) + '\n'


def install(
    root: Path,
    home: Path,
    *,
    model: str,
    dry_run: bool,
    manifest: Manifest = MANIFEST,
) -> InstallReport:
    """Install the agentmaster Copilot target into `home`.

    Verifies every source file exists before planning a single write, then
    applies all agents, skills, hooks, and the hook config in one
    transactional pass backed up under `home`.
    """
    home = home.resolve()
    _preflight(root, manifest)
    plans = [
        *_worker_plans(root, home, manifest),
        *_coordinator_plans(root, home, model, manifest),
        *_skill_plans(root, home, manifest),
        *_hook_plans(root, home, manifest),
        FilePlan(
            content=_hooks_json(home),
            destination=home / 'hooks' / 'agentmaster.json',
        ),
    ]
    return apply_plans(plans, backup_root=home, dry_run=dry_run)


def uninstall(
    home: Path, *, dry_run: bool, manifest: Manifest = MANIFEST
) -> InstallReport:
    """Remove the agentmaster Copilot target from `home`.

    Removes the 7 agent files, the 3 router-skill trees, the hook script
    directory, and `home/hooks/agentmaster.json` only — other files under
    `home/hooks/` are left untouched.
    """
    home = home.resolve()
    agents = (*manifest.workers, *manifest.copilot_coordinators)
    paths = [
        *(home / 'agents' / f'{name}.agent.md' for name in agents),
        *(home / 'skills' / skill for skill in manifest.copilot_coordinators),
        home / 'agentmaster-hooks',
        home / 'hooks' / 'agentmaster.json',
    ]
    return remove_paths(paths, dry_run=dry_run)

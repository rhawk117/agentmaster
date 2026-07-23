import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from installer import managed_state, runtime
from installer.actions import FilePlan, apply_plans, remove_paths
from installer.frontmatter import update_frontmatter
from installer.manifest import MANIFEST
from installer.render import render_worker

if TYPE_CHECKING:
    from collections.abc import Iterator

    from installer.actions import InstallReport
    from installer.config import CopilotRoleConfig
    from installer.manifest import Manifest


def default_home() -> Path:
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


def _worker_plans(
    root: Path, home: Path, roles: CopilotRoleConfig, manifest: Manifest
) -> list[FilePlan]:
    plans = []
    for worker in manifest.workers:
        overrides = (
            {'model': roles.implementer_model} if worker == 'implementer' else None
        )
        plans.append(
            FilePlan(
                content=render_worker(
                    worker, 'copilot', manifest, root, overrides=overrides
                ),
                destination=home / 'agents' / f'{worker}.agent.md',
            )
        )
    return plans


def _coordinator_plans(
    root: Path, home: Path, roles: CopilotRoleConfig, manifest: Manifest
) -> list[FilePlan]:
    plans: list[FilePlan] = []
    for coordinator in manifest.copilot_coordinators:
        source = root / 'copilot' / 'agents' / f'{coordinator}.agent.md'
        text = source.read_text(encoding='utf-8')
        repinned = update_frontmatter(text, {'model': roles.coordinator_model})
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
    interpreter = runtime.resolve_interpreter()
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


def _read_text(path: Path) -> str | None:
    return path.read_text(encoding='utf-8') if path.exists() else None


@dataclass(frozen=True, slots=True)
class CopilotInstallOptions:
    roles: CopilotRoleConfig
    agentmaster_home: Path
    ledger_path: Path | None
    ledger_enabled: bool
    artifact_path: Path
    dry_run: bool
    manifest: Manifest = MANIFEST


def install(root: Path, home: Path, options: CopilotInstallOptions) -> InstallReport:
    home = home.resolve()
    roles, manifest = options.roles, options.manifest
    agentmaster_home = options.agentmaster_home.resolve()
    _preflight(root, manifest)

    interpreter = runtime.resolve_interpreter()
    launcher = agentmaster_home / 'bin' / 'agentmaster'
    owned_state = managed_state.parse(_read_text(agentmaster_home / 'owned-state.json'))
    new_owned_state = owned_state.with_value(
        'copilot',
        'runtime_dirs',
        [str(agentmaster_home / 'runtime'), str(agentmaster_home / 'bin')],
    )
    descriptor = runtime.RuntimeDescriptor(
        config_path=agentmaster_home / 'config.toml',
        launcher=launcher,
        ledger_path=options.ledger_path if options.ledger_enabled else None,
        ledger_enabled=options.ledger_enabled,
        artifact_dir=options.artifact_path,
    )

    plans = [
        *_worker_plans(root, home, roles, manifest),
        *_coordinator_plans(root, home, roles, manifest),
        *_skill_plans(root, home, manifest),
        *_hook_plans(root, home, manifest),
        FilePlan(
            content=_hooks_json(home),
            destination=home / 'hooks' / 'agentmaster.json',
        ),
        *runtime.runtime_plans(root, agentmaster_home),
        runtime.launcher_plan(agentmaster_home, interpreter),
        runtime.descriptor_plan(home / 'agentmaster-hooks' / 'runtime.json', descriptor),
        FilePlan(
            content=managed_state.render(new_owned_state),
            destination=agentmaster_home / 'owned-state.json',
        ),
    ]
    return apply_plans(plans, backup_root=home, dry_run=options.dry_run)


def uninstall(
    home: Path,
    *,
    dry_run: bool,
    agentmaster_home: Path,
    manifest: Manifest = MANIFEST,
) -> InstallReport:
    home = home.resolve()
    agentmaster_home = agentmaster_home.resolve()
    owned_state = managed_state.parse(_read_text(agentmaster_home / 'owned-state.json'))
    runtime_dirs = owned_state.get('copilot', 'runtime_dirs', [])
    if not isinstance(runtime_dirs, list):
        runtime_dirs = []

    agents = (*manifest.workers, *manifest.copilot_coordinators)
    paths = [
        *(home / 'agents' / f'{name}.agent.md' for name in agents),
        *(home / 'skills' / skill for skill in manifest.copilot_coordinators),
        home / 'agentmaster-hooks',
        home / 'hooks' / 'agentmaster.json',
        *(Path(entry) for entry in runtime_dirs if isinstance(entry, str)),
    ]
    return remove_paths(paths, dry_run=dry_run)

"""Claude Code install target — composes skills, workers, and the hook layer.

Ports the behaviour of the retired shell installer: a completeness
preflight over the bundle sources, then a single transactional `apply_plans`
call that places skill trees, rendered worker agents, the lifecycle hooks,
and the merged `settings.json` / Agentmaster `config.toml` / owned-state
document all in one batch, so a failure partway through rolls every one of
them back together.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from installer import agentmaster_config, claude_settings, managed_state, runtime
from installer.actions import FilePlan, apply_plans, remove_paths
from installer.config import (
    DEFAULT_ROLE_EFFORT,
    AutoCompactOverride,
    ClaudeRoleConfig,
    ResolvedConfig,
    Role,
    RoleOverride,
)
from installer.frontmatter import update_frontmatter
from installer.manifest import MANIFEST, Manifest
from installer.render import render_worker

if TYPE_CHECKING:
    from installer.actions import InstallReport

_SKILL_ROLE = {
    'agentmaster-plan': Role.COORDINATOR,
    'agentmaster-retro': Role.COORDINATOR,
    'agentmaster-execute': Role.ORCHESTRATOR,
    'agentmaster-review': Role.REVIEWER,
}
_COST_BOUNDARY_SOURCE = 'python3 "$HOME/.claude/agentmaster/hooks/cost_boundary.py"'
_ROSTER = '^(scout|code-analyst|plan-critic|implementer|git-publisher|Explore)$'


def _effort_value(role: RoleOverride, fallback: Role) -> str:
    return (role.effort or DEFAULT_ROLE_EFFORT[fallback]).value


def _owned_hooks(owned_state: managed_state.OwnedState) -> dict[str, list]:
    value = owned_state.get('claude', 'hooks', {})
    if not isinstance(value, dict):
        return {}
    return {
        event: entries
        for event, entries in value.items()
        if isinstance(event, str) and isinstance(entries, list)
    }


def _owned_auto_compact(
    owned_state: managed_state.OwnedState,
) -> dict[str, object] | None:
    value = owned_state.get('claude', 'auto_compact')
    if not isinstance(value, dict):
        return None
    return {key: val for key, val in value.items() if isinstance(key, str)}


def _skill_overrides(skill: str, roles: ClaudeRoleConfig) -> dict[str, str] | None:
    role = _SKILL_ROLE.get(skill)
    if role is Role.COORDINATOR:
        return {'model': roles.coordinator_model}
    if role is Role.ORCHESTRATOR:
        return roles.orchestrator.frontmatter_fields()
    if role is Role.REVIEWER:
        return roles.reviewer.frontmatter_fields()
    return None


def default_home() -> Path:
    """Return the Claude config dir — `CLAUDE_CONFIG_DIR` if set, else `~/.claude`."""
    override = os.environ.get('CLAUDE_CONFIG_DIR')
    if override:
        return Path(override)
    return Path.home() / '.claude'


def _interpreter() -> str:
    return runtime.resolve_interpreter()


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
    root: Path, home: Path, roles: ClaudeRoleConfig, manifest: Manifest
) -> list[FilePlan]:
    interpreter = _interpreter()
    boundary = f'"{interpreter}" "{home.as_posix()}/agentmaster/hooks/cost_boundary.py"'
    plans: list[FilePlan] = []
    for skill in manifest.claude_skills:
        src_dir = root / 'skills' / skill
        overrides = _skill_overrides(skill, roles)
        for src in sorted(p for p in src_dir.rglob('*') if p.is_file()):
            content = src.read_text(encoding='utf-8')
            if src.name == 'SKILL.md':
                content = content.replace(_COST_BOUNDARY_SOURCE, boundary)
                if overrides:
                    content = update_frontmatter(content, overrides)
            relative = src.relative_to(src_dir)
            plans.append(
                FilePlan(content=content, destination=home / 'skills' / skill / relative)
            )
    return plans


def _agent_plans(
    root: Path, home: Path, roles: ClaudeRoleConfig, manifest: Manifest
) -> list[FilePlan]:
    plans: list[FilePlan] = []
    for worker in manifest.workers:
        overrides = (
            roles.implementer.frontmatter_fields() if worker == 'implementer' else None
        )
        text = render_worker(worker, 'claude', manifest, root, overrides=overrides)
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


def _read_text(path: Path) -> str | None:
    return path.read_text(encoding='utf-8') if path.exists() else None


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
        'Stop': [{'hooks': [cmd('execute_stop.py')]}],
    }


def _managed_plans(
    home: Path,
    roles: ClaudeRoleConfig,
    resolved: ResolvedConfig,
    auto_compact: AutoCompactOverride,
    launcher: Path,
) -> list[FilePlan]:
    """Compute the settings.json / config.toml / owned-state.json / runtime.json plans.

    Reads and shape-validates each existing file (failing closed on
    malformed content) before any write; the caller folds the result into
    the same `apply_plans` batch as the skill/agent/hook plans.
    """
    agentmaster_home = resolved.agentmaster_home.resolve()
    settings_path = home / 'settings.json'
    settings_text = _read_text(settings_path)
    settings = (
        claude_settings.validate_settings(json.loads(settings_text))
        if settings_text
        else {}
    )

    owned_state_path = agentmaster_home / 'owned-state.json'
    owned_state = managed_state.parse(_read_text(owned_state_path))

    marker = f'{home.as_posix()}/agentmaster/hooks'
    new_settings, new_owned_hooks = claude_settings.merge_hook_events(
        settings,
        _hook_events(home),
        owned=_owned_hooks(owned_state),
        marker=marker,
    )
    new_owned_state = owned_state.with_value('claude', 'hooks', new_owned_hooks)

    owned_auto_compact = _owned_auto_compact(owned_state)
    if auto_compact.percent is not None:
        new_settings, new_owned_auto_compact = (
            claude_settings.merge_auto_compact_override(
                new_settings, owned=owned_auto_compact, percent=auto_compact.percent
            )
        )
    elif auto_compact.clear:
        new_settings = claude_settings.strip_auto_compact_override(
            new_settings, owned_auto_compact
        )
        new_owned_auto_compact = None
    else:
        new_owned_auto_compact = owned_auto_compact
    new_owned_state = new_owned_state.with_value(
        'claude', 'auto_compact', new_owned_auto_compact
    )
    new_owned_state = new_owned_state.with_value(
        'claude',
        'runtime_dirs',
        [str(agentmaster_home / 'runtime'), str(agentmaster_home / 'bin')],
    )

    config_path = agentmaster_home / 'config.toml'
    config_plan = agentmaster_config.AgentmasterConfigPlan(
        ledger_path=str(resolved.ledger_path),
        artifact_path=str(resolved.artifact_path),
        ledger_enabled=resolved.ledger_enabled,
        delivery_mode=resolved.delivery_mode.value,
        orchestrator_model=roles.orchestrator.model,
        orchestrator_effort=_effort_value(roles.orchestrator, Role.ORCHESTRATOR),
        implementer_model=roles.implementer.model,
        implementer_effort=_effort_value(roles.implementer, Role.IMPLEMENTER),
        reviewer_model=roles.reviewer.model,
        reviewer_effort=_effort_value(roles.reviewer, Role.REVIEWER),
        raw_capture=resolved.raw_capture.value,
        redaction=resolved.redaction.value,
    )
    config_text = agentmaster_config.render_config(
        config_plan, existing_text=_read_text(config_path)
    )

    descriptor = runtime.RuntimeDescriptor(
        config_path=config_path,
        launcher=launcher,
        ledger_path=resolved.ledger_path if resolved.ledger_enabled else None,
        ledger_enabled=resolved.ledger_enabled,
        artifact_dir=resolved.artifact_path,
    )

    return [
        FilePlan(
            content=json.dumps(new_settings, indent=2) + '\n', destination=settings_path
        ),
        FilePlan(content=config_text, destination=config_path),
        FilePlan(
            content=managed_state.render(new_owned_state), destination=owned_state_path
        ),
        runtime.descriptor_plan(home / 'agentmaster' / 'runtime.json', descriptor),
    ]


def _strip_settings(home: Path, agentmaster_home: Path) -> dict | None:
    """Compute settings.json with only exactly-owned entries removed.

    Returns `None` when there is no settings.json to strip. Called before
    any deletion so malformed settings fail closed before removal (§14).
    """
    settings_path = home / 'settings.json'
    settings_text = _read_text(settings_path)
    if settings_text is None:
        return None
    settings = claude_settings.validate_settings(json.loads(settings_text))
    owned_state = managed_state.parse(_read_text(agentmaster_home / 'owned-state.json'))
    stripped = claude_settings.strip_hook_events(settings, _owned_hooks(owned_state))
    return claude_settings.strip_auto_compact_override(
        stripped, _owned_auto_compact(owned_state)
    )


@dataclass(frozen=True, slots=True)
class ClaudeInstallOptions:
    """Per-call Claude installer inputs beyond the source root and target home."""

    roles: ClaudeRoleConfig
    resolved: ResolvedConfig
    auto_compact: AutoCompactOverride = field(
        default_factory=lambda: AutoCompactOverride(None, False)
    )
    manifest: Manifest = MANIFEST


def install(root: Path, home: Path, options: ClaudeInstallOptions) -> InstallReport:
    """Install skills, workers, hooks, and managed settings/config transactionally.

    `settings.json`, Agentmaster's `config.toml`, and the owned-state
    document are computed as plain file plans and applied in the same
    `apply_plans` batch as everything else — no target mutates settings
    outside the plan, and a failure partway through rolls all of them back.
    """
    home = home.resolve()
    roles, resolved, auto_compact, manifest = (
        options.roles,
        options.resolved,
        options.auto_compact,
        options.manifest,
    )
    _preflight(root, manifest)
    agentmaster_home = resolved.agentmaster_home.resolve()
    interpreter = runtime.resolve_interpreter()
    launcher = agentmaster_home / 'bin' / 'agentmaster'
    plans = [
        *_skill_plans(root, home, roles, manifest),
        *_agent_plans(root, home, roles, manifest),
        *_hook_plans(root, home, manifest),
        *runtime.runtime_plans(root, agentmaster_home),
        runtime.launcher_plan(agentmaster_home, interpreter),
        *_managed_plans(home, roles, resolved, auto_compact, launcher),
    ]
    return apply_plans(plans, backup_root=home, dry_run=resolved.dry_run)


def uninstall(
    home: Path,
    *,
    agentmaster_home: Path,
    dry_run: bool,
    manifest: Manifest = MANIFEST,
) -> InstallReport:
    """Remove agentmaster skills, agents, and hooks; strip only owned settings entries.

    Settings are validated and the stripped result computed before any
    deletion, so malformed settings fail closed before anything is removed.
    """
    home = home.resolve()
    agentmaster_home = agentmaster_home.resolve()
    stripped_settings = _strip_settings(home, agentmaster_home)
    owned_state = managed_state.parse(_read_text(agentmaster_home / 'owned-state.json'))
    runtime_dirs = owned_state.get('claude', 'runtime_dirs', [])
    if not isinstance(runtime_dirs, list):
        runtime_dirs = []

    paths = [home / 'skills' / skill for skill in manifest.claude_skills]
    paths += [home / 'agents' / f'{worker}.md' for worker in manifest.workers]
    paths += [home / 'agents' / f'{agent}.md' for agent in manifest.claude_only_agents]
    paths.append(home / 'agentmaster')
    paths += [Path(entry) for entry in runtime_dirs if isinstance(entry, str)]
    report = remove_paths(paths, dry_run=dry_run)

    if not dry_run and stripped_settings is not None:
        settings_path = home / 'settings.json'
        settings_path.write_text(
            json.dumps(stripped_settings, indent=2) + '\n', encoding='utf-8'
        )
    return report

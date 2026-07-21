"""agentmaster installer CLI.

Commands:
    python install.py install   --target claude|copilot|all [--dry-run] [--no-input]
                                 [--claude-model NAME] [--copilot-model NAME]
                                 [--claude-orchestrator-model NAME]
                                 [--claude-orchestrator-effort low|medium|high|xhigh|max]
                                 [--claude-implementer-model NAME]
                                 [--claude-implementer-effort low|medium|high|xhigh|max]
                                 [--claude-review-model NAME]
                                 [--claude-review-effort low|medium|high|xhigh|max]
                                 [--copilot-implementer-model NAME]
                                 [--ledger-path PATH] [--no-ledger] [--artifact-dir PATH]
                                 [--delivery-mode local|commit|pull-request|merge]
                                 [--auto-compact-percent 1-100]
                                 [--clear-auto-compact-override]
                                 [--config PATH] [--agentmaster-home PATH]
    python install.py uninstall --target claude|copilot|all [--dry-run]
    python install.py validate
    python install.py sync

Each role (coordinator, orchestrator, implementer, reviewer) resolves
independently: an explicit flag wins; when absent on an interactive terminal
the installer prompts; otherwise it uses the recommended default silently.
`--no-input` and a non-interactive stdin both suppress prompting. Copilot has
no orchestrator/reviewer roles and never gets an effort field.
Destinations honor `CLAUDE_CONFIG_DIR` / `COPILOT_CONFIG_DIR` and the
`--claude-dir` / `--copilot-dir` overrides. `--config` loads a versioned
TOML file (schema in SPEC.md §12); explicit CLI flags always win over it.
`--auto-compact-percent` (Claude only, 1-100) and
`--clear-auto-compact-override` (mutually exclusive) manage
`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`; this affects the main Claude conversation
and all subagents, so omitting both flags leaves current behavior untouched.
Exit code is 0 on success, 1 on any failure or validation finding.
"""

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from installer import claude, copilot
from installer.config import (
    MODEL_RE,
    ClaudeRoleConfig,
    ConfigError,
    CopilotRoleConfig,
    DeliveryMode,
    Effort,
    ResolvedConfig,
    Role,
    RoleOverride,
    RolePromptContext,
    Target,
    UnresolvedConfig,
    load_config_document,
    resolve,
    resolve_auto_compact,
    resolve_role,
    validate_auto_compact_flags,
    validate_ledger_flags,
    validate_role_flags,
)
from installer.ledger_bootstrap import (
    LedgerBootstrapError,
    LedgerBootstrapPlan,
    bootstrap,
)
from installer.parity import validate
from installer.render import sync_workers

if TYPE_CHECKING:
    from collections.abc import Callable

    from installer.actions import InstallReport

ROOT = Path(__file__).resolve().parent
_MODEL_FIELDS = (
    'claude_model',
    'copilot_model',
    'claude_orchestrator_model',
    'claude_implementer_model',
    'claude_review_model',
    'copilot_implementer_model',
)
_REMOVED_MODEL_MESSAGE = (
    '--model was removed; use --claude-model/--copilot-model for the coordinator, '
    'or a role-specific flag: --claude-orchestrator-model/-effort, '
    '--claude-implementer-model/-effort, --claude-review-model/-effort, '
    '--copilot-implementer-model.'
)


def _home(target: Target, resolved: ResolvedConfig) -> Path:
    override = resolved.claude_dir if target is Target.CLAUDE else resolved.copilot_dir
    if override:
        return override
    return claude.default_home() if target is Target.CLAUDE else copilot.default_home()


def _prompt_role(
    role: Role, target: Target, default_model: str, default_effort: Effort | None
) -> tuple[str, Effort | None]:
    print(f'{target}/{role}:')
    model = input(f'  model [{default_model}]: ').strip() or default_model
    if default_effort is None:
        return model, None
    choices = '/'.join(effort.value for effort in Effort)
    raw_effort = input(f'  effort ({choices}) [{default_effort}]: ').strip()
    return model, Effort(raw_effort) if raw_effort else default_effort


_AUTO_COMPACT_NOTE = (
    'This affects the main Claude conversation and all subagents. Earlier '
    'compaction reduces working-context pressure but may discard detail and '
    'disrupt cache continuity; it is not a per-implementer control.'
)


def _prompt_auto_compact() -> tuple[int | None, bool]:
    print(f'Claude auto-compaction override: {_AUTO_COMPACT_NOTE}')
    print('  1) preserve current/default behavior')
    print('  2) set 50% (recommended for long Agentmaster execution sessions)')
    print('  3) set a custom percentage')
    print('  4) clear an existing Agentmaster-managed override')
    choice = input('  choice [1]: ').strip() or '1'
    if choice == '2':
        return 50, False
    if choice == '3':
        return int(input('  percent (1-100): ').strip()), False
    if choice == '4':
        return None, True
    return None, False


def _reject_removed_model_flag(argv: list[str]) -> bool:
    if any(arg == '--model' or arg.startswith('--model=') for arg in argv):
        print(_REMOVED_MODEL_MESSAGE, file=sys.stderr)
        return True
    return False


def _invalid_model(unresolved: UnresolvedConfig) -> str | None:
    for name in _MODEL_FIELDS:
        value = getattr(unresolved, name)
        if value and not MODEL_RE.match(value):
            return value
    return None


def _unresolved_config(args: argparse.Namespace) -> UnresolvedConfig:
    def _effort(name: str) -> Effort | None:
        value = getattr(args, name, None)
        return Effort(value) if value else None

    return UnresolvedConfig(
        target=Target(args.target),
        dry_run=getattr(args, 'dry_run', False),
        no_input=getattr(args, 'no_input', False),
        claude_dir=Path(args.claude_dir) if getattr(args, 'claude_dir', None) else None,
        copilot_dir=Path(args.copilot_dir)
        if getattr(args, 'copilot_dir', None)
        else None,
        config_path=Path(args.config) if getattr(args, 'config', None) else None,
        agentmaster_home=Path(args.agentmaster_home)
        if getattr(args, 'agentmaster_home', None)
        else None,
        claude_model=getattr(args, 'claude_model', None),
        copilot_model=getattr(args, 'copilot_model', None),
        claude_orchestrator_model=getattr(args, 'claude_orchestrator_model', None),
        claude_orchestrator_effort=_effort('claude_orchestrator_effort'),
        claude_implementer_model=getattr(args, 'claude_implementer_model', None),
        claude_implementer_effort=_effort('claude_implementer_effort'),
        claude_review_model=getattr(args, 'claude_review_model', None),
        claude_review_effort=_effort('claude_review_effort'),
        copilot_implementer_model=getattr(args, 'copilot_implementer_model', None),
        ledger_path=Path(args.ledger_path)
        if getattr(args, 'ledger_path', None)
        else None,
        no_ledger=getattr(args, 'no_ledger', False),
        artifact_dir=Path(args.artifact_dir)
        if getattr(args, 'artifact_dir', None)
        else None,
        delivery_mode=DeliveryMode(args.delivery_mode)
        if getattr(args, 'delivery_mode', None)
        else None,
        auto_compact_percent=getattr(args, 'auto_compact_percent', None),
        clear_auto_compact_override=getattr(args, 'clear_auto_compact_override', False),
    )


def _print_report(target: Target, report: InstallReport) -> None:
    for status, path in report.entries:
        print(f'  {status:>6}  {path}')
    if report.backup_dir is not None:
        print(f'  backup  {report.backup_dir}')
    print(f'{target}: {report.summary()}')


def _warn_superpowers(target: Target, home: Path) -> None:
    plugin_dir = 'plugins' if target is Target.CLAUDE else 'installed-plugins'
    if any((home / plugin_dir).glob('*superpowers*')):
        return
    cli = 'copilot' if target is Target.COPILOT else 'claude'
    print(f'note: superpowers plugin not detected for {target} — install with:')
    print(f'  {cli} plugin marketplace add obra/superpowers-marketplace')
    print(f'  {cli} plugin install superpowers@superpowers-marketplace')


def _resolve_claude_roles(
    unresolved: UnresolvedConfig, *, is_tty: bool
) -> ClaudeRoleConfig:
    context = RolePromptContext(
        no_input=unresolved.no_input, is_tty=is_tty, prompt=_prompt_role
    )

    def _role(
        role: Role, model: str | None, effort: Effort | None = None
    ) -> RoleOverride:
        return resolve_role(
            role,
            Target.CLAUDE,
            explicit_model=model,
            explicit_effort=effort,
            context=context,
        )

    return ClaudeRoleConfig(
        coordinator_model=_role(Role.COORDINATOR, unresolved.claude_model).model,
        orchestrator=_role(
            Role.ORCHESTRATOR,
            unresolved.claude_orchestrator_model,
            unresolved.claude_orchestrator_effort,
        ),
        implementer=_role(
            Role.IMPLEMENTER,
            unresolved.claude_implementer_model,
            unresolved.claude_implementer_effort,
        ),
        reviewer=_role(
            Role.REVIEWER, unresolved.claude_review_model, unresolved.claude_review_effort
        ),
    )


def _resolve_copilot_roles(
    unresolved: UnresolvedConfig, *, is_tty: bool
) -> CopilotRoleConfig:
    context = RolePromptContext(
        no_input=unresolved.no_input, is_tty=is_tty, prompt=_prompt_role
    )

    def _role(role: Role, model: str | None) -> RoleOverride:
        return resolve_role(
            role,
            Target.COPILOT,
            explicit_model=model,
            explicit_effort=None,
            context=context,
        )

    return CopilotRoleConfig(
        coordinator_model=_role(Role.COORDINATOR, unresolved.copilot_model).model,
        implementer_model=_role(
            Role.IMPLEMENTER, unresolved.copilot_implementer_model
        ).model,
    )


def _bootstrap_ledger(resolved: ResolvedConfig) -> int | None:
    """Run the ledger/artifact bootstrap; returns an exit code only on failure."""
    if not resolved.ledger_enabled:
        return None
    try:
        bootstrap(
            LedgerBootstrapPlan(
                ledger_path=resolved.ledger_path, artifact_path=resolved.artifact_path
            ),
            dry_run=resolved.dry_run,
        )
    except LedgerBootstrapError as error:
        print(f'ledger: {error}', file=sys.stderr)
        return 1
    return None


def _cmd_install(args: argparse.Namespace) -> int:
    unresolved = _unresolved_config(args)
    bad_model = _invalid_model(unresolved)
    if bad_model is not None:
        print(f'invalid model: {bad_model!r}', file=sys.stderr)
        return 1

    document = None
    if unresolved.config_path is not None:
        try:
            document = load_config_document(unresolved.config_path)
        except ConfigError as error:
            print(f'invalid config: {error}', file=sys.stderr)
            return 1

    try:
        validate_role_flags(unresolved)
        validate_ledger_flags(unresolved)
        validate_auto_compact_flags(unresolved)
        resolved = resolve(unresolved, document)
    except ConfigError as error:
        print(f'invalid config: {error}', file=sys.stderr)
        return 1

    for line in resolved.summary_lines():
        print(f'  {line}')

    ledger_error = _bootstrap_ledger(resolved)
    if ledger_error is not None:
        return ledger_error

    is_tty = sys.stdin.isatty()
    for target in resolved.targets:
        home = _home(target, resolved)
        try:
            if target is Target.CLAUDE:
                roles = _resolve_claude_roles(unresolved, is_tty=is_tty)
                auto_compact = resolve_auto_compact(
                    explicit_percent=unresolved.auto_compact_percent,
                    explicit_clear=unresolved.clear_auto_compact_override,
                    no_input=unresolved.no_input,
                    is_tty=is_tty,
                    prompt=_prompt_auto_compact,
                )
                report = claude.install(
                    ROOT,
                    home,
                    claude.ClaudeInstallOptions(
                        roles=roles, resolved=resolved, auto_compact=auto_compact
                    ),
                )
            else:
                roles = _resolve_copilot_roles(unresolved, is_tty=is_tty)
                report = copilot.install(
                    ROOT, home, roles=roles, dry_run=resolved.dry_run
                )
        except (OSError, ValueError) as error:
            print(f'{target}: install failed: {error}', file=sys.stderr)
            return 1
        _print_report(target, report)
        _warn_superpowers(target, home)
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    resolved = resolve(_unresolved_config(args))
    for target in resolved.targets:
        home = _home(target, resolved)
        try:
            if target is Target.CLAUDE:
                report = claude.uninstall(
                    home,
                    agentmaster_home=resolved.agentmaster_home,
                    dry_run=resolved.dry_run,
                )
            else:
                report = copilot.uninstall(home, dry_run=resolved.dry_run)
        except OSError as error:
            print(f'{target}: uninstall failed: {error}', file=sys.stderr)
            return 1
        _print_report(target, report)
    return 0


def _cmd_validate(_args: argparse.Namespace) -> int:
    findings = validate(ROOT)
    for finding in findings:
        print(finding)
    if findings:
        print(f'validation failed: {len(findings)} finding(s)', file=sys.stderr)
        return 1
    print('validation passed: sources, generated files, and criteria in sync')
    return 0


def _cmd_sync(_args: argparse.Namespace) -> int:
    for path in sync_workers(ROOT):
        print(f'  synced  {path.relative_to(ROOT).as_posix()}')
    return 0


def _add_target_arguments(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument('--target', choices=('claude', 'copilot', 'all'), default='all')
    cmd.add_argument('--dry-run', action='store_true')
    cmd.add_argument('--claude-dir', default=None)
    cmd.add_argument('--copilot-dir', default=None)


def _add_role_arguments(cmd: argparse.ArgumentParser) -> None:
    effort_choices = [effort.value for effort in Effort]
    cmd.add_argument('--claude-model', default=None)
    cmd.add_argument('--copilot-model', default=None)
    cmd.add_argument('--claude-orchestrator-model', default=None)
    cmd.add_argument('--claude-orchestrator-effort', choices=effort_choices, default=None)
    cmd.add_argument('--claude-implementer-model', default=None)
    cmd.add_argument('--claude-implementer-effort', choices=effort_choices, default=None)
    cmd.add_argument('--claude-review-model', default=None)
    cmd.add_argument('--claude-review-effort', choices=effort_choices, default=None)
    cmd.add_argument('--copilot-implementer-model', default=None)


def _add_ledger_arguments(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument('--ledger-path', default=None)
    cmd.add_argument('--no-ledger', action='store_true')
    cmd.add_argument('--artifact-dir', default=None)
    cmd.add_argument(
        '--delivery-mode', choices=[mode.value for mode in DeliveryMode], default=None
    )


def _add_auto_compact_arguments(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument('--auto-compact-percent', type=int, default=None)
    cmd.add_argument('--clear-auto-compact-override', action='store_true')


def _build_parser() -> tuple[argparse.ArgumentParser, dict[str, Callable]]:
    parser = argparse.ArgumentParser(prog='install.py', description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    commands = {
        'install': _cmd_install,
        'uninstall': _cmd_uninstall,
        'validate': _cmd_validate,
        'sync': _cmd_sync,
    }
    for name in commands:
        cmd = sub.add_parser(name)
        if name in ('install', 'uninstall'):
            _add_target_arguments(cmd)
        if name == 'install':
            _add_role_arguments(cmd)
            _add_ledger_arguments(cmd)
            _add_auto_compact_arguments(cmd)
            cmd.add_argument('--config', default=None)
            cmd.add_argument('--agentmaster-home', default=None)
            cmd.add_argument('--no-input', action='store_true')
    return parser, commands


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else argv
    if _reject_removed_model_flag(raw_argv):
        return 1
    parser, commands = _build_parser()
    args = parser.parse_args(argv)
    return commands[args.command](args)


if __name__ == '__main__':
    raise SystemExit(main())

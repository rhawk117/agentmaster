"""agentmaster installer CLI.

Commands:
    python install.py install   --target claude|copilot|all [--dry-run] [--model NAME]
                                 [--config PATH] [--agentmaster-home PATH] [--no-input]
    python install.py uninstall --target claude|copilot|all [--dry-run]
    python install.py validate
    python install.py sync

`--model` wins when given; when absent on an interactive terminal the
installer asks, otherwise it uses the per-platform default silently.
`--no-input` and a non-interactive stdin both suppress prompting.
Destinations honor `CLAUDE_CONFIG_DIR` / `COPILOT_CONFIG_DIR` and the
`--claude-dir` / `--copilot-dir` overrides. `--config` loads a versioned
TOML file (schema in SPEC.md §12); explicit CLI flags always win over it.
Exit code is 0 on success, 1 on any failure or validation finding.
"""

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from installer import claude, copilot
from installer.config import (
    MODEL_RE,
    ConfigError,
    ResolvedConfig,
    Target,
    UnresolvedConfig,
    load_config_document,
    resolve,
    resolve_model,
)
from installer.parity import validate
from installer.render import sync_workers

if TYPE_CHECKING:
    from installer.actions import InstallReport

ROOT = Path(__file__).resolve().parent
MODEL_MENU = {
    'claude': (
        'frontier model for the plan and review skills '
        '(execute stays on sonnet by design):\n'
        '  1) opus            (alias — resolves to Opus 4.8; default)\n'
        '  2) claude-opus-4-8 (pinned full ID)\n'
        '  3) fable           (if your org enables it)\n'
        '  4) custom',
        {'1': 'opus', '': 'opus', '2': 'claude-opus-4-8', '3': 'fable'},
    ),
    'copilot': (
        'frontier reasoning model for the coordinators '
        '(verify availability with /model after install):\n'
        '  1) claude-opus-4.8   (default — frontier reasoning)\n'
        '  2) claude-sonnet-4.6 (budget alternative)\n'
        '  3) custom slug',
        {'1': 'claude-opus-4.8', '': 'claude-opus-4.8', '2': 'claude-sonnet-4.6'},
    ),
}


def _home(target: Target, resolved: ResolvedConfig) -> Path:
    override = resolved.claude_dir if target is Target.CLAUDE else resolved.copilot_dir
    if override:
        return override
    return claude.default_home() if target is Target.CLAUDE else copilot.default_home()


def _prompt_model(target: Target) -> str:
    menu, choices = MODEL_MENU[target]
    print(menu)
    choice = input('choice [1]: ').strip()
    return choices.get(choice) or input('model: ').strip()


def _unresolved_config(args: argparse.Namespace) -> UnresolvedConfig:
    return UnresolvedConfig(
        target=Target(args.target),
        dry_run=getattr(args, 'dry_run', False),
        no_input=getattr(args, 'no_input', False),
        model=getattr(args, 'model', None),
        claude_dir=Path(args.claude_dir) if getattr(args, 'claude_dir', None) else None,
        copilot_dir=Path(args.copilot_dir)
        if getattr(args, 'copilot_dir', None)
        else None,
        config_path=Path(args.config) if getattr(args, 'config', None) else None,
        agentmaster_home=Path(args.agentmaster_home)
        if getattr(args, 'agentmaster_home', None)
        else None,
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


def _cmd_install(args: argparse.Namespace) -> int:
    unresolved = _unresolved_config(args)
    if unresolved.model and not MODEL_RE.match(unresolved.model):
        print(f'invalid model: {unresolved.model!r}', file=sys.stderr)
        return 1

    document = None
    if unresolved.config_path is not None:
        try:
            document = load_config_document(unresolved.config_path)
        except ConfigError as error:
            print(f'invalid config: {error}', file=sys.stderr)
            return 1

    try:
        resolved = resolve(unresolved, document)
    except ConfigError as error:
        print(f'invalid config: {error}', file=sys.stderr)
        return 1

    for line in resolved.summary_lines():
        print(f'  {line}')

    is_tty = sys.stdin.isatty()
    for target in resolved.targets:
        home = _home(target, resolved)
        model = resolve_model(target, unresolved, is_tty=is_tty, prompt=_prompt_model)
        if not MODEL_RE.match(model):
            print(f'invalid model: {model!r}', file=sys.stderr)
            return 1
        try:
            if target is Target.CLAUDE:
                report = claude.install(ROOT, home, model=model, dry_run=resolved.dry_run)
            else:
                report = copilot.install(
                    ROOT, home, model=model, dry_run=resolved.dry_run
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
        module = claude if target is Target.CLAUDE else copilot
        try:
            report = module.uninstall(_home(target, resolved), dry_run=resolved.dry_run)
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


def main(argv: list[str] | None = None) -> int:
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
            cmd.add_argument(
                '--target', choices=('claude', 'copilot', 'all'), default='all'
            )
            cmd.add_argument('--dry-run', action='store_true')
            cmd.add_argument('--claude-dir', default=None)
            cmd.add_argument('--copilot-dir', default=None)
        if name == 'install':
            cmd.add_argument('--model', default=None)
            cmd.add_argument('--config', default=None)
            cmd.add_argument('--agentmaster-home', default=None)
            cmd.add_argument('--no-input', action='store_true')
    args = parser.parse_args(argv)
    return commands[args.command](args)


if __name__ == '__main__':
    raise SystemExit(main())

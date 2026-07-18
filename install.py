"""agentmaster installer CLI.

Commands:
    python install.py install   --target claude|copilot|all [--dry-run] [--model NAME]
    python install.py uninstall --target claude|copilot|all [--dry-run]
    python install.py validate  --target all
    python install.py sync

`--model` (and, for Copilot, `--git-guard/--no-git-guard`) win when given; when
absent on an interactive terminal the installer asks, otherwise it uses the
per-platform default silently. Destinations honor `CLAUDE_CONFIG_DIR` /
`COPILOT_CONFIG_DIR` and the `--claude-dir` / `--copilot-dir` overrides.
Exit code is 0 on success, 1 on any failure or validation finding.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 14):
    sys.stderr.write(
        'agentmaster installer requires Python 3.14+ (running '
        f'{sys.version_info.major}.{sys.version_info.minor}). '
        'Run it with a newer interpreter, e.g.: uv run python install.py ...\n'
    )
    raise SystemExit(1)

import argparse  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

from installer import claude, copilot  # noqa: E402
from installer.parity import validate  # noqa: E402
from installer.render import sync_workers  # noqa: E402

if TYPE_CHECKING:
    from installer.actions import InstallReport

ROOT = Path(__file__).resolve().parent
MODEL_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
DEFAULT_MODEL = {'claude': 'opus', 'copilot': 'claude-opus-4.8'}
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


def _targets(value: str) -> tuple[str, ...]:
    return ('claude', 'copilot') if value == 'all' else (value,)


def _home(target: str, args: argparse.Namespace) -> Path:
    override = args.claude_dir if target == 'claude' else args.copilot_dir
    if override:
        return Path(override)
    return claude.default_home() if target == 'claude' else copilot.default_home()


def _prompt_model(target: str) -> str:
    menu, choices = MODEL_MENU[target]
    print(menu)
    choice = input('choice [1]: ').strip()
    return choices.get(choice) or input('model: ').strip()


def _resolve_model(target: str, args: argparse.Namespace) -> str:
    if args.model:
        return args.model
    if sys.stdin.isatty():
        return _prompt_model(target)
    return DEFAULT_MODEL[target]


def _resolve_git_guard(args: argparse.Namespace) -> bool:
    if args.git_guard is not None:
        return args.git_guard
    if sys.stdin.isatty():
        reply = input(
            'enable the git-guard hook? (blocks write git for ALL Copilot '
            'sessions; AGENTMASTER_GIT_GUARD=off disables) [Y/n]: '
        ).strip()
        return not reply.lower().startswith('n')
    return True


def _print_report(target: str, report: InstallReport) -> None:
    for status, path in report.entries:
        print(f'  {status:>6}  {path}')
    if report.backup_dir is not None:
        print(f'  backup  {report.backup_dir}')
    print(f'{target}: {report.summary()}')


def _warn_superpowers(target: str, home: Path) -> None:
    plugin_dir = 'plugins' if target == 'claude' else 'installed-plugins'
    if any((home / plugin_dir).glob('*superpowers*')):
        return
    cli = target if target == 'copilot' else 'claude'
    print(f'note: superpowers plugin not detected for {target} — install with:')
    print(f'  {cli} plugin marketplace add obra/superpowers-marketplace')
    print(f'  {cli} plugin install superpowers@superpowers-marketplace')


def _cmd_install(args: argparse.Namespace) -> int:
    if args.model and not MODEL_RE.match(args.model):
        print(f'invalid model: {args.model!r}', file=sys.stderr)
        return 1
    for target in _targets(args.target):
        home = _home(target, args)
        model = _resolve_model(target, args)
        if not MODEL_RE.match(model):
            print(f'invalid model: {model!r}', file=sys.stderr)
            return 1
        try:
            if target == 'claude':
                report = claude.install(ROOT, home, model=model, dry_run=args.dry_run)
            else:
                report = copilot.install(
                    ROOT,
                    home,
                    model=model,
                    dry_run=args.dry_run,
                    git_guard=_resolve_git_guard(args),
                )
        except (OSError, ValueError) as error:
            print(f'{target}: install failed: {error}', file=sys.stderr)
            return 1
        _print_report(target, report)
        _warn_superpowers(target, home)
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    for target in _targets(args.target):
        module = claude if target == 'claude' else copilot
        try:
            report = module.uninstall(_home(target, args), dry_run=args.dry_run)
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
        if name != 'sync':
            cmd.add_argument(
                '--target', choices=('claude', 'copilot', 'all'), default='all'
            )
        if name in ('install', 'uninstall'):
            cmd.add_argument('--dry-run', action='store_true')
            cmd.add_argument('--claude-dir', default=None)
            cmd.add_argument('--copilot-dir', default=None)
        if name == 'install':
            cmd.add_argument('--model', default=None)
            cmd.add_argument(
                '--git-guard',
                action=argparse.BooleanOptionalAction,
                default=None,
                help='wire the Copilot git-guard hook (default: yes)',
            )
    args = parser.parse_args(argv)
    return commands[args.command](args)


if __name__ == '__main__':
    raise SystemExit(main())

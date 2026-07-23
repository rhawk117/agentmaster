"""PreToolUse (skill cost boundary) -> block direct repo work while a phase runs.

Active only while `.agentmaster/.phase` names a phase: the coordinator skills
write the marker at phase start and clear it at phase end, so the boundary
cannot outlive its phase. Paths outside the workspace (the plan-mode plan
file, the session scratchpad) and under `.agentmaster/` stay writable.
"""

import sys
from pathlib import Path

import hooklib

_PATH_TOOLS = frozenset({'read', 'write', 'edit', 'notebookedit', 'grep', 'glob'})
_PATH_KEYS = ('file_path', 'path', 'notebook_path')
_CONTROL_SUBCOMMANDS = frozenset({'run', 'task', 'dispatch', 'context', 'ledger'})
_SHELL_METACHARACTERS = frozenset({';', '|', '&', '`', '$(', '>', '<', '\n'})


def _target_path(args: object) -> str:
    if not isinstance(args, dict):
        return ''
    for key in _PATH_KEYS:
        value = args.get(key)
        if value:
            return str(value)
    return ''


def _is_exempt(target: str, root: Path) -> bool:
    """True when target lies outside the workspace or under .agentmaster/."""
    try:
        resolved = (root / target).resolve()
    except OSError, RuntimeError:
        return False
    if not resolved.is_relative_to(root):
        return True
    return resolved.is_relative_to(root / '.agentmaster')


def _is_control_launcher_command(command: str) -> bool:
    """True only for a bare `agentmaster <control-noun> ...` with no shell chaining.

    Deny-by-default: any chaining/redirection metacharacter, or a first token
    that isn't the launcher, or a second token outside the approved control
    nouns, falls through to the caller's block.
    """
    if any(marker in command for marker in _SHELL_METACHARACTERS):
        return False
    tokens = command.strip().split()
    if len(tokens) < 2 or tokens[1] not in _CONTROL_SUBCOMMANDS:
        return False
    launcher = tokens[0]
    if Path(launcher).name == 'agentmaster':
        return True
    descriptor = hooklib.load_runtime_descriptor()
    return descriptor is not None and launcher == str(descriptor.launcher)


def main() -> int:
    payload = hooklib.read_payload()
    root = hooklib.workspace(payload).resolve()
    phase = hooklib.current_phase(payload)
    if not phase:
        return 0
    try:
        if hooklib.tool_name(payload) == 'bash':
            command = hooklib.tool_args(payload).get('command') or ''
            if _is_control_launcher_command(command):
                return 0
        elif hooklib.tool_name(payload) in _PATH_TOOLS:
            target = _target_path(hooklib.tool_args(payload))
            if target and _is_exempt(target, root):
                return 0
    except Exception as exc:  # noqa: BLE001
        # Fail closed: an unexpected error while a phase is active must block
        # the tool call, not fall through to exit 1 (which lets it proceed).
        sys.stderr.write(f'agentmaster cost boundary: fail-closed after error: {exc}\n')
    sys.stderr.write(
        f'agentmaster cost boundary ({phase} phase): this phase never touches '
        'the repository directly - delegate to scout or code-analyst. Paths '
        'outside the workspace (e.g. ~/.claude/plans) and under .agentmaster/ '
        'are allowed.\n'
    )
    return 2


if __name__ == '__main__':
    raise SystemExit(main())

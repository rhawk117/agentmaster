"""PreToolUse (skill cost boundary) -> block direct repo work while a phase runs.

Active only while `.agentmaster/.phase` names a phase: the coordinator skills
write the marker at phase start and clear it at phase end, so the boundary
cannot outlive its phase. Paths outside the workspace (the plan-mode plan
file, the session scratchpad) and under `.agentmaster/` stay writable.
"""

import sys
from typing import TYPE_CHECKING

import hooklib

if TYPE_CHECKING:
    from pathlib import Path

_PATH_TOOLS = frozenset({'read', 'write', 'edit', 'notebookedit', 'grep', 'glob'})
_PATH_KEYS = ('file_path', 'path', 'notebook_path')


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


def main() -> int:
    payload = hooklib.read_payload()
    root = hooklib.workspace(payload).resolve()
    phase = hooklib.current_phase(root / '.agentmaster')
    if not phase:
        return 0
    if hooklib.tool_name(payload) in _PATH_TOOLS:
        target = _target_path(hooklib.tool_args(payload))
        if target and _is_exempt(target, root):
            return 0
    sys.stderr.write(
        f'agentmaster cost boundary ({phase} phase): this phase never touches '
        'the repository directly - delegate to scout or code-analyst. Paths '
        'outside the workspace (e.g. ~/.claude/plans) and under .agentmaster/ '
        'are allowed.\n'
    )
    return 2


if __name__ == '__main__':
    raise SystemExit(main())

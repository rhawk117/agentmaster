"""Shared helpers for the agentmaster lifecycle hooks."""

import contextlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SAFE_GIT_SUBCOMMANDS = frozenset({
    'status',
    'diff',
    'log',
    'show',
    'blame',
    'rev-parse',
    'ls-files',
    'grep',
    'describe',
    'shortlog',
})

_GIT_SUBCOMMAND_RE = re.compile(r'\bgit\s+(?:-\S+\s+)*([a-z-]+)')


def read_payload() -> dict[str, Any]:
    """Read the hook payload from stdin, returning {} on malformed input."""
    with contextlib.suppress(Exception):
        return json.loads(sys.stdin.read() or '{}')
    return {}


def workspace(payload: dict[str, Any]) -> Path:
    """Resolve the workspace directory the hook operates on."""
    return Path(payload.get('cwd') or Path.cwd())


def agentmaster_dir(payload: dict[str, Any]) -> Path:
    """Return the .agentmaster directory, creating it if needed."""
    am = workspace(payload) / '.agentmaster'
    am.mkdir(exist_ok=True)
    return am


def debug_dump(payload: dict[str, Any]) -> None:
    """Append the raw payload to hook-debug.jsonl when debugging is enabled."""
    if os.environ.get('AGENTMASTER_HOOK_DEBUG'):
        am = agentmaster_dir(payload)
        with (am / 'hook-debug.jsonl').open('a') as f:
            f.write(json.dumps(payload) + '\n')


def append_telemetry(
    payload: dict[str, Any],
    agent: str,
    tokens: str | int = '',
    duration_ms: str | int = '',
) -> None:
    """Append a telemetry row for the given agent to telemetry.md."""
    am = agentmaster_dir(payload)
    with (am / 'telemetry.md').open('a') as f:
        f.write(f'hook,{agent},,{tokens},{duration_ms}\n')


def tool_name(payload: dict[str, Any]) -> str:
    """Return the lowercased tool name, handling camelCase and snake_case."""
    return str(payload.get('toolName', payload.get('tool_name', ''))).lower()


def tool_args(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the tool arguments, handling the four known payload shapes."""
    return (
        payload.get('toolArgs')
        or payload.get('tool_args')
        or payload.get('toolInput')
        or payload.get('tool_input')
        or {}
    )


def first_blocked_git_subcommand(command: str) -> str | None:
    """Return the first git subcommand in command that is not read-only."""
    for m in _GIT_SUBCOMMAND_RE.finditer(command):
        if m.group(1) not in SAFE_GIT_SUBCOMMANDS:
            return m.group(1)
    return None

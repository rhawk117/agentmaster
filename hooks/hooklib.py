"""Shared helpers for the agentmaster lifecycle hooks."""

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, NamedTuple

EVENT_SPOOL_SCHEMA_VERSION = 1
DEFAULT_INGEST_LIMIT = 50


def read_payload() -> dict[str, Any]:
    """Read the hook payload from stdin, returning {} on malformed input."""
    with contextlib.suppress(Exception):
        payload = json.loads(sys.stdin.read() or '{}')
        if isinstance(payload, dict):
            return payload
    return {}


def workspace(payload: dict[str, Any]) -> Path:
    """Resolve the workspace directory the hook operates on."""
    return Path(payload.get('cwd') or Path.cwd())


def agentmaster_dir(payload: dict[str, Any]) -> Path:
    """Return the .agentmaster directory, creating it if needed."""
    am = workspace(payload) / '.agentmaster'
    am.mkdir(exist_ok=True)
    return am


def _sanitize_session_id(raw: str) -> str:
    """Make a harness session id safe as a single path segment.

    Path separators are replaced so the id can't escape the sessions/
    directory; ids that are empty or made only of dots (which could
    otherwise resolve to the current or a parent directory) fall back
    to 'default'.
    """
    sid = raw.strip().replace('/', '_').replace('\\', '_')
    if not sid or set(sid) == {'.'}:
        return 'default'
    return sid


def session_id(payload: dict[str, Any]) -> str:
    """Return the sanitized harness session id, or 'default' when absent."""
    return _sanitize_session_id(str(payload.get('session_id') or ''))


def session_dir(payload: dict[str, Any]) -> Path:
    """Return this session's workspace dir, creating it if needed.

    Layout: .agentmaster/sessions/<harness-session-id>/ holds the
    per-session .phase marker, .starts/ start timestamps, and
    telemetry.md rows, so two sessions in one checkout never clobber
    each other. Reads of .phase and .starts/ fall back to the legacy
    .agentmaster/ root for markers written before this layout existed.
    """
    sdir = agentmaster_dir(payload) / 'sessions' / session_id(payload)
    sdir.mkdir(parents=True, exist_ok=True)
    return sdir


def debug_dump(payload: dict[str, Any]) -> None:
    """Append the raw payload to hook-debug.jsonl when debugging is enabled."""
    if os.environ.get('AGENTMASTER_HOOK_DEBUG'):
        am = agentmaster_dir(payload)
        with (am / 'hook-debug.jsonl').open('a') as f:
            f.write(json.dumps(payload) + '\n')


def current_phase(payload: dict[str, Any]) -> str:
    """Return the active phase named in .phase, or '' when absent/unreadable.

    Reads the session-scoped marker first, falling back to the legacy
    .agentmaster/.phase for markers written before session scoping.
    """
    for phase_file in (
        session_dir(payload) / '.phase',
        agentmaster_dir(payload) / '.phase',
    ):
        try:
            text = phase_file.read_text().strip()
        except OSError:
            continue
        if text:
            return text.split()[0]
    return ''


def append_telemetry(
    payload: dict[str, Any],
    agent: str,
    tokens: str | int = '',
    duration_ms: str | int = '',
    model: str = '',
) -> None:
    """Append a telemetry row for the given agent to the session's telemetry.md."""
    sdir = session_dir(payload)
    phase = current_phase(payload) or 'hook'
    with (sdir / 'telemetry.md').open('a') as f:
        f.write(f'{phase},{agent},{model},{tokens},{duration_ms}\n')


class CompactionContext(NamedTuple):
    """Fields optionally present on a PreCompact hook payload."""

    agent_type: str
    trigger: str
    token_count: str
    session_id: str


def compaction_context(payload: dict[str, Any]) -> CompactionContext:
    """Defensively extract compaction fields from a PreCompact payload.

    Every field degrades to '' (agent_type to 'main') when the provider
    omits it or the payload shape is unexpected; extraction never raises.
    """
    with contextlib.suppress(Exception):
        return CompactionContext(
            agent_type=str(
                payload.get('agent_type') or payload.get('agent_name') or 'main'
            ),
            trigger=str(payload.get('trigger') or ''),
            token_count=str(
                payload.get('token_count') or payload.get('pre_tokens') or ''
            ),
            session_id=str(payload.get('session_id') or payload.get('agent_id') or ''),
        )
    return CompactionContext('main', '', '', '')


def events_dir(payload: dict[str, Any]) -> Path:
    """Return the pending-ledger-events spool directory, creating it if needed."""
    d = agentmaster_dir(payload) / 'events'
    d.mkdir(parents=True, exist_ok=True)
    return d


def spool_event(payload: dict[str, Any], event: dict[str, Any]) -> None:
    """Atomically write one normalized event for later bounded ledger ingestion.

    Hook processes never import the `ledger` package: they run standalone,
    copied without it (SPEC.md §19, §23 Microtask 17), so this writes a
    small versioned JSON file instead of a database row; `ledger.ingestion`
    turns it into typed tables in a later, bounded step. `harness_session_id`
    is `session_id(payload)` so a spooled event lines up with the same
    session identity `session_dir` already uses for telemetry.md/.starts.
    Any failure (unwritable path, disk full) is swallowed so a hook never
    blocks the harness on optional observability (SPEC.md §9, §16.1).
    """
    with contextlib.suppress(Exception):
        events = events_dir(payload)
        record = {
            'schema_version': EVENT_SPOOL_SCHEMA_VERSION,
            'harness_session_id': session_id(payload),
            **event,
        }
        descriptor, tmp_name = tempfile.mkstemp(dir=events, suffix='.json')
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(descriptor, 'w') as f:
                f.write(json.dumps(record))
            tmp_path.replace(events / f'{time.time_ns()}-{os.getpid()}.json')
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise


class RuntimeDescriptor(NamedTuple):
    """The installed Runtime descriptor contract fields, parsed from `runtime.json`."""

    config_path: Path
    launcher: Path
    ledger_path: Path | None
    ledger_enabled: bool
    artifact_dir: Path
    schema_version: int


def load_runtime_descriptor() -> RuntimeDescriptor | None:
    """Load the installed `runtime.json` beside this hook, or `None` on any error.

    `hooklib.py` is installed alongside every other hook file (`installer/
    manifest.py`'s `claude_hooks`/`copilot_hooks`); the descriptor itself
    sits one level up for Claude (`<home>/agentmaster/runtime.json` next to
    `<home>/agentmaster/hooks/`) and beside the hooks for Copilot
    (`<home>/agentmaster-hooks/runtime.json`), so both candidate locations
    relative to this file are checked. Never raises: a missing/malformed
    descriptor (uninstalled dev checkout, corrupt file) fails open by
    returning `None`, exactly like every other hook-side failure mode.
    """
    here = Path(__file__).resolve().parent
    for candidate in (here / 'runtime.json', here.parent / 'runtime.json'):
        with contextlib.suppress(Exception):
            document = json.loads(candidate.read_text(encoding='utf-8'))
            return RuntimeDescriptor(
                config_path=Path(document['config_path']),
                launcher=Path(document['launcher']),
                ledger_path=(
                    Path(document['ledger_path'])
                    if document['ledger_path'] is not None
                    else None
                ),
                ledger_enabled=bool(document['ledger_enabled']),
                artifact_dir=Path(document['artifact_dir']),
                schema_version=int(document['schema_version']),
            )
    return None


def auto_drain(payload: dict[str, Any], *, limit: int = DEFAULT_INGEST_LIMIT) -> None:
    """Fire a bounded, fail-open ingest of this workspace's spooled events.

    Invoked at safe checkpoints (session start, subagent stop, post-compaction,
    Copilot post-agent-tool) right after `spool_event` durably writes an
    event, so the spool never grows unboundedly between manual `agentmaster
    ledger ingest-events` calls. Does nothing when no runtime is installed,
    the ledger is disabled, or the launcher is missing -- a hook must never
    block or fail the harness on optional observability (SPEC.md §9, §16.1).
    Ingestion counts are only surfaced to `hook-debug.jsonl` when
    `AGENTMASTER_HOOK_DEBUG` is set; normal hooks stay silent.
    """
    with contextlib.suppress(Exception):
        descriptor = load_runtime_descriptor()
        if descriptor is None or not descriptor.ledger_enabled:
            return
        if descriptor.ledger_path is None or not descriptor.launcher.is_file():
            return
        result = subprocess.run(  # noqa: S603
            [
                str(descriptor.launcher),
                'ledger',
                'ingest-events',
                '--path',
                str(descriptor.ledger_path),
                '--spool',
                str(events_dir(payload)),
                '--limit',
                str(limit),
                '--json',
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if os.environ.get('AGENTMASTER_HOOK_DEBUG'):
            am = agentmaster_dir(payload)
            with (am / 'hook-debug.jsonl').open('a') as f:
                f.write(
                    json.dumps({
                        'auto_drain_returncode': result.returncode,
                        'auto_drain_stdout': result.stdout,
                        'auto_drain_stderr': result.stderr,
                    })
                    + '\n'
                )


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

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
    with contextlib.suppress(Exception):
        payload = json.loads(sys.stdin.read() or '{}')
        if isinstance(payload, dict):
            return payload
    return {}


def workspace(payload: dict[str, Any]) -> Path:
    return Path(payload.get('cwd') or Path.cwd())


def agentmaster_dir(payload: dict[str, Any]) -> Path:
    am = workspace(payload) / '.agentmaster'
    am.mkdir(exist_ok=True)
    return am


def _sanitize_session_id(raw: str) -> str:
    sid = raw.strip().replace('/', '_').replace('\\', '_')
    if not sid or set(sid) == {'.'}:
        return 'default'
    return sid


def session_id(payload: dict[str, Any]) -> str:
    return _sanitize_session_id(str(payload.get('session_id') or ''))


def session_dir(payload: dict[str, Any]) -> Path:
    sdir = agentmaster_dir(payload) / 'sessions' / session_id(payload)
    sdir.mkdir(parents=True, exist_ok=True)
    return sdir


def debug_dump(payload: dict[str, Any]) -> None:
    if os.environ.get('AGENTMASTER_HOOK_DEBUG'):
        am = agentmaster_dir(payload)
        with (am / 'hook-debug.jsonl').open('a') as f:
            f.write(json.dumps(payload) + '\n')


def current_phase(payload: dict[str, Any]) -> str:
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
    sdir = session_dir(payload)
    phase = current_phase(payload) or 'hook'
    with (sdir / 'telemetry.md').open('a') as f:
        f.write(f'{phase},{agent},{model},{tokens},{duration_ms}\n')


class CompactionContext(NamedTuple):
    agent_type: str
    trigger: str
    token_count: str
    session_id: str


def compaction_context(payload: dict[str, Any]) -> CompactionContext:
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
    d = agentmaster_dir(payload) / 'events'
    d.mkdir(parents=True, exist_ok=True)
    return d


def spool_event(payload: dict[str, Any], event: dict[str, Any]) -> None:
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
    config_path: Path
    launcher: Path
    ledger_path: Path | None
    ledger_enabled: bool
    artifact_dir: Path
    schema_version: int


def load_runtime_descriptor() -> RuntimeDescriptor | None:
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
    return str(payload.get('toolName', payload.get('tool_name', ''))).lower()


def tool_args(payload: dict[str, Any]) -> dict[str, Any]:
    return (
        payload.get('toolArgs')
        or payload.get('tool_args')
        or payload.get('toolInput')
        or payload.get('tool_input')
        or {}
    )

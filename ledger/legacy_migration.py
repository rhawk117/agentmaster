import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.artifact_store import content_address
from ledger.ingestion import resolve_project, upsert_user_session
from ledger.redaction import redact
from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

_TELEMETRY_FIELD_COUNT = 5
_LEGACY_ROOT_SESSION = 'legacy-root'


@dataclass(frozen=True, slots=True)
class LegacyImportRequest:
    harness_session_id: str
    project_id: str
    id_factory: Callable[[], str]
    now: Callable[[], str]
    apply: bool


@dataclass(frozen=True, slots=True)
class LegacyImportReport:
    source: Path
    imported: int
    ambiguous: int
    malformed: int
    redacted: bool
    artifact_id: str | None


def discover_legacy_telemetry_files(workspace: Path) -> list[tuple[Path, str]]:
    am = workspace / '.agentmaster'
    found: list[tuple[Path, str]] = []
    sessions_dir = am / 'sessions'
    if sessions_dir.is_dir():
        for session_dir in sorted(p for p in sessions_dir.iterdir() if p.is_dir()):
            candidate = session_dir / 'telemetry.md'
            if candidate.is_file():
                found.append((candidate, session_dir.name))
    legacy_root = am / 'telemetry.md'
    if legacy_root.is_file():
        found.append((legacy_root, _LEGACY_ROOT_SESSION))
    return found


def _parse_row(line: str) -> tuple[str, str, str, str, str] | None:
    parts = line.split(',')
    if len(parts) != _TELEMETRY_FIELD_COUNT:
        return None
    return parts[0], parts[1], parts[2], parts[3], parts[4]


def _to_optional_int(raw: str) -> tuple[int | None, bool]:
    if raw == '':
        return None, False
    try:
        return int(raw), False
    except ValueError:
        return None, True


def _legacy_run_id(harness_session_id: str) -> str:
    return f'legacy-run:{harness_session_id}'


def _legacy_agent_session_id(harness_session_id: str) -> str:
    return f'legacy-agent-session:{harness_session_id}'


def _register_legacy_artifact(
    connection: sqlite3.Connection,
    source_path: Path,
    content: bytes,
    request: LegacyImportRequest,
) -> str:
    digest = content_address(content)

    def _op(conn: sqlite3.Connection) -> str:
        row = conn.execute(
            'SELECT id FROM ARTIFACT WHERE sha256 = ? AND project_id = ?',
            (digest, request.project_id),
        ).fetchone()
        if row is not None:
            return row[0]
        artifact_id = request.id_factory()
        conn.execute(
            'INSERT INTO ARTIFACT '
            '(id, project_id, sha256, media_type, byte_size, relative_path, '
            'retention_class, redaction_state, created_at) '
            "VALUES (?, ?, ?, 'text/markdown', ?, ?, 'default', 'standard', ?)",
            (
                artifact_id,
                request.project_id,
                digest,
                len(content),
                str(source_path),
                request.now(),
            ),
        )
        return artifact_id

    return run_write_transaction(connection, _op)


def import_telemetry_file(
    connection: sqlite3.Connection, source_path: Path, request: LegacyImportRequest
) -> LegacyImportReport:
    text = source_path.read_text(encoding='utf-8')
    redacted_bytes = redact(text.encode('utf-8'))
    was_redacted = redacted_bytes != text.encode('utf-8')
    redacted_text = redacted_bytes.decode('utf-8', errors='replace')

    imported = 0
    ambiguous = 0
    malformed = 0
    rows: list[tuple[str, str, str, int | None, int | None]] = []
    for line in redacted_text.splitlines():
        if not line.strip():
            continue
        parsed = _parse_row(line)
        if parsed is None:
            malformed += 1
            continue
        phase, agent, model, tokens_raw, duration_raw = parsed
        tokens, tokens_ambiguous = _to_optional_int(tokens_raw)
        duration_ms, duration_ambiguous = _to_optional_int(duration_raw)
        if tokens_ambiguous or duration_ambiguous:
            ambiguous += 1
        rows.append((phase, agent, model, tokens, duration_ms))
        imported += 1

    if not request.apply:
        return LegacyImportReport(
            source=source_path,
            imported=imported,
            ambiguous=ambiguous,
            malformed=malformed,
            redacted=was_redacted,
            artifact_id=None,
        )

    run_id = _legacy_run_id(request.harness_session_id)
    agent_session_id = _legacy_agent_session_id(request.harness_session_id)
    user_session_id = upsert_user_session(
        connection,
        request.harness_session_id,
        id_factory=request.id_factory,
        now=request.now,
    )

    def _op(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT OR IGNORE INTO RUN '
            '(id, project_id, user_session_id, delivery_mode, state, started_at) '
            "VALUES (?, ?, ?, 'local', 'Complete', ?)",
            (run_id, request.project_id, user_session_id, request.now()),
        )
        conn.execute(
            'INSERT OR IGNORE INTO AGENT_SESSION '
            '(id, run_id, role, provider, model, state, started_at) '
            "VALUES (?, ?, 'legacy-import', 'claude', '', 'complete', ?)",
            (agent_session_id, run_id, request.now()),
        )
        for index, (phase, agent, model, tokens, duration_ms) in enumerate(rows):
            row_digest = hashlib.sha256(
                f'{source_path}:{index}:{phase}:{agent}:{model}:{tokens}:{duration_ms}'.encode()
            ).hexdigest()
            conn.execute(
                'INSERT OR IGNORE INTO MODEL_CALL '
                '(id, agent_session_id, provider_call_id, model, billed_tokens, '
                'duration_ms, provider_usage_json, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    f'legacy-model-call:{row_digest}',
                    agent_session_id,
                    row_digest,
                    model or agent,
                    tokens,
                    duration_ms,
                    json.dumps({'legacy_phase': phase, 'legacy_agent': agent}),
                    request.now(),
                ),
            )

    run_write_transaction(connection, _op)
    artifact_id = _register_legacy_artifact(
        connection, source_path, redacted_bytes, request
    )
    return LegacyImportReport(
        source=source_path,
        imported=imported,
        ambiguous=ambiguous,
        malformed=malformed,
        redacted=was_redacted,
        artifact_id=artifact_id,
    )


def import_legacy_workspace(
    connection: sqlite3.Connection,
    workspace: Path,
    *,
    id_factory: Callable[[], str],
    now: Callable[[], str],
    apply: bool,
) -> list[LegacyImportReport]:
    project_id = (
        resolve_project(
            connection,
            canonical_root=str(workspace.resolve()),
            id_factory=id_factory,
            now=now,
        )
        if apply
        else ''
    )
    return [
        import_telemetry_file(
            connection,
            path,
            LegacyImportRequest(
                harness_session_id=harness_session_id,
                project_id=project_id,
                id_factory=id_factory,
                now=now,
                apply=apply,
            ),
        )
        for path, harness_session_id in discover_legacy_telemetry_files(workspace)
    ]

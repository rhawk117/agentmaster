"""Normalize spooled hook events into typed ledger rows (SPEC.md §16.3, §17, §23 M17).

Hooks never write to the ledger directly (they run standalone, without the
`ledger` package - see `hooklib.spool_event`); this module is the bounded
ingestion step that drains `ledger.event_spool`'s JSON files into USER_SESSION,
PROJECT, RUN, AGENT_SESSION, MODEL_CALL, and COMPACTION_EVENT rows.

Ingestion owns USER_SESSION row creation: every dependent row is only ever
recorded after `upsert_user_session` resolves, so replaying two events for
the same harness session never creates a second USER_SESSION. Every id
derived from event identity (agent id, event kind) is deterministic, so
re-ingesting an already-processed spool file is a no-op rather than a
duplicate row (`INSERT OR IGNORE` plus MODEL_CALL's existing
`ux_model_call_agent_session_provider_call` unique index). AGENT_SESSION's
`entrypoint_id` resolves the event's agent-type name against active
`kind='agent'` ENTRYPOINT rows (SPEC.md §23 Microtask 19); an unresolved
name stays NULL rather than guessing.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ledger.event_spool import SpooledEvent, discard, read_events
from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class IngestReport:
    """Counts from one `ingest_pending_events` call."""

    ingested: int
    malformed: int
    unsupported: int
    failed: int


def resolve_project(
    connection: sqlite3.Connection,
    *,
    canonical_root: str,
    id_factory: Callable[[], str],
    now: Callable[[], str],
) -> str:
    """Find or create the PROJECT row for `canonical_root`, else touch `last_seen_at`.

    `fingerprint` is `canonical_root` itself: a hook payload carries no git
    remote identity to fingerprint on, so this is a deliberate simplification
    rather than the full root-aliasing identity resolution described in
    SPEC.md §17.3 (not implemented anywhere yet in this codebase).
    """

    def _op(conn: sqlite3.Connection) -> str:
        row = conn.execute(
            'SELECT id FROM PROJECT WHERE fingerprint = ?', (canonical_root,)
        ).fetchone()
        if row is not None:
            conn.execute(
                'UPDATE PROJECT SET last_seen_at = ? WHERE id = ?', (now(), row[0])
            )
            return row[0]
        project_id = id_factory()
        conn.execute(
            'INSERT INTO PROJECT '
            '(id, canonical_root, fingerprint, created_at, last_seen_at) '
            'VALUES (?, ?, ?, ?, ?)',
            (project_id, canonical_root, canonical_root, now(), now()),
        )
        return project_id

    return run_write_transaction(connection, _op)


def upsert_user_session(
    connection: sqlite3.Connection,
    harness_session_id: str,
    *,
    id_factory: Callable[[], str],
    now: Callable[[], str],
) -> str:
    """Find or create the USER_SESSION row for `harness_session_id`.

    The SELECT-then-conditionally-INSERT happens inside one
    `run_write_transaction` operation, under the `BEGIN IMMEDIATE` write
    lock it takes before calling `operation` - so two ingestion calls for
    the same harness session can never race into two rows.
    """

    def _op(conn: sqlite3.Connection) -> str:
        row = conn.execute(
            'SELECT user_session_id FROM USER_SESSION WHERE harness_session_id = ?',
            (harness_session_id,),
        ).fetchone()
        if row is not None:
            return row[0]
        user_session_id = id_factory()
        conn.execute(
            'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
            'VALUES (?, ?, ?)',
            (user_session_id, harness_session_id, now()),
        )
        return user_session_id

    return run_write_transaction(connection, _op)


def resolve_run(
    connection: sqlite3.Connection,
    *,
    project_id: str,
    user_session_id: str,
    id_factory: Callable[[], str],
    now: Callable[[], str],
) -> str:
    """Reuse this session's open RUN (no `ended_at`), else start a new one.

    Full run lifecycle management (state transitions, closing a run) is
    Microtask 19's orchestrator control plane; ingestion only needs a
    stable `run_id` to hang AGENT_SESSION/MODEL_CALL rows on.
    """

    def _op(conn: sqlite3.Connection) -> str:
        row = conn.execute(
            'SELECT id FROM RUN WHERE user_session_id = ? AND ended_at IS NULL '
            'ORDER BY started_at DESC LIMIT 1',
            (user_session_id,),
        ).fetchone()
        if row is not None:
            return row[0]
        run_id = id_factory()
        conn.execute(
            'INSERT INTO RUN '
            '(id, project_id, user_session_id, delivery_mode, state, started_at) '
            "VALUES (?, ?, ?, 'local', 'Executing', ?)",
            (run_id, project_id, user_session_id, now()),
        )
        return run_id

    return run_write_transaction(connection, _op)


def _agent_session_id(run_id: str, agent_key: str) -> str:
    return f'agent-session:{run_id}:{agent_key}'


def resolve_agent_entrypoint_id(
    connection: sqlite3.Connection, agent_name: str
) -> str | None:
    """Resolve `agent_name` to its active `kind='agent'` ENTRYPOINT id, or `None`.

    `None` when `agent_name` has no matching active row (not yet seeded,
    retired, or never listed by the installer manifest) rather than a
    synthetic id (SPEC.md §16.3: never fabricate).
    """
    row = connection.execute(
        "SELECT id FROM ENTRYPOINT WHERE kind = 'agent' AND name = ? AND active = 1",
        (agent_name,),
    ).fetchone()
    return row[0] if row is not None else None


def _nonneg_int(value: str | float | None) -> int | None:
    """Return `value` as a non-negative int.

    `None` on anything else, never fabricated (SPEC.md §16.3): an absent
    or unparseable value stays NULL rather than becoming 0 or a guess.
    """
    if value is None:
        return None
    try:
        parsed = int(value)
    except TypeError, ValueError:
        return None
    return parsed if parsed >= 0 else None


def _ingest_agent_session_event(
    connection: sqlite3.Connection,
    event: SpooledEvent,
    *,
    id_factory: Callable[[], str],
    now: Callable[[], str],
) -> None:
    fields = event.fields
    user_session_id = upsert_user_session(
        connection, event.harness_session_id, id_factory=id_factory, now=now
    )
    project_id = resolve_project(
        connection,
        canonical_root=str(fields.get('cwd') or ''),
        id_factory=id_factory,
        now=now,
    )
    run_id = resolve_run(
        connection,
        project_id=project_id,
        user_session_id=user_session_id,
        id_factory=id_factory,
        now=now,
    )
    agent_id = str(fields.get('agent_id') or '')
    agent_session_id = _agent_session_id(run_id, agent_id or id_factory())
    role = str(fields.get('role') or 'unknown')
    model = str(fields.get('model') or '')
    duration_ms = _nonneg_int(fields.get('duration_ms'))
    total_tokens = _nonneg_int(fields.get('total_tokens'))
    model_call_id = f'model-call:{agent_session_id}'
    provider_usage_json = (
        json.dumps({'total_tokens': total_tokens}) if total_tokens is not None else None
    )

    def _op(conn: sqlite3.Connection) -> None:
        entrypoint_id = resolve_agent_entrypoint_id(conn, role)
        conn.execute(
            'INSERT OR IGNORE INTO AGENT_SESSION '
            '(id, run_id, entrypoint_id, role, provider, model, state, started_at, '
            'ended_at) '
            "VALUES (?, ?, ?, ?, 'claude', ?, 'complete', ?, ?)",
            (agent_session_id, run_id, entrypoint_id, role, model, now(), now()),
        )
        conn.execute(
            'INSERT OR IGNORE INTO MODEL_CALL '
            '(id, agent_session_id, provider_call_id, model, duration_ms, '
            'provider_usage_json, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (
                model_call_id,
                agent_session_id,
                model_call_id,
                model,
                duration_ms,
                provider_usage_json,
                now(),
            ),
        )

    run_write_transaction(connection, _op)


def _snapshot_manifest_digest(snapshot_dir: Path) -> tuple[str, int]:
    """Hash a deterministic listing of `snapshot_dir`'s files, not their bytes.

    Cheap and reproducible (an `os.stat` walk, no file reads); a full
    content hash of a whole directory tree is unnecessary for linking a
    COMPACTION_EVENT to an ARTIFACT and would be far more costly at ingest
    time than this task's scope justifies.
    """
    entries = sorted(
        (str(p.relative_to(snapshot_dir)), p.stat().st_size)
        for p in snapshot_dir.rglob('*')
        if p.is_file()
    )
    manifest = json.dumps(entries, sort_keys=True).encode('utf-8')
    return hashlib.sha256(manifest).hexdigest(), sum(size for _, size in entries)


def _resolve_snapshot_artifact(
    connection: sqlite3.Connection,
    *,
    project_id: str,
    snapshot_dir: str | None,
    id_factory: Callable[[], str],
    now: Callable[[], str],
) -> str | None:
    if not snapshot_dir:
        return None
    root = Path(snapshot_dir)
    if not root.is_dir():
        return None
    digest, byte_size = _snapshot_manifest_digest(root)

    def _op(conn: sqlite3.Connection) -> str:
        row = conn.execute(
            'SELECT id FROM ARTIFACT WHERE sha256 = ? AND project_id = ?',
            (digest, project_id),
        ).fetchone()
        if row is not None:
            return row[0]
        artifact_id = id_factory()
        conn.execute(
            'INSERT INTO ARTIFACT '
            '(id, project_id, sha256, media_type, byte_size, relative_path, '
            'retention_class, redaction_state, created_at) '
            "VALUES (?, ?, ?, 'application/x-agentmaster-compaction-snapshot', ?, ?, "
            "'default', 'standard', ?)",
            (artifact_id, project_id, digest, byte_size, str(root), now()),
        )
        return artifact_id

    return run_write_transaction(connection, _op)


def _ingest_compaction_event(
    connection: sqlite3.Connection,
    event: SpooledEvent,
    *,
    id_factory: Callable[[], str],
    now: Callable[[], str],
) -> None:
    fields = event.fields
    user_session_id = upsert_user_session(
        connection, event.harness_session_id, id_factory=id_factory, now=now
    )
    project_id = resolve_project(
        connection,
        canonical_root=str(fields.get('cwd') or ''),
        id_factory=id_factory,
        now=now,
    )
    run_id = resolve_run(
        connection,
        project_id=project_id,
        user_session_id=user_session_id,
        id_factory=id_factory,
        now=now,
    )
    agent_key = str(fields.get('agent_type') or 'main')
    agent_session_id = _agent_session_id(run_id, agent_key)
    trigger = str(fields.get('trigger') or '')
    pre_tokens = _nonneg_int(fields.get('token_count'))
    snapshot_artifact_id = _resolve_snapshot_artifact(
        connection,
        project_id=project_id,
        snapshot_dir=fields.get('snapshot_dir'),
        id_factory=id_factory,
        now=now,
    )
    compaction_id = f'compaction:{agent_session_id}:{trigger}:{pre_tokens}'

    def _op(conn: sqlite3.Connection) -> None:
        entrypoint_id = resolve_agent_entrypoint_id(conn, agent_key)
        conn.execute(
            'INSERT OR IGNORE INTO AGENT_SESSION '
            '(id, run_id, entrypoint_id, role, provider, model, state, started_at) '
            "VALUES (?, ?, ?, ?, 'claude', '', 'active', ?)",
            (agent_session_id, run_id, entrypoint_id, agent_key, now()),
        )
        conn.execute(
            'INSERT OR IGNORE INTO COMPACTION_EVENT '
            '(id, agent_session_id, trigger, pre_tokens, snapshot_artifact_id, '
            'created_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (
                compaction_id,
                agent_session_id,
                trigger,
                pre_tokens,
                snapshot_artifact_id,
                now(),
            ),
        )

    run_write_transaction(connection, _op)


_HANDLERS: dict[str, Callable[..., None]] = {
    'agent_session': _ingest_agent_session_event,
    'compaction': _ingest_compaction_event,
}


def ingest_pending_events(
    connection: sqlite3.Connection,
    spool_dir: Path,
    *,
    id_factory: Callable[[], str],
    now: Callable[[], str],
) -> IngestReport:
    """Drain every spooled event in `spool_dir` into ledger rows.

    Successfully ingested and malformed/unsupported files are discarded
    (replaying a malformed file cannot succeed later, and an unsupported
    `kind` will never gain a handler retroactively). A file that raises a
    `sqlite3.Error` during ingestion is left in place for a future retry.
    """
    result = read_events(spool_dir)
    ingested = 0
    unsupported = 0
    failed = 0
    to_discard = list(result.malformed)
    for event in result.events:
        handler = _HANDLERS.get(event.kind)
        if handler is None:
            unsupported += 1
            to_discard.append(event.path)
            continue
        try:
            handler(connection, event, id_factory=id_factory, now=now)
        except sqlite3.Error:
            failed += 1
            continue
        ingested += 1
        to_discard.append(event.path)
    discard(to_discard)
    return IngestReport(
        ingested=ingested,
        malformed=len(result.malformed),
        unsupported=unsupported,
        failed=failed,
    )

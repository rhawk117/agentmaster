"""Thin JSON wrappers over the RUN/TASK orchestration surface (SPEC.md §9, §9.1).

`agentmaster/cli.py` parses arguments and prints JSON only; every legality
check and state mutation lives in `ledger.orchestrator_state`,
`ledger.orchestrator_preflight`, and `ledger.orchestrator_recovery` (already
directly testable without a subprocess). This module adds the one piece
those don't provide: reusing an existing open RUN for a user session
(RUN-reconciliation contract) and writing that RUN id into the session's
`.run_id` marker so `ledger.ingestion.resolve_run`'s `.run_id`-preferring
lookup and this CLI's own dispatch calls agree on exactly one RUN.
"""

import json
import os
import sqlite3
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from hooks.hooklib import session_dir
from ledger.artifact_store import ArtifactStore
from ledger.connection import connect
from ledger.evidence import CommandCapture, record_command_evidence
from ledger.ingestion import resolve_project, upsert_user_session
from ledger.orchestrator_preflight import PreflightCheck, run_preflight
from ledger.orchestrator_recovery import recover_run
from ledger.orchestrator_state import (
    IllegalTransitionError,
    RunNotFoundError,
    RunTransitionInput,
    TaskNotFoundError,
    TaskTransitionInput,
    transition_run,
    transition_task,
)
from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _emit(payload: object) -> None:
    print(json.dumps(payload))


def _report_illegal_transition(error: IllegalTransitionError) -> int:
    _emit({'error': str(error)})
    return 1


def _report_not_found(error: RunNotFoundError | TaskNotFoundError) -> int:
    _emit({'error': str(error)})
    return 1


def _report_integrity_error(error: sqlite3.IntegrityError) -> int:
    """A referenced row (e.g. an agent-session lease) does not exist -- fail
    closed with a JSON error rather than letting the traceback surface.
    """
    _emit({'error': str(error)})
    return 1


def _write_run_id_marker(
    *, harness_session_id: str, project_root: str, run_id: str
) -> None:
    """Atomically persist `run_id` to this session's `.run_id` marker.

    Write-to-temp-then-rename, matching `hooklib.spool_event`'s and
    `installer.actions._write_atomic`'s pattern -- a reader never observes a
    partially written marker.
    """
    sdir = session_dir({'session_id': harness_session_id, 'cwd': project_root})
    descriptor, tmp_name = tempfile.mkstemp(dir=sdir, suffix='.tmp')
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(descriptor, 'w') as f:
            f.write(run_id)
        tmp_path.replace(sdir / '.run_id')
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


@dataclass(frozen=True, slots=True)
class _RunStartInput:
    """Bundles a `_reuse_or_start_run` call's arguments under the project's
    max-arguments lint (PLR0913), mirroring `ledger.ingestion._RunResolutionContext`.
    """

    project_id: str
    user_session_id: str
    delivery_mode: str
    plan_id: str | None
    base_sha: str | None
    id_factory: Callable[[], str]
    now: Callable[[], str]


def _reuse_or_start_run(
    connection: sqlite3.Connection, start: _RunStartInput
) -> tuple[str, bool]:
    """Reuse this session's open RUN, else insert a new one in `'Planned'`.

    Uses the exact same "no `ended_at`" lookup `ledger.ingestion.resolve_run`
    uses, so whichever of `run start` or a telemetry drain runs first, the
    other reuses the same RUN rather than inserting a second one
    (RUN-reconciliation contract).
    """

    def _op(conn: sqlite3.Connection) -> tuple[str, bool]:
        row = conn.execute(
            'SELECT id FROM RUN WHERE user_session_id = ? AND ended_at IS NULL '
            'ORDER BY started_at DESC LIMIT 1',
            (start.user_session_id,),
        ).fetchone()
        if row is not None:
            return row[0], False
        run_id = start.id_factory()
        conn.execute(
            'INSERT INTO RUN '
            '(id, project_id, user_session_id, plan_id, delivery_mode, state, '
            'base_sha, started_at) '
            "VALUES (?, ?, ?, ?, ?, 'Planned', ?, ?)",
            (
                run_id,
                start.project_id,
                start.user_session_id,
                start.plan_id,
                start.delivery_mode,
                start.base_sha,
                start.now(),
            ),
        )
        return run_id, True

    return run_write_transaction(connection, _op)


def cmd_run_start(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        id_factory = lambda: str(uuid.uuid4())  # noqa: E731
        project_id = resolve_project(
            connection,
            canonical_root=args.project_root,
            id_factory=id_factory,
            now=_now,
        )
        user_session_id = upsert_user_session(
            connection, args.harness_session_id, id_factory=id_factory, now=_now
        )
        run_id, created = _reuse_or_start_run(
            connection,
            _RunStartInput(
                project_id=project_id,
                user_session_id=user_session_id,
                delivery_mode=args.delivery_mode,
                plan_id=args.plan_id,
                base_sha=args.base_sha,
                id_factory=id_factory,
                now=_now,
            ),
        )
        _write_run_id_marker(
            harness_session_id=args.harness_session_id,
            project_root=args.project_root,
            run_id=run_id,
        )
    finally:
        connection.close()
    _emit({'run_id': run_id, 'created': created, 'project_id': project_id})
    return 0


def cmd_run_preflight(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        checks = [
            PreflightCheck(name=name, passed=passed == 'true', detail=detail or '')
            for name, passed, detail in (
                raw.split(':', 2) if raw.count(':') >= 2 else (*raw.split(':', 1), '')
                for raw in args.check
            )
        ]
        try:
            result = run_preflight(
                connection,
                args.run_id,
                checks,
                now=_now(),
                id_factory=lambda: str(uuid.uuid4()),
            )
        except (RunNotFoundError, TaskNotFoundError) as error:
            return _report_not_found(error)
        except IllegalTransitionError as error:
            return _report_illegal_transition(error)
    finally:
        connection.close()
    _emit(asdict(result))
    return 0 if result.passed else 1


def cmd_run_transition(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        try:
            transition_run(
                connection,
                args.run_id,
                args.to_state,
                RunTransitionInput(
                    now=_now(), id_factory=lambda: str(uuid.uuid4()), reason=args.reason
                ),
            )
        except (RunNotFoundError, TaskNotFoundError) as error:
            return _report_not_found(error)
        except IllegalTransitionError as error:
            return _report_illegal_transition(error)
    finally:
        connection.close()
    _emit({'run_id': args.run_id, 'state': args.to_state})
    return 0


def cmd_run_recover(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        try:
            report = recover_run(
                connection, args.run_id, now=_now(), id_factory=lambda: str(uuid.uuid4())
            )
        except RunNotFoundError as error:
            return _report_not_found(error)
    finally:
        connection.close()
    _emit(asdict(report))
    return 0


def _parse_depends_on(raw: str) -> tuple[str, str]:
    task_id, _, kind = raw.partition(':')
    return task_id, kind or 'blocks'


def cmd_task_register(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    task_id = args.task_id or f'task:{args.run_id}:{args.sequence_no}'

    def _op(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT OR IGNORE INTO TASK '
            '(id, run_id, parent_task_id, title, state, risk_level, sequence_no, '
            'acceptance_json, required_evidence_json) '
            "VALUES (?, ?, ?, ?, 'ready', ?, ?, ?, ?)",
            (
                task_id,
                args.run_id,
                args.parent_task_id,
                args.title,
                args.risk_level,
                args.sequence_no,
                args.acceptance_json,
                args.required_evidence_json,
            ),
        )
        for raw in args.depends_on:
            depends_on_task_id, kind = _parse_depends_on(raw)
            conn.execute(
                'INSERT OR IGNORE INTO TASK_DEPENDENCY '
                '(task_id, depends_on_task_id, dependency_kind) VALUES (?, ?, ?)',
                (task_id, depends_on_task_id, kind),
            )

    try:
        try:
            run_write_transaction(connection, _op)
        except sqlite3.IntegrityError as error:
            return _report_integrity_error(error)
    finally:
        connection.close()
    _emit({'task_id': task_id, 'run_id': args.run_id})
    return 0


def cmd_task_transition(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        try:
            transition_task(
                connection,
                args.task_id,
                args.to_state,
                TaskTransitionInput(
                    now=_now(),
                    id_factory=lambda: str(uuid.uuid4()),
                    reason=args.reason,
                    lease_agent_session_id=args.lease_agent_session_id,
                ),
            )
        except (RunNotFoundError, TaskNotFoundError) as error:
            return _report_not_found(error)
        except IllegalTransitionError as error:
            return _report_illegal_transition(error)
        except sqlite3.IntegrityError as error:
            return _report_integrity_error(error)
    finally:
        connection.close()
    _emit({'task_id': args.task_id, 'state': args.to_state})
    return 0


def cmd_task_record_evidence(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    store = ArtifactStore(Path(args.artifact_root))
    raw_output = (
        sys.stdin.buffer.read()
        if args.output_file == '-'
        else Path(args.output_file).read_bytes()
    )
    capture = CommandCapture(
        evidence_id=str(uuid.uuid4()),
        artifact_id=str(uuid.uuid4()),
        project_id=args.project_id,
        run_id=args.run_id,
        task_id=args.task_id,
        criterion_id=args.criterion_id,
        evidence_kind=args.evidence_kind,
        command=args.command,
        exit_code=args.exit_code,
        commit_sha=args.commit_sha,
        summary=args.summary,
        media_type='text/plain',
        retention_class='default',
        raw_output=raw_output,
        created_at=_now(),
    )
    try:
        record = record_command_evidence(connection, store, capture)
    finally:
        connection.close()
    _emit(asdict(record))
    return 0


def cmd_dispatch_acquire(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        try:
            transition_task(
                connection,
                args.task_id,
                'running',
                TaskTransitionInput(
                    now=_now(),
                    id_factory=lambda: str(uuid.uuid4()),
                    reason=args.reason,
                    lease_agent_session_id=args.lease_agent_session_id,
                ),
            )
        except (RunNotFoundError, TaskNotFoundError) as error:
            return _report_not_found(error)
        except IllegalTransitionError as error:
            return _report_illegal_transition(error)
        except sqlite3.IntegrityError as error:
            return _report_integrity_error(error)
    finally:
        connection.close()
    _emit({
        'task_id': args.task_id,
        'state': 'running',
        'lease_agent_session_id': args.lease_agent_session_id,
    })
    return 0


def cmd_dispatch_release(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        try:
            transition_task(
                connection,
                args.task_id,
                args.to_state,
                TaskTransitionInput(
                    now=_now(), id_factory=lambda: str(uuid.uuid4()), reason=args.reason
                ),
            )
        except (RunNotFoundError, TaskNotFoundError) as error:
            return _report_not_found(error)
        except IllegalTransitionError as error:
            return _report_illegal_transition(error)
    finally:
        connection.close()
    _emit({'task_id': args.task_id, 'state': args.to_state})
    return 0

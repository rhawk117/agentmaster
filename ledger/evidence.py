from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.redaction import redact

if TYPE_CHECKING:
    import sqlite3

    from ledger.artifact_store import ArtifactStore
    from ledger.redaction import RedactionPolicy

DEFAULT_PREVIEW_BYTES = 4096


@dataclass(frozen=True, slots=True)
class CommandCapture:
    evidence_id: str
    artifact_id: str
    project_id: str
    run_id: str
    task_id: str | None
    criterion_id: str | None
    evidence_kind: str
    command: str | None
    exit_code: int
    commit_sha: str | None
    summary: str | None
    media_type: str
    retention_class: str
    raw_output: bytes
    created_at: str


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    artifact_id: str
    sha256: str
    stored_full: bool


def record_command_evidence(
    connection: sqlite3.Connection,
    store: ArtifactStore,
    capture: CommandCapture,
    *,
    policy: RedactionPolicy | None = None,
    preview_bytes: int = DEFAULT_PREVIEW_BYTES,
) -> EvidenceRecord:
    redacted = redact(capture.raw_output, policy)
    stored_full = capture.exit_code != 0
    stored_bytes = redacted if stored_full else redacted[:preview_bytes]
    write = store.put(stored_bytes)

    connection.execute(
        'INSERT INTO ARTIFACT '
        '(id, project_id, sha256, media_type, byte_size, relative_path, '
        'retention_class, redaction_state, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            capture.artifact_id,
            capture.project_id,
            write.sha256,
            capture.media_type,
            write.byte_size,
            write.relative_path,
            capture.retention_class,
            'redacted',
            capture.created_at,
        ),
    )
    connection.execute(
        'INSERT INTO EVIDENCE '
        '(id, run_id, task_id, artifact_id, evidence_kind, criterion_id, command, '
        'exit_code, commit_sha, summary, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            capture.evidence_id,
            capture.run_id,
            capture.task_id,
            capture.artifact_id,
            capture.evidence_kind,
            capture.criterion_id,
            capture.command,
            capture.exit_code,
            capture.commit_sha,
            capture.summary,
            capture.created_at,
        ),
    )
    connection.commit()
    return EvidenceRecord(
        evidence_id=capture.evidence_id,
        artifact_id=capture.artifact_id,
        sha256=write.sha256,
        stored_full=stored_full,
    )

"""Structured independent review recording (SPEC.md §20.3, §23 Microtask 21).

`ReviewResult` mirrors the reviewer's machine-readable response exactly:
`schema_version`, `reviewed_sha`, `verdict`, `findings`, `evidence_gaps`, and
`summary`. `validate_review_result` enforces every §20.3 acceptance rule
before anything is written -- "a malformed result is a failed review, never
GOOD" -- so a caller never records a half-valid review. `record_review`
persists the reviewer's full raw JSON as one content-addressed ARTIFACT
(evidence_gaps has no ERD column or table of its own, so it travels with the
rest of the raw result) and each finding as its own REVIEW_FINDING row, which
`v_unresolved_review_findings` (§18) queries independently of the artifact.
"""

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from ledger.artifact_store import ArtifactStore

SCHEMA_VERSION = 1
VALID_VERDICTS = frozenset({'GOOD', 'NEEDS_FIXES'})
_SHA_RE = re.compile(r'^[0-9a-f]{40}$')


class MalformedReviewError(ValueError):
    """The reviewer's result fails SPEC.md §20.3 shape or identity validation."""


@dataclass(frozen=True, slots=True)
class ReviewFindingInput:
    """One finding from the reviewer's structured result (SPEC.md §17.1 ERD)."""

    severity: str
    summary: str
    criterion_id: str | None = None
    file_path: str | None = None
    line_no: int | None = None
    evidence_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """The reviewer's full machine-readable response (SPEC.md §20.3)."""

    schema_version: int
    reviewed_sha: str
    verdict: str
    findings: tuple[ReviewFindingInput, ...]
    evidence_gaps: tuple[str, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class RecordReviewInput:
    """Everything besides the reviewer's own result a `record_review` call needs."""

    review_id: str
    delivery_attempt_id: str
    reviewer_session_id: str
    project_id: str
    now: str
    id_factory: Callable[[], str]
    artifact_media_type: str = 'application/json'
    artifact_retention_class: str = 'review-result'


@dataclass(frozen=True, slots=True)
class RecordedReview:
    """The persisted result of `record_review`."""

    review_id: str
    summary_artifact_id: str
    finding_ids: tuple[str, ...]


def _validate_finding(finding: ReviewFindingInput, index: int) -> None:
    if not finding.severity:
        raise MalformedReviewError(f'findings[{index}].severity is required')
    if not finding.summary:
        raise MalformedReviewError(f'findings[{index}].summary is required')
    if finding.line_no is not None and finding.line_no < 0:
        raise MalformedReviewError(f'findings[{index}].line_no must be non-negative')


def validate_review_result(result: ReviewResult) -> None:
    """Validate `result` against every SPEC.md §20.3 shape rule.

    Raises
    ------
    MalformedReviewError
        `schema_version` is unsupported, `reviewed_sha` is not a 40-hex
        commit, `verdict` is outside `{GOOD, NEEDS_FIXES}`, or any finding
        is missing its required `severity`/`summary`.
    """
    if result.schema_version != SCHEMA_VERSION:
        raise MalformedReviewError(
            f'schema_version {result.schema_version!r} is not supported '
            f'(expected {SCHEMA_VERSION})'
        )
    if not _SHA_RE.fullmatch(result.reviewed_sha or ''):
        raise MalformedReviewError(
            f'reviewed_sha {result.reviewed_sha!r} is not a 40-hex commit SHA'
        )
    if result.verdict not in VALID_VERDICTS:
        raise MalformedReviewError(
            f'verdict {result.verdict!r} is not one of {sorted(VALID_VERDICTS)}'
        )
    for index, finding in enumerate(result.findings):
        _validate_finding(finding, index)


def _validate_reviewer_identity(
    connection: sqlite3.Connection, reviewer_session_id: str
) -> None:
    """A review must be attributed to a real, independent reviewer session.

    Raises
    ------
    MalformedReviewError
        No AGENT_SESSION row exists for `reviewer_session_id`, or that
        session's role is not `'reviewer'` -- a prompt cannot impersonate a
        completed review by naming an implementer's own session.
    """
    row = connection.execute(
        'SELECT role FROM AGENT_SESSION WHERE id = ?', (reviewer_session_id,)
    ).fetchone()
    if row is None:
        raise MalformedReviewError(
            f'reviewer_session_id {reviewer_session_id!r} has no AGENT_SESSION row'
        )
    if row[0] != 'reviewer':
        raise MalformedReviewError(
            f'reviewer_session_id {reviewer_session_id!r} has role {row[0]!r}, not '
            "'reviewer'"
        )


def record_review(
    connection: sqlite3.Connection,
    store: ArtifactStore,
    review_input: RecordReviewInput,
    result: ReviewResult,
) -> RecordedReview:
    """Validate and persist one reviewer result as REVIEW + REVIEW_FINDING rows.

    Validates the result shape and the reviewer's identity before writing
    anything (SPEC.md §20.3: "a malformed result is a failed review, never
    GOOD"). The full raw result -- including `evidence_gaps`, which has no
    relational column of its own -- is stored as one content-addressed
    ARTIFACT referenced by `REVIEW.summary_artifact_id`.

    Raises
    ------
    MalformedReviewError
        `result` fails `validate_review_result`, or `review_input.
        reviewer_session_id` is not an existing session with role
        `'reviewer'`.
    """
    validate_review_result(result)
    _validate_reviewer_identity(connection, review_input.reviewer_session_id)

    raw = json.dumps({
        'schema_version': result.schema_version,
        'reviewed_sha': result.reviewed_sha,
        'verdict': result.verdict,
        'findings': [
            {
                'severity': f.severity,
                'summary': f.summary,
                'criterion_id': f.criterion_id,
                'file_path': f.file_path,
                'line_no': f.line_no,
                'evidence_id': f.evidence_id,
            }
            for f in result.findings
        ],
        'evidence_gaps': list(result.evidence_gaps),
        'summary': result.summary,
    }).encode('utf-8')
    write = store.put(raw)
    artifact_id = review_input.id_factory()
    connection.execute(
        'INSERT INTO ARTIFACT '
        '(id, project_id, sha256, media_type, byte_size, relative_path, '
        'retention_class, redaction_state, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            artifact_id,
            review_input.project_id,
            write.sha256,
            review_input.artifact_media_type,
            write.byte_size,
            write.relative_path,
            review_input.artifact_retention_class,
            'none',
            review_input.now,
        ),
    )
    connection.execute(
        'INSERT INTO REVIEW '
        '(id, delivery_attempt_id, reviewer_session_id, reviewed_sha, verdict, '
        'summary_artifact_id, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (
            review_input.review_id,
            review_input.delivery_attempt_id,
            review_input.reviewer_session_id,
            result.reviewed_sha,
            result.verdict,
            artifact_id,
            review_input.now,
        ),
    )
    finding_ids = tuple(review_input.id_factory() for _ in result.findings)
    for finding_id, finding in zip(finding_ids, result.findings, strict=True):
        connection.execute(
            'INSERT INTO REVIEW_FINDING '
            '(id, review_id, severity, state, criterion_id, file_path, line_no, '
            'summary, evidence_id) '
            "VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?)",
            (
                finding_id,
                review_input.review_id,
                finding.severity,
                finding.criterion_id,
                finding.file_path,
                finding.line_no,
                finding.summary,
                finding.evidence_id,
            ),
        )
    connection.commit()
    return RecordedReview(
        review_id=review_input.review_id,
        summary_artifact_id=artifact_id,
        finding_ids=finding_ids,
    )

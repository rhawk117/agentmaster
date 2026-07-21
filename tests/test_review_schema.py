"""Tests for structured independent review recording (SPEC.md §20.3, §23 M21)."""

import json
import sqlite3
import uuid

import pytest

from ledger.artifact_store import ArtifactStore
from ledger.review import (
    MalformedReviewError,
    RecordedReview,
    RecordReviewInput,
    ReviewFindingInput,
    ReviewResult,
    record_review,
    validate_review_result,
)
from tests.conftest import LEDGER_SEED_CREATED_AT, seed_project_run_task

_GOOD_SHA = 'a' * 40


def _id() -> str:
    return str(uuid.uuid4())


def _seed_delivery_attempt(connection, *, run_id: str, head_sha: str = _GOOD_SHA) -> str:
    """A minimal DELIVERY_ATTEMPT row: real ingestion is Microtask 22's job, this
    is only scaffolding so REVIEW's mandatory FK has a row to reference.
    """
    delivery_attempt_id = _id()
    connection.execute(
        'INSERT INTO DELIVERY_ATTEMPT '
        '(id, run_id, attempt_no, branch, base_sha, head_sha, state, created_at) '
        "VALUES (?, ?, 1, 'feat/x', ?, ?, 'open', ?)",
        (delivery_attempt_id, run_id, 'b' * 40, head_sha, LEDGER_SEED_CREATED_AT),
    )
    connection.commit()
    return delivery_attempt_id


def _seed_agent_session(connection, *, run_id: str, role: str = 'reviewer') -> str:
    session_id = _id()
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES (?, ?, ?, 'claude', 'opus', 'active', ?)",
        (session_id, run_id, role, LEDGER_SEED_CREATED_AT),
    )
    connection.commit()
    return session_id


def _result(
    *,
    verdict: str = 'GOOD',
    reviewed_sha: str = _GOOD_SHA,
    findings: tuple[ReviewFindingInput, ...] = (),
    evidence_gaps: tuple[str, ...] = (),
    schema_version: int = 1,
) -> ReviewResult:
    return ReviewResult(
        schema_version=schema_version,
        reviewed_sha=reviewed_sha,
        verdict=verdict,
        findings=findings,
        evidence_gaps=evidence_gaps,
        summary='looks fine',
    )


def _review_input(
    connection, *, run_id: str, reviewer_role: str = 'reviewer'
) -> RecordReviewInput:
    delivery_attempt_id = _seed_delivery_attempt(connection, run_id=run_id)
    reviewer_session_id = _seed_agent_session(
        connection, run_id=run_id, role=reviewer_role
    )
    return RecordReviewInput(
        review_id=_id(),
        delivery_attempt_id=delivery_attempt_id,
        reviewer_session_id=reviewer_session_id,
        project_id='project-1',
        now=LEDGER_SEED_CREATED_AT,
        id_factory=_id,
    )


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(tmp_path / 'artifacts')


# --- validate_review_result ---------------------------------------------------


def test_validate_review_result_accepts_a_well_formed_good_result():
    validate_review_result(_result())


@pytest.mark.parametrize('schema_version', [0, 2, None])
def test_validate_review_result_rejects_unsupported_schema_version(schema_version):
    with pytest.raises(MalformedReviewError, match='schema_version'):
        validate_review_result(_result(schema_version=schema_version))


@pytest.mark.parametrize('bad_sha', ['', 'short', 'g' * 40, 'A' * 40, 'a' * 39])
def test_validate_review_result_rejects_a_malformed_sha(bad_sha):
    with pytest.raises(MalformedReviewError, match='reviewed_sha'):
        validate_review_result(_result(reviewed_sha=bad_sha))


def test_validate_review_result_rejects_an_unknown_verdict():
    with pytest.raises(MalformedReviewError, match='verdict'):
        validate_review_result(_result(verdict='APPROVED'))


def test_validate_review_result_rejects_a_finding_missing_summary():
    finding = ReviewFindingInput(severity='blocker', summary='')
    with pytest.raises(MalformedReviewError, match=r'findings\[0\].summary'):
        validate_review_result(_result(verdict='NEEDS_FIXES', findings=(finding,)))


def test_validate_review_result_rejects_a_finding_missing_severity():
    finding = ReviewFindingInput(severity='', summary='bug found')
    with pytest.raises(MalformedReviewError, match=r'findings\[0\].severity'):
        validate_review_result(_result(verdict='NEEDS_FIXES', findings=(finding,)))


def test_validate_review_result_rejects_a_negative_line_no():
    finding = ReviewFindingInput(severity='minor', summary='nit', line_no=-1)
    with pytest.raises(MalformedReviewError, match='line_no'):
        validate_review_result(_result(verdict='NEEDS_FIXES', findings=(finding,)))


# --- record_review: reviewer identity -----------------------------------------


@pytest.mark.sqlite
def test_record_review_rejects_an_unknown_reviewer_session(ledger_connection, store):
    seed = seed_project_run_task(ledger_connection)
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=seed.run_id)
    review_input = RecordReviewInput(
        review_id=_id(),
        delivery_attempt_id=delivery_attempt_id,
        reviewer_session_id='no-such-session',
        project_id=seed.project_id,
        now=LEDGER_SEED_CREATED_AT,
        id_factory=_id,
    )
    with pytest.raises(MalformedReviewError, match='no AGENT_SESSION row'):
        record_review(ledger_connection, store, review_input, _result())


@pytest.mark.sqlite
def test_record_review_rejects_impersonation_by_an_implementer_session(
    ledger_connection, store
):
    seed = seed_project_run_task(ledger_connection)
    review_input = _review_input(
        ledger_connection, run_id=seed.run_id, reviewer_role='implementer'
    )
    with pytest.raises(MalformedReviewError, match="not 'reviewer'"):
        record_review(ledger_connection, store, review_input, _result())


@pytest.mark.sqlite
def test_record_review_validates_before_writing_anything(ledger_connection, store):
    seed = seed_project_run_task(ledger_connection)
    review_input = _review_input(ledger_connection, run_id=seed.run_id)

    with pytest.raises(MalformedReviewError):
        record_review(ledger_connection, store, review_input, _result(verdict='MAYBE'))

    count = ledger_connection.execute('SELECT COUNT(*) FROM REVIEW').fetchone()[0]
    assert count == 0


# --- record_review: round trip -------------------------------------------------


@pytest.mark.sqlite
def test_record_review_round_trip_persists_verdict_findings_and_evidence_gaps(
    ledger_connection, store
):
    seed = seed_project_run_task(ledger_connection)
    review_input = _review_input(ledger_connection, run_id=seed.run_id)
    findings = (
        ReviewFindingInput(
            severity='blocker',
            summary='SQL injection in query builder',
            criterion_id='criterion-1',
            file_path='ledger/queries.py',
            line_no=42,
        ),
        ReviewFindingInput(severity='minor', summary='unused import'),
    )
    result = _result(
        verdict='NEEDS_FIXES',
        findings=findings,
        evidence_gaps=('no test for the timeout branch',),
    )

    recorded = record_review(ledger_connection, store, review_input, result)

    assert isinstance(recorded, RecordedReview)
    review_row = ledger_connection.execute(
        'SELECT delivery_attempt_id, reviewer_session_id, reviewed_sha, verdict, '
        'summary_artifact_id FROM REVIEW WHERE id = ?',
        (recorded.review_id,),
    ).fetchone()
    assert review_row == (
        review_input.delivery_attempt_id,
        review_input.reviewer_session_id,
        _GOOD_SHA,
        'NEEDS_FIXES',
        recorded.summary_artifact_id,
    )

    finding_rows = ledger_connection.execute(
        'SELECT severity, state, criterion_id, file_path, line_no, summary '
        'FROM REVIEW_FINDING WHERE review_id = ? ORDER BY line_no IS NULL, line_no',
        (recorded.review_id,),
    ).fetchall()
    assert finding_rows == [
        (
            'blocker',
            'open',
            'criterion-1',
            'ledger/queries.py',
            42,
            'SQL injection in query builder',
        ),
        ('minor', 'open', None, None, None, 'unused import'),
    ]

    artifact_sha256 = ledger_connection.execute(
        'SELECT sha256 FROM ARTIFACT WHERE id = ?',
        (recorded.summary_artifact_id,),
    ).fetchone()[0]
    stored = json.loads(store.read(artifact_sha256))
    assert stored['verdict'] == 'NEEDS_FIXES'
    assert stored['evidence_gaps'] == ['no test for the timeout branch']
    assert [f['summary'] for f in stored['findings']] == [
        'SQL injection in query builder',
        'unused import',
    ]


@pytest.mark.sqlite
def test_record_review_with_no_findings_persists_an_empty_list(ledger_connection, store):
    seed = seed_project_run_task(ledger_connection)
    review_input = _review_input(ledger_connection, run_id=seed.run_id)

    recorded = record_review(ledger_connection, store, review_input, _result())

    count = ledger_connection.execute(
        'SELECT COUNT(*) FROM REVIEW_FINDING WHERE review_id = ?', (recorded.review_id,)
    ).fetchone()[0]
    assert count == 0


# --- schema-level FK/CHECK behavior --------------------------------------------


@pytest.mark.sqlite
def test_review_finding_fk_to_review_is_enforced(ledger_connection):
    with pytest.raises(sqlite3.IntegrityError):
        ledger_connection.execute(
            'INSERT INTO REVIEW_FINDING (id, review_id, severity, state, summary) '
            "VALUES ('finding-1', 'no-such-review', 'blocker', 'open', 'x')"
        )


@pytest.mark.sqlite
def test_review_verdict_check_rejects_an_unenumerated_value(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=seed.run_id)
    reviewer_session_id = _seed_agent_session(ledger_connection, run_id=seed.run_id)
    with pytest.raises(sqlite3.IntegrityError):
        ledger_connection.execute(
            'INSERT INTO REVIEW '
            '(id, delivery_attempt_id, reviewer_session_id, reviewed_sha, verdict, '
            'created_at) VALUES (?, ?, ?, ?, ?, ?)',
            (
                'review-1',
                delivery_attempt_id,
                reviewer_session_id,
                _GOOD_SHA,
                'APPROVED',
                LEDGER_SEED_CREATED_AT,
            ),
        )


@pytest.mark.sqlite
def test_review_finding_severity_has_no_check_constraint(ledger_connection):
    """§16.3: CHECK constraints are only for spec-enumerated closed sets; unlike
    REVIEW.verdict (§20.3's explicit "GOOD | NEEDS_FIXES"), severity has no
    spec-enumerated set, so any non-empty value is accepted at the schema level.
    """
    seed = seed_project_run_task(ledger_connection)
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=seed.run_id)
    reviewer_session_id = _seed_agent_session(ledger_connection, run_id=seed.run_id)
    ledger_connection.execute(
        'INSERT INTO REVIEW '
        '(id, delivery_attempt_id, reviewer_session_id, reviewed_sha, verdict, '
        'created_at) VALUES (?, ?, ?, ?, ?, ?)',
        (
            'review-1',
            delivery_attempt_id,
            reviewer_session_id,
            _GOOD_SHA,
            'GOOD',
            LEDGER_SEED_CREATED_AT,
        ),
    )
    ledger_connection.execute(
        'INSERT INTO REVIEW_FINDING (id, review_id, severity, state, summary) '
        "VALUES ('finding-1', 'review-1', 'made-up-severity', 'open', 'x')"
    )
    ledger_connection.commit()

    severity = ledger_connection.execute(
        "SELECT severity FROM REVIEW_FINDING WHERE id = 'finding-1'"
    ).fetchone()[0]
    assert severity == 'made-up-severity'

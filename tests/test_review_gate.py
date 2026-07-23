import uuid

import pytest

from ledger.artifact_store import ArtifactStore
from ledger.orchestrator_state import RunTransitionInput, transition_run
from ledger.review import (
    MalformedReviewError,
    RecordReviewInput,
    ReviewFindingInput,
    ReviewResult,
)
from ledger.review_gate import (
    MAX_REVIEW_ATTEMPTS,
    DeliveryAttemptNotFoundError,
    ReviewGateInput,
    apply_review_result,
)
from tests.conftest import LEDGER_SEED_CREATED_AT, seed_project_run_task

_GOOD_SHA = 'a' * 40
_NEW_SHA = 'c' * 40


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return LEDGER_SEED_CREATED_AT


def _run_input() -> RunTransitionInput:
    return RunTransitionInput(now=_now(), id_factory=_id)


def _to_reviewing(connection, run_id: str) -> None:
    transition_run(connection, run_id, 'Preflight', _run_input())
    _retry_to_reviewing(connection, run_id)


def _retry_to_reviewing(connection, run_id: str) -> None:
    for state in ('Executing', 'Verifying', 'DeliveryPending', 'CIPending'):
        transition_run(connection, run_id, state, _run_input())
    transition_run(connection, run_id, 'ReviewRequired', _run_input())
    transition_run(connection, run_id, 'Reviewing', _run_input())


def _seed_delivery_attempt(connection, *, run_id: str, head_sha: str = _GOOD_SHA) -> str:
    delivery_attempt_id = _id()
    connection.execute(
        'INSERT INTO DELIVERY_ATTEMPT '
        '(id, run_id, attempt_no, branch, base_sha, head_sha, state, created_at) '
        "VALUES (?, ?, 1, 'feat/x', ?, ?, 'open', ?)",
        (delivery_attempt_id, run_id, 'b' * 40, head_sha, LEDGER_SEED_CREATED_AT),
    )
    connection.commit()
    return delivery_attempt_id


def _seed_reviewer_session(connection, *, run_id: str) -> str:
    session_id = _id()
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES (?, ?, 'reviewer', 'claude', 'opus', 'active', ?)",
        (session_id, run_id, LEDGER_SEED_CREATED_AT),
    )
    connection.commit()
    return session_id


def _result(
    *,
    verdict: str = 'GOOD',
    reviewed_sha: str = _GOOD_SHA,
    findings: tuple[ReviewFindingInput, ...] = (),
) -> ReviewResult:
    return ReviewResult(
        schema_version=1,
        reviewed_sha=reviewed_sha,
        verdict=verdict,
        findings=findings,
        evidence_gaps=(),
        summary='result',
    )


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(tmp_path / 'artifacts')


@pytest.fixture
def gated_run(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _to_reviewing(ledger_connection, seed.run_id)
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=seed.run_id)
    reviewer_session_id = _seed_reviewer_session(ledger_connection, run_id=seed.run_id)
    return seed.run_id, delivery_attempt_id, reviewer_session_id


def _review_input(
    delivery_attempt_id: str, reviewer_session_id: str
) -> RecordReviewInput:
    return RecordReviewInput(
        review_id=_id(),
        delivery_attempt_id=delivery_attempt_id,
        reviewer_session_id=reviewer_session_id,
        project_id='project-1',
        now=LEDGER_SEED_CREATED_AT,
        id_factory=_id,
    )


def _gate_input(run_id: str, review_input: RecordReviewInput) -> ReviewGateInput:
    return ReviewGateInput(
        run_id=run_id, review_input=review_input, transition=_run_input()
    )


@pytest.mark.sqlite
def test_good_on_exact_head_moves_to_merge_pending(ledger_connection, store, gated_run):
    run_id, delivery_attempt_id, reviewer_session_id = gated_run

    outcome = apply_review_result(
        ledger_connection,
        store,
        _gate_input(run_id, _review_input(delivery_attempt_id, reviewer_session_id)),
        _result(verdict='GOOD'),
    )

    assert outcome.outcome == 'good'
    assert outcome.run_state == 'MergePending'
    state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run_id,)
    ).fetchone()[0]
    assert state == 'MergePending'


@pytest.mark.sqlite
def test_good_on_a_stale_head_is_not_applied(ledger_connection, store, gated_run):
    run_id, delivery_attempt_id, reviewer_session_id = gated_run

    outcome = apply_review_result(
        ledger_connection,
        store,
        _gate_input(run_id, _review_input(delivery_attempt_id, reviewer_session_id)),
        _result(verdict='GOOD', reviewed_sha=_NEW_SHA),
    )

    assert outcome.outcome == 'stale'
    assert outcome.run_state == 'Reviewing'
    state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run_id,)
    ).fetchone()[0]
    assert state == 'Reviewing'


@pytest.mark.sqlite
def test_needs_fixes_accepts_findings_and_moves_to_fixes_required(
    ledger_connection, store, gated_run
):
    run_id, delivery_attempt_id, reviewer_session_id = gated_run
    finding = ReviewFindingInput(severity='blocker', summary='missing null check')

    outcome = apply_review_result(
        ledger_connection,
        store,
        _gate_input(run_id, _review_input(delivery_attempt_id, reviewer_session_id)),
        _result(verdict='NEEDS_FIXES', findings=(finding,)),
    )

    assert outcome.outcome == 'needs_fixes'
    assert outcome.run_state == 'FixesRequired'
    assert outcome.unresolved_blockers == ('missing null check',)
    finding_state = ledger_connection.execute(
        'SELECT state FROM REVIEW_FINDING WHERE review_id = ?', (outcome.review_id,)
    ).fetchone()[0]
    assert finding_state == 'accepted'
    run_state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run_id,)
    ).fetchone()[0]
    assert run_state == 'FixesRequired'


@pytest.mark.sqlite
def test_retry_ceiling_fails_the_run_and_surfaces_blockers(
    ledger_connection, store, gated_run
):
    run_id, delivery_attempt_id, reviewer_session_id = gated_run
    finding = ReviewFindingInput(severity='blocker', summary='still broken')

    outcome = None
    for _ in range(MAX_REVIEW_ATTEMPTS + 1):
        outcome = apply_review_result(
            ledger_connection,
            store,
            _gate_input(run_id, _review_input(delivery_attempt_id, reviewer_session_id)),
            _result(verdict='NEEDS_FIXES', findings=(finding,)),
        )
        if outcome.outcome != 'retry_ceiling_exhausted':
            _retry_to_reviewing(ledger_connection, run_id)

    assert outcome.outcome == 'retry_ceiling_exhausted'
    assert outcome.run_state == 'Failed'
    assert outcome.unresolved_blockers
    run_state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run_id,)
    ).fetchone()[0]
    assert run_state == 'Failed'


@pytest.mark.sqlite
def test_retry_ceiling_trips_on_exactly_the_max_th_attempt(
    ledger_connection, store, gated_run
):
    run_id, delivery_attempt_id, reviewer_session_id = gated_run
    finding = ReviewFindingInput(severity='blocker', summary='still broken')

    for attempt in range(1, MAX_REVIEW_ATTEMPTS):
        outcome = apply_review_result(
            ledger_connection,
            store,
            _gate_input(run_id, _review_input(delivery_attempt_id, reviewer_session_id)),
            _result(verdict='NEEDS_FIXES', findings=(finding,)),
        )
        assert outcome.outcome == 'needs_fixes', f'attempt {attempt} tripped early'
        _retry_to_reviewing(ledger_connection, run_id)

    outcome = apply_review_result(
        ledger_connection,
        store,
        _gate_input(run_id, _review_input(delivery_attempt_id, reviewer_session_id)),
        _result(verdict='NEEDS_FIXES', findings=(finding,)),
    )

    assert outcome.outcome == 'retry_ceiling_exhausted'
    assert outcome.run_state == 'Failed'


@pytest.mark.sqlite
def test_a_malformed_result_is_never_recorded_or_applied(
    ledger_connection, store, gated_run
):
    run_id, delivery_attempt_id, reviewer_session_id = gated_run

    with pytest.raises(MalformedReviewError):
        apply_review_result(
            ledger_connection,
            store,
            _gate_input(run_id, _review_input(delivery_attempt_id, reviewer_session_id)),
            _result(verdict='SOMETHING_ELSE'),
        )

    count = ledger_connection.execute('SELECT COUNT(*) FROM REVIEW').fetchone()[0]
    assert count == 0
    state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run_id,)
    ).fetchone()[0]
    assert state == 'Reviewing'


@pytest.mark.sqlite
def test_unknown_delivery_attempt_raises(ledger_connection, store, gated_run):
    run_id, _delivery_attempt_id, reviewer_session_id = gated_run

    with pytest.raises(DeliveryAttemptNotFoundError):
        apply_review_result(
            ledger_connection,
            store,
            _gate_input(
                run_id, _review_input('no-such-delivery-attempt', reviewer_session_id)
            ),
            _result(verdict='GOOD'),
        )

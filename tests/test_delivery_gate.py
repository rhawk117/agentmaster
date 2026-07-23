import sqlite3
import uuid

import pytest

from ledger.delivery import (
    CiCheckInput,
    DeliveryAttemptInput,
    next_attempt_no,
    record_ci_check,
    record_delivery_attempt,
    update_delivery_attempt_head,
)
from ledger.delivery_gate import (
    DeliveryAttemptNotFoundError,
    advance_on_green_ci,
    evaluate_ci,
    evaluate_merge_gate,
)
from ledger.orchestrator_state import RunTransitionInput, transition_run
from tests.conftest import LEDGER_SEED_CREATED_AT, seed_project_run_task

_HEAD_A = 'a' * 40
_HEAD_B = 'b' * 40
_NOW = LEDGER_SEED_CREATED_AT


def _id() -> str:
    return str(uuid.uuid4())


def _transition() -> RunTransitionInput:
    return RunTransitionInput(now=_NOW, id_factory=_id)


def _to_ci_pending(connection, run_id: str) -> None:
    for state in ('Preflight', 'Executing', 'Verifying', 'DeliveryPending', 'CIPending'):
        transition_run(connection, run_id, state, _transition())


def _seed_delivery_attempt(connection, *, run_id: str, head_sha: str = _HEAD_A) -> str:
    delivery = DeliveryAttemptInput(
        id=_id(),
        run_id=run_id,
        branch='feat/x',
        base_sha='0' * 40,
        head_sha=head_sha,
        created_at=_NOW,
    )
    record_delivery_attempt(connection, delivery)
    return delivery.id


def _seed_reviewer_session(connection, *, run_id: str) -> str:
    session_id = _id()
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES (?, ?, 'reviewer', 'claude', 'opus', 'active', ?)",
        (session_id, run_id, _NOW),
    )
    connection.commit()
    return session_id


def _seed_review(
    connection,
    *,
    delivery_attempt_id: str,
    reviewer_session_id: str,
    reviewed_sha: str,
    verdict: str = 'GOOD',
) -> None:
    connection.execute(
        'INSERT INTO REVIEW '
        '(id, delivery_attempt_id, reviewer_session_id, reviewed_sha, verdict, '
        'created_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (_id(), delivery_attempt_id, reviewer_session_id, reviewed_sha, verdict, _NOW),
    )
    connection.commit()


def _check(
    delivery_attempt_id: str, name: str, *, head_sha, status, conclusion, observed_at
):
    return CiCheckInput(
        id=_id(),
        delivery_attempt_id=delivery_attempt_id,
        name=name,
        head_sha=head_sha,
        status=status,
        conclusion=conclusion,
        observed_at=observed_at,
    )


@pytest.fixture
def run(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _to_ci_pending(ledger_connection, seed.run_id)
    return seed.run_id


@pytest.mark.sqlite
def test_record_delivery_attempt_assigns_sequential_attempt_numbers(
    ledger_connection, run
):
    first_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    second = DeliveryAttemptInput(
        id=_id(),
        run_id=run,
        branch='feat/x',
        base_sha='0' * 40,
        head_sha=_HEAD_B,
        created_at=_NOW,
    )
    attempt_no = record_delivery_attempt(ledger_connection, second)

    assert attempt_no == 2
    assert next_attempt_no(ledger_connection, run) == 3
    assert first_id


@pytest.mark.sqlite
def test_ci_check_round_trips_and_enforces_the_delivery_attempt_fk(
    ledger_connection, run
):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    check = _check(
        delivery_attempt_id,
        'build',
        head_sha=_HEAD_A,
        status='completed',
        conclusion='success',
        observed_at=_NOW,
    )

    record_ci_check(ledger_connection, check)

    row = ledger_connection.execute(
        'SELECT name, status, conclusion FROM CI_CHECK WHERE id = ?', (check.id,)
    ).fetchone()
    assert row == ('build', 'completed', 'success')

    with pytest.raises(sqlite3.IntegrityError):
        record_ci_check(
            ledger_connection,
            _check(
                'no-such-delivery-attempt',
                'build',
                head_sha=_HEAD_A,
                status='completed',
                conclusion='success',
                observed_at=_NOW,
            ),
        )


@pytest.mark.sqlite
def test_evaluate_ci_is_green_when_every_required_check_succeeds_at_head(
    ledger_connection, run
):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='success',
            observed_at=_NOW,
        ),
    )

    evaluation = evaluate_ci(ledger_connection, delivery_attempt_id, ('build',))

    assert evaluation.outcome == 'green'
    assert evaluation.blocking_reasons == ()


@pytest.mark.sqlite
def test_evaluate_ci_is_pending_when_a_required_check_never_observed(
    ledger_connection, run
):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)

    evaluation = evaluate_ci(ledger_connection, delivery_attempt_id, ('build',))

    assert evaluation.outcome == 'pending'
    assert 'pending' in evaluation.blocking_reasons[0]


@pytest.mark.sqlite
def test_evaluate_ci_rejects_a_failed_check(ledger_connection, run):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='failure',
            observed_at=_NOW,
        ),
    )

    evaluation = evaluate_ci(ledger_connection, delivery_attempt_id, ('build',))

    assert evaluation.outcome == 'failed'
    assert "conclusion 'failure'" in evaluation.blocking_reasons[0]


@pytest.mark.sqlite
def test_evaluate_ci_rejects_a_cancelled_check(ledger_connection, run):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='cancelled',
            observed_at=_NOW,
        ),
    )

    evaluation = evaluate_ci(ledger_connection, delivery_attempt_id, ('build',))

    assert evaluation.outcome == 'failed'
    assert 'cancelled' in evaluation.blocking_reasons[0]


@pytest.mark.sqlite
def test_evaluate_ci_rejects_a_skipped_required_check(ledger_connection, run):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='skipped',
            observed_at=_NOW,
        ),
    )

    evaluation = evaluate_ci(ledger_connection, delivery_attempt_id, ('build',))

    assert evaluation.outcome == 'failed'
    assert 'skipped but required' in evaluation.blocking_reasons[0]


@pytest.mark.sqlite
def test_evaluate_ci_rejects_a_neutral_check(ledger_connection, run):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='neutral',
            observed_at=_NOW,
        ),
    )

    evaluation = evaluate_ci(ledger_connection, delivery_attempt_id, ('build',))

    assert evaluation.outcome == 'failed'
    assert "conclusion 'neutral'" in evaluation.blocking_reasons[0]


@pytest.mark.sqlite
def test_evaluate_ci_rejects_ambiguous_conclusions_at_the_same_head_and_time(
    ledger_connection, run
):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='success',
            observed_at=_NOW,
        ),
    )
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='failure',
            observed_at=_NOW,
        ),
    )

    evaluation = evaluate_ci(ledger_connection, delivery_attempt_id, ('build',))

    assert evaluation.outcome == 'failed'
    assert 'ambiguous' in evaluation.blocking_reasons[0]


@pytest.mark.sqlite
def test_a_head_advance_during_polling_makes_the_prior_green_check_stale(
    ledger_connection, run
):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='success',
            observed_at=_NOW,
        ),
    )
    green_at_old_head = evaluate_ci(ledger_connection, delivery_attempt_id, ('build',))
    assert green_at_old_head.outcome == 'green'

    update_delivery_attempt_head(ledger_connection, delivery_attempt_id, _HEAD_B)

    evaluation = evaluate_ci(ledger_connection, delivery_attempt_id, ('build',))

    assert evaluation.outcome == 'pending'
    assert 'stale' in evaluation.blocking_reasons[0]


@pytest.mark.sqlite
def test_advance_on_green_ci_moves_the_run_to_review_required(ledger_connection, run):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='success',
            observed_at=_NOW,
        ),
    )

    evaluation = advance_on_green_ci(
        ledger_connection, run, delivery_attempt_id, ('build',), _transition()
    )

    assert evaluation.outcome == 'green'
    state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run,)
    ).fetchone()[0]
    assert state == 'ReviewRequired'


@pytest.mark.sqlite
def test_advance_on_failed_ci_moves_the_run_to_fixes_required(ledger_connection, run):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='failure',
            observed_at=_NOW,
        ),
    )

    advance_on_green_ci(
        ledger_connection, run, delivery_attempt_id, ('build',), _transition()
    )

    state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run,)
    ).fetchone()[0]
    assert state == 'FixesRequired'


@pytest.mark.sqlite
def test_advance_on_pending_ci_leaves_run_state_untouched(ledger_connection, run):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)

    advance_on_green_ci(
        ledger_connection, run, delivery_attempt_id, ('build',), _transition()
    )

    state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run,)
    ).fetchone()[0]
    assert state == 'CIPending'


@pytest.mark.sqlite
def test_merge_gate_is_ready_when_pr_ci_and_review_heads_all_match(
    ledger_connection, run
):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    reviewer_session_id = _seed_reviewer_session(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='success',
            observed_at=_NOW,
        ),
    )
    _seed_review(
        ledger_connection,
        delivery_attempt_id=delivery_attempt_id,
        reviewer_session_id=reviewer_session_id,
        reviewed_sha=_HEAD_A,
    )

    result = evaluate_merge_gate(ledger_connection, delivery_attempt_id, ('build',))

    assert result.ready is True
    assert result.blocking_reasons == ()


@pytest.mark.sqlite
def test_merge_gate_demands_re_review_when_the_reviewed_sha_is_stale(
    ledger_connection, run
):
    delivery_attempt_id = _seed_delivery_attempt(
        ledger_connection, run_id=run, head_sha=_HEAD_B
    )
    reviewer_session_id = _seed_reviewer_session(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_B,
            status='completed',
            conclusion='success',
            observed_at=_NOW,
        ),
    )
    _seed_review(
        ledger_connection,
        delivery_attempt_id=delivery_attempt_id,
        reviewer_session_id=reviewer_session_id,
        reviewed_sha=_HEAD_A,
    )

    result = evaluate_merge_gate(ledger_connection, delivery_attempt_id, ('build',))

    assert result.ready is False
    assert any('stale review' in reason for reason in result.blocking_reasons)


@pytest.mark.sqlite
def test_merge_gate_rejects_a_needs_fixes_verdict_even_on_the_exact_head(
    ledger_connection, run
):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    reviewer_session_id = _seed_reviewer_session(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='success',
            observed_at=_NOW,
        ),
    )
    _seed_review(
        ledger_connection,
        delivery_attempt_id=delivery_attempt_id,
        reviewer_session_id=reviewer_session_id,
        reviewed_sha=_HEAD_A,
        verdict='NEEDS_FIXES',
    )

    result = evaluate_merge_gate(ledger_connection, delivery_attempt_id, ('build',))

    assert result.ready is False
    assert any('not GOOD' in reason for reason in result.blocking_reasons)


@pytest.mark.sqlite
def test_merge_gate_blocks_when_ci_has_not_passed_even_with_a_good_review(
    ledger_connection, run
):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    reviewer_session_id = _seed_reviewer_session(ledger_connection, run_id=run)
    _seed_review(
        ledger_connection,
        delivery_attempt_id=delivery_attempt_id,
        reviewer_session_id=reviewer_session_id,
        reviewed_sha=_HEAD_A,
    )

    result = evaluate_merge_gate(ledger_connection, delivery_attempt_id, ('build',))

    assert result.ready is False
    assert any('pending' in reason for reason in result.blocking_reasons)


@pytest.mark.sqlite
def test_merge_gate_blocks_when_ci_concludes_neutral(ledger_connection, run):
    delivery_attempt_id = _seed_delivery_attempt(ledger_connection, run_id=run)
    reviewer_session_id = _seed_reviewer_session(ledger_connection, run_id=run)
    record_ci_check(
        ledger_connection,
        _check(
            delivery_attempt_id,
            'build',
            head_sha=_HEAD_A,
            status='completed',
            conclusion='neutral',
            observed_at=_NOW,
        ),
    )
    _seed_review(
        ledger_connection,
        delivery_attempt_id=delivery_attempt_id,
        reviewer_session_id=reviewer_session_id,
        reviewed_sha=_HEAD_A,
    )

    result = evaluate_merge_gate(ledger_connection, delivery_attempt_id, ('build',))

    assert result.ready is False
    assert any("conclusion 'neutral'" in reason for reason in result.blocking_reasons)


@pytest.mark.sqlite
def test_unknown_delivery_attempt_raises(ledger_connection):
    with pytest.raises(DeliveryAttemptNotFoundError):
        evaluate_ci(ledger_connection, 'no-such-attempt', ('build',))

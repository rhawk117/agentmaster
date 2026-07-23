from typing import TYPE_CHECKING

import pytest
from conftest import LEDGER_SEED_CREATED_AT, seed_project_run_task

from ledger.connection import connect_read_only
from ledger.improvement_policy import (
    PromotionEvaluationInput,
    PromotionThresholds,
    distinct_evidence_project_count,
    evaluate_global_promotion,
    record_promotion_evaluation,
)
from ledger.retrospective import (
    MemoryCandidateProposal,
    RetrospectiveClock,
    RunNotReadyForRetrospectiveError,
    gather_observations,
    propose_memory_candidate,
    run_retrospective,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

_CREATED_AT = LEDGER_SEED_CREATED_AT


def _id_factory() -> Callable[[], str]:
    counter = iter(range(1, 100_000))

    def _next() -> str:
        return f'id-{next(counter)}'

    return _next


def _clock() -> RetrospectiveClock:
    return RetrospectiveClock(now=_CREATED_AT, id_factory=_id_factory())


def _seed_agent_session_with_calls(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    role: str = 'implementer',
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> None:
    session_id = f'agent-session-{role}'
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES (?, ?, ?, 'anthropic', 'claude-sonnet', 'complete', ?)",
        (session_id, run_id, role, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO MODEL_CALL '
        '(id, agent_session_id, model, input_tokens, output_tokens, created_at) '
        "VALUES (?, ?, 'claude-sonnet', ?, ?, ?)",
        (f'{session_id}-call-1', session_id, input_tokens, output_tokens, _CREATED_AT),
    )
    connection.commit()


def _seed_unresolved_review_finding(
    connection: sqlite3.Connection, *, run_id: str
) -> None:
    connection.execute(
        'INSERT INTO DELIVERY_ATTEMPT '
        '(id, run_id, attempt_no, branch, base_sha, head_sha, state, created_at) '
        "VALUES ('attempt-1', ?, 1, 'feat/x', 'aaa', 'bbb', 'open', ?)",
        (run_id, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES ('reviewer-session', ?, 'reviewer', 'anthropic', 'claude-sonnet', "
        "'complete', ?)",
        (run_id, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO REVIEW '
        '(id, delivery_attempt_id, reviewer_session_id, reviewed_sha, verdict, '
        'created_at) '
        "VALUES ('review-1', 'attempt-1', 'reviewer-session', 'bbb', 'NEEDS_FIXES', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO REVIEW_FINDING '
        '(id, review_id, severity, state, summary) '
        "VALUES ('finding-1', 'review-1', 'major', 'open', 'missing test')"
    )
    connection.commit()


def _set_run_state(connection: sqlite3.Connection, run_id: str, state: str) -> None:
    connection.execute('UPDATE RUN SET state = ? WHERE id = ?', (state, run_id))
    connection.commit()


def _read_only(tmp_path) -> sqlite3.Connection:
    return connect_read_only(tmp_path / 'ledger.sqlite3')


@pytest.mark.sqlite
def test_gather_observations_reports_the_run_outcome(ledger_connection, tmp_path):
    seed = seed_project_run_task(ledger_connection)

    read_connection = _read_only(tmp_path)
    try:
        observations = gather_observations(read_connection, seed.run_id)
    finally:
        read_connection.close()

    outcomes = [o for o in observations if o.observation_kind == 'outcome']
    assert len(outcomes) == 1
    assert '0/1 task' in outcomes[0].claim


@pytest.mark.sqlite
def test_gather_observations_includes_token_usage_by_role(ledger_connection, tmp_path):
    seed = seed_project_run_task(ledger_connection)
    _seed_agent_session_with_calls(ledger_connection, run_id=seed.run_id)

    read_connection = _read_only(tmp_path)
    try:
        observations = gather_observations(read_connection, seed.run_id)
    finally:
        read_connection.close()

    efficiency = [o for o in observations if o.observation_kind == 'efficiency']
    assert len(efficiency) == 1
    assert 'implementer' in efficiency[0].claim


@pytest.mark.sqlite
def test_gather_observations_includes_unresolved_review_findings(
    ledger_connection, tmp_path
):
    seed = seed_project_run_task(ledger_connection)
    _seed_unresolved_review_finding(ledger_connection, run_id=seed.run_id)

    read_connection = _read_only(tmp_path)
    try:
        observations = gather_observations(read_connection, seed.run_id)
    finally:
        read_connection.close()

    quality = [o for o in observations if o.observation_kind == 'quality']
    assert len(quality) == 1
    assert quality[0].counterfactual is not None


@pytest.mark.sqlite
def test_gather_observations_includes_feedback(ledger_connection, tmp_path):
    seed = seed_project_run_task(ledger_connection)
    ledger_connection.execute(
        'INSERT INTO FEEDBACK (id, user_session_id, run_id, rating, comment, created_at) '
        "VALUES ('feedback-1', ?, ?, 1, 'nice work', ?)",
        (seed.user_session_id, seed.run_id, _CREATED_AT),
    )
    ledger_connection.commit()

    read_connection = _read_only(tmp_path)
    try:
        observations = gather_observations(read_connection, seed.run_id)
    finally:
        read_connection.close()

    feedback_observations = [o for o in observations if o.observation_kind == 'feedback']
    assert len(feedback_observations) == 1
    assert 'nice work' in feedback_observations[0].claim


@pytest.mark.sqlite
def test_run_retrospective_rejects_a_run_not_yet_retrospective_pending(
    ledger_connection, tmp_path
):
    seed = seed_project_run_task(ledger_connection)
    read_connection = _read_only(tmp_path)

    try:
        with pytest.raises(RunNotReadyForRetrospectiveError):
            run_retrospective(ledger_connection, read_connection, seed.run_id, _clock())
    finally:
        read_connection.close()


@pytest.mark.sqlite
def test_run_retrospective_writes_observations_and_completes_the_run(
    ledger_connection, tmp_path
):
    seed = seed_project_run_task(ledger_connection)
    _set_run_state(ledger_connection, seed.run_id, 'RetrospectivePending')
    read_connection = _read_only(tmp_path)

    try:
        result = run_retrospective(
            ledger_connection, read_connection, seed.run_id, _clock()
        )
    finally:
        read_connection.close()

    assert result.outcome == 'observed'
    assert len(result.observation_ids) >= 1
    row = ledger_connection.execute(
        'SELECT status, run_id FROM RETROSPECTIVE WHERE id = ?',
        (result.retrospective_id,),
    ).fetchone()
    assert row == ('Complete', seed.run_id)
    (run_state,) = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (seed.run_id,)
    ).fetchone()
    assert run_state == 'Complete'


@pytest.mark.sqlite
def test_run_retrospective_is_idempotent_on_retry(ledger_connection, tmp_path):
    seed = seed_project_run_task(ledger_connection)
    _set_run_state(ledger_connection, seed.run_id, 'RetrospectivePending')
    read_connection = _read_only(tmp_path)

    try:
        first = run_retrospective(
            ledger_connection, read_connection, seed.run_id, _clock()
        )
        second = run_retrospective(
            ledger_connection, read_connection, seed.run_id, _clock()
        )
    finally:
        read_connection.close()

    assert first == second
    (observation_count,) = ledger_connection.execute(
        'SELECT COUNT(*) FROM RETRO_OBSERVATION WHERE retrospective_id = ?',
        (first.retrospective_id,),
    ).fetchone()
    assert observation_count == len(first.observation_ids)


@pytest.mark.sqlite
def test_propose_memory_candidate_creates_a_project_scoped_candidate(
    ledger_connection,
):
    seed = seed_project_run_task(ledger_connection)
    ledger_connection.execute(
        'INSERT INTO RETROSPECTIVE (id, run_id, status, created_at) '
        "VALUES ('retro-1', ?, 'Complete', ?)",
        (seed.run_id, _CREATED_AT),
    )
    ledger_connection.execute(
        'INSERT INTO RETRO_OBSERVATION '
        '(id, retrospective_id, observation_kind, claim, created_at) '
        "VALUES ('obs-1', 'retro-1', 'outcome', 'claim', ?)",
        (_CREATED_AT,),
    )
    ledger_connection.execute(
        'INSERT INTO ARTIFACT (id, project_id, sha256, media_type, byte_size, '
        'relative_path, retention_class, redaction_state, created_at) '
        "VALUES ('artifact-1', ?, 'sha', 'text/plain', 1, 'p', 'standard', "
        "'clean', ?)",
        (seed.project_id, _CREATED_AT),
    )
    ledger_connection.execute(
        'INSERT INTO EVIDENCE (id, run_id, artifact_id, evidence_kind, created_at) '
        "VALUES ('evidence-1', ?, 'artifact-1', 'command-result', ?)",
        (seed.run_id, _CREATED_AT),
    )
    ledger_connection.commit()

    proposal = MemoryCandidateProposal(
        memory_id='memory-1',
        project_id=seed.project_id,
        memory_kind='lesson',
        title='retry backoff needs a cap',
        content='observed unbounded retry growth',
        proposing_session_id=None,
        observation_id='obs-1',
        evidence_id='evidence-1',
    )

    memory_id = propose_memory_candidate(
        ledger_connection, proposal, created_at=_CREATED_AT
    )

    state, kind = ledger_connection.execute(
        'SELECT state, memory_kind FROM MEMORY WHERE id = ?', (memory_id,)
    ).fetchone()
    assert (state, kind) == ('Candidate', 'lesson')
    scope_kind, scope_project_id = ledger_connection.execute(
        'SELECT scope_kind, project_id FROM MEMORY_SCOPE WHERE memory_id = ?',
        (memory_id,),
    ).fetchone()
    assert (scope_kind, scope_project_id) == ('project', seed.project_id)
    relation, observation_id = ledger_connection.execute(
        'SELECT relation, observation_id FROM MEMORY_EVIDENCE WHERE memory_id = ?',
        (memory_id,),
    ).fetchone()
    assert (relation, observation_id) == ('proposes', 'obs-1')


def _seed_project(connection: sqlite3.Connection, project_id: str) -> None:
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        'VALUES (?, ?, ?, ?, ?)',
        (project_id, f'/{project_id}', f'fp-{project_id}', _CREATED_AT, _CREATED_AT),
    )
    connection.commit()


def _seed_memory_candidate(connection: sqlite3.Connection, *, memory_id: str) -> None:
    connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, created_at, '
        'updated_at) '
        "VALUES (?, 'project-1', 'Candidate', 'lesson', 'title', 'content', ?, ?)",
        (memory_id, _CREATED_AT, _CREATED_AT),
    )
    connection.commit()


def _seed_evidence_from_project(
    connection: sqlite3.Connection,
    *,
    memory_id: str,
    evidence_id: str,
    run_id: str,
    project_id: str,
) -> None:
    if (
        connection.execute('SELECT 1 FROM PROJECT WHERE id = ?', (project_id,)).fetchone()
        is None
    ):
        _seed_project(connection, project_id)
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        'VALUES (?, ?, ?)',
        (f'user-session-{run_id}', f'harness-{run_id}', _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO RUN (id, project_id, user_session_id, delivery_mode, state, '
        "started_at) VALUES (?, ?, ?, 'local', 'Planned', ?)",
        (run_id, project_id, f'user-session-{run_id}', _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO ARTIFACT (id, project_id, sha256, media_type, byte_size, '
        'relative_path, retention_class, redaction_state, created_at) '
        "VALUES (?, ?, ?, 'text/plain', 1, 'p', 'standard', 'clean', ?)",
        (f'artifact-{evidence_id}', project_id, f'sha-{evidence_id}', _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO EVIDENCE (id, run_id, artifact_id, evidence_kind, created_at) '
        "VALUES (?, ?, ?, 'command-result', ?)",
        (evidence_id, run_id, f'artifact-{evidence_id}', _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO MEMORY_EVIDENCE (memory_id, evidence_id, relation, created_at) '
        "VALUES (?, ?, 'supports', ?)",
        (memory_id, evidence_id, _CREATED_AT),
    )
    connection.commit()


@pytest.mark.sqlite
def test_distinct_evidence_project_count_counts_projects_not_evidence_rows(
    ledger_connection,
):
    _seed_project(ledger_connection, 'project-1')
    _seed_memory_candidate(ledger_connection, memory_id='memory-1')
    _seed_evidence_from_project(
        ledger_connection,
        memory_id='memory-1',
        evidence_id='evidence-1',
        run_id='run-a',
        project_id='project-1',
    )
    _seed_evidence_from_project(
        ledger_connection,
        memory_id='memory-1',
        evidence_id='evidence-2',
        run_id='run-b',
        project_id='project-1',
    )

    count = distinct_evidence_project_count(ledger_connection, 'memory-1')

    assert count == 1


@pytest.mark.sqlite
def test_global_promotion_rejects_repeated_same_project_evidence(ledger_connection):
    _seed_project(ledger_connection, 'project-1')
    _seed_memory_candidate(ledger_connection, memory_id='memory-1')
    for index in range(3):
        _seed_evidence_from_project(
            ledger_connection,
            memory_id='memory-1',
            evidence_id=f'evidence-{index}',
            run_id=f'run-{index}',
            project_id='project-1',
        )

    decision = evaluate_global_promotion(
        ledger_connection, 'memory-1', PromotionThresholds()
    )

    assert decision.decision == 'insufficient_evidence'
    assert decision.distinct_evidence_projects == 1


@pytest.mark.sqlite
def test_global_promotion_accepts_evidence_from_two_distinct_projects(
    ledger_connection,
):
    _seed_project(ledger_connection, 'project-1')
    _seed_memory_candidate(ledger_connection, memory_id='memory-1')
    _seed_evidence_from_project(
        ledger_connection,
        memory_id='memory-1',
        evidence_id='evidence-1',
        run_id='run-a',
        project_id='project-1',
    )
    _seed_evidence_from_project(
        ledger_connection,
        memory_id='memory-1',
        evidence_id='evidence-2',
        run_id='run-b',
        project_id='project-2',
    )

    decision = evaluate_global_promotion(
        ledger_connection, 'memory-1', PromotionThresholds()
    )

    assert decision.decision == 'eligible'
    assert decision.distinct_evidence_projects == 2


@pytest.mark.sqlite
def test_global_promotion_rejects_a_memory_with_contradicting_evidence(
    ledger_connection,
):
    _seed_project(ledger_connection, 'project-1')
    _seed_memory_candidate(ledger_connection, memory_id='memory-1')
    _seed_evidence_from_project(
        ledger_connection,
        memory_id='memory-1',
        evidence_id='evidence-1',
        run_id='run-a',
        project_id='project-1',
    )
    _seed_evidence_from_project(
        ledger_connection,
        memory_id='memory-1',
        evidence_id='evidence-2',
        run_id='run-b',
        project_id='project-2',
    )
    ledger_connection.execute("UPDATE MEMORY SET harmful_count = 1 WHERE id = 'memory-1'")
    ledger_connection.commit()

    decision = evaluate_global_promotion(
        ledger_connection, 'memory-1', PromotionThresholds()
    )

    assert decision.decision == 'contradicted'


@pytest.mark.sqlite
def test_record_promotion_evaluation_writes_evaluation_and_metric_rows(
    ledger_connection,
):
    _seed_project(ledger_connection, 'project-1')
    _seed_memory_candidate(ledger_connection, memory_id='memory-1')
    _seed_evidence_from_project(
        ledger_connection,
        memory_id='memory-1',
        evidence_id='evidence-1',
        run_id='run-a',
        project_id='project-1',
    )
    _seed_evidence_from_project(
        ledger_connection,
        memory_id='memory-1',
        evidence_id='evidence-2',
        run_id='run-b',
        project_id='project-2',
    )
    decision = evaluate_global_promotion(
        ledger_connection, 'memory-1', PromotionThresholds()
    )

    evaluation_id = record_promotion_evaluation(
        ledger_connection,
        decision,
        PromotionEvaluationInput(
            memory_id='memory-1',
            project_id='project-1',
            evaluator_session_id=None,
            id_factory=_id_factory(),
            created_at=_CREATED_AT,
        ),
    )

    decision_column = ledger_connection.execute(
        'SELECT decision FROM EVALUATION WHERE id = ?', (evaluation_id,)
    ).fetchone()[0]
    assert decision_column == 'eligible'
    metric_value = ledger_connection.execute(
        'SELECT value_microunits FROM EVALUATION_METRIC '
        "WHERE evaluation_id = ? AND metric_name = 'distinct_evidence_projects'",
        (evaluation_id,),
    ).fetchone()[0]
    assert metric_value == 2_000_000

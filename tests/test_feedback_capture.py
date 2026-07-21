"""Tests for the feedback-capture loop attached at RUN completion
(SPEC.md §9.1, §17.2, §17.4, §23 Microtask 26).
"""

from typing import TYPE_CHECKING

import pytest
from conftest import LEDGER_SEED_CREATED_AT, seed_project_run_task

from ledger.feedback_capture import (
    FeedbackPrompt,
    capture_feedback,
    register_feedback_capture_hook,
)
from ledger.orchestrator_state import RUN_COMPLETION_HOOKS

if TYPE_CHECKING:
    from collections.abc import Callable

_CREATED_AT = LEDGER_SEED_CREATED_AT


def _id_factory() -> Callable[[], str]:
    counter = iter(range(1, 100_000))

    def _next() -> str:
        return f'id-{next(counter)}'

    return _next


def _seed_evidence_and_observation(connection, *, run_id: str, project_id: str) -> None:
    connection.execute(
        'INSERT INTO ARTIFACT (id, project_id, sha256, media_type, byte_size, '
        'relative_path, retention_class, redaction_state, created_at) '
        "VALUES ('artifact-1', ?, 'sha', 'text/plain', 1, 'p', 'standard', 'clean', ?)",
        (project_id, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO EVIDENCE (id, run_id, artifact_id, evidence_kind, created_at) '
        "VALUES ('evidence-1', ?, 'artifact-1', 'command-result', ?)",
        (run_id, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO RETROSPECTIVE (id, run_id, status, created_at) '
        "VALUES ('retro-1', ?, 'Complete', ?)",
        (run_id, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO RETRO_OBSERVATION '
        '(id, retrospective_id, observation_kind, claim, created_at) '
        "VALUES ('obs-1', 'retro-1', 'outcome', 'claim', ?)",
        (_CREATED_AT,),
    )
    connection.commit()


@pytest.mark.sqlite
def test_capture_feedback_returns_none_and_writes_nothing_when_the_prompt_skips(
    ledger_connection,
):
    seed = seed_project_run_task(ledger_connection)

    feedback_id = capture_feedback(
        ledger_connection,
        seed.run_id,
        prompt=lambda: None,
        id_factory=_id_factory(),
        now=_CREATED_AT,
    )

    assert feedback_id is None
    (count,) = ledger_connection.execute('SELECT COUNT(*) FROM FEEDBACK').fetchone()
    assert count == 0


@pytest.mark.sqlite
def test_capture_feedback_records_a_feedback_row(ledger_connection):
    seed = seed_project_run_task(ledger_connection)

    feedback_id = capture_feedback(
        ledger_connection,
        seed.run_id,
        prompt=lambda: FeedbackPrompt(rating=1, comment='great run'),
        id_factory=_id_factory(),
        now=_CREATED_AT,
    )

    row = ledger_connection.execute(
        'SELECT user_session_id, run_id, rating, comment FROM FEEDBACK WHERE id = ?',
        (feedback_id,),
    ).fetchone()
    assert row == (seed.user_session_id, seed.run_id, 1, 'great run')


@pytest.mark.sqlite
def test_capture_feedback_proposes_a_candidate_linked_via_feedback_memory_id(
    ledger_connection,
):
    seed = seed_project_run_task(ledger_connection)
    _seed_evidence_and_observation(
        ledger_connection, run_id=seed.run_id, project_id=seed.project_id
    )

    feedback_id = capture_feedback(
        ledger_connection,
        seed.run_id,
        prompt=lambda: FeedbackPrompt(rating=1, comment='great run'),
        id_factory=_id_factory(),
        now=_CREATED_AT,
    )

    (memory_id,) = ledger_connection.execute(
        'SELECT memory_id FROM FEEDBACK WHERE id = ?', (feedback_id,)
    ).fetchone()
    assert memory_id is not None
    state, kind = ledger_connection.execute(
        'SELECT state, memory_kind FROM MEMORY WHERE id = ?', (memory_id,)
    ).fetchone()
    assert (state, kind) == ('Candidate', 'user-feedback')


@pytest.mark.sqlite
def test_capture_feedback_neutral_rating_proposes_no_candidate(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    _seed_evidence_and_observation(
        ledger_connection, run_id=seed.run_id, project_id=seed.project_id
    )

    feedback_id = capture_feedback(
        ledger_connection,
        seed.run_id,
        prompt=lambda: FeedbackPrompt(rating=0, comment=None),
        id_factory=_id_factory(),
        now=_CREATED_AT,
    )

    (memory_id,) = ledger_connection.execute(
        'SELECT memory_id FROM FEEDBACK WHERE id = ?', (feedback_id,)
    ).fetchone()
    assert memory_id is None


@pytest.mark.sqlite
def test_capture_feedback_updates_memory_access_and_counts_for_memories_used_in_the_run(
    ledger_connection,
):
    seed = seed_project_run_task(ledger_connection)
    ledger_connection.execute(
        'INSERT INTO MEMORY (id, origin_project_id, state, memory_kind, title, content, '
        'created_at, updated_at) '
        "VALUES ('memory-1', ?, 'Active', 'lesson', 'title', 'content', ?, ?)",
        (seed.project_id, _CREATED_AT, _CREATED_AT),
    )
    ledger_connection.execute(
        'INSERT INTO memory_access '
        '(id, run_id, memory_id, query_digest, rank, score, retrieval_algorithm_version, '
        'created_at) '
        "VALUES ('access-1', ?, 'memory-1', 'digest', 0, 1.0, 'v1', ?)",
        (seed.run_id, _CREATED_AT),
    )
    ledger_connection.commit()

    capture_feedback(
        ledger_connection,
        seed.run_id,
        prompt=lambda: FeedbackPrompt(rating=-1, comment=None),
        id_factory=_id_factory(),
        now=_CREATED_AT,
    )

    helpful, harmful = ledger_connection.execute(
        "SELECT helpful, harmful FROM memory_access WHERE id = 'access-1'"
    ).fetchone()
    assert (helpful, harmful) == (0, 1)
    usefulness_count, harmful_count = ledger_connection.execute(
        "SELECT usefulness_count, harmful_count FROM MEMORY WHERE id = 'memory-1'"
    ).fetchone()
    assert (usefulness_count, harmful_count) == (0, 1)


def test_register_feedback_capture_hook_is_idempotent():
    RUN_COMPLETION_HOOKS.clear()
    try:
        register_feedback_capture_hook()
        register_feedback_capture_hook()
        assert len(RUN_COMPLETION_HOOKS) == 1
    finally:
        RUN_COMPLETION_HOOKS.clear()


@pytest.mark.sqlite
def test_run_completion_hook_fires_capture_feedback_without_blocking_completion(
    ledger_connection,
):
    """A completed RUN transition still succeeds when the hook's prompt is skipped
    (non-interactive session, SPEC.md §9.1: "a feedback prompt never blocks the
    transition to Complete from completing").
    """
    from ledger.orchestrator_state import RunTransitionInput, transition_run

    seed = seed_project_run_task(ledger_connection)
    ledger_connection.execute(
        "UPDATE RUN SET state = 'RetrospectivePending' WHERE id = ?", (seed.run_id,)
    )
    ledger_connection.commit()
    register_feedback_capture_hook()
    try:
        transition_run(
            ledger_connection,
            seed.run_id,
            'Complete',
            RunTransitionInput(now=_CREATED_AT, id_factory=_id_factory()),
        )
    finally:
        RUN_COMPLETION_HOOKS.clear()

    (state,) = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (seed.run_id,)
    ).fetchone()
    assert state == 'Complete'
    (count,) = ledger_connection.execute('SELECT COUNT(*) FROM FEEDBACK').fetchone()
    assert count == 0
